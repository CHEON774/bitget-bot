import asyncio, json, websockets, requests, hmac, hashlib, time, base64
from datetime import datetime
from flask import Flask, request
import threading
import numpy as np

app = Flask(__name__)

API_KEY = 'bg_a9c07aa3168e846bfaa713fe9af79d14'
API_SECRET = '5be628fd41dce5eff78a607f31d096a4911d4e2156b6d66a14be20f027068043'
API_PASSPHRASE = '1q2w3e4r'
TELEGRAM_TOKEN = '7776435078:AAFsM_jIDSx1Eij4YJyqJp-zEDtQVtKohnU'
TELEGRAM_CHAT_ID = '1797494660'

SYMBOLS = {
    "BTCUSDT": {"leverage": 10, "amount": 150},
    "ETHUSDT": {"leverage": 7, "amount": 120}
}

INST_TYPE = "USDT-FUTURES"
CHANNEL = "candle15m"

entry_prices = {s: None for s in SYMBOLS}
positions = {s: None for s in SYMBOLS}  # 'long', 'short', or None
trailing_active = {s: False for s in SYMBOLS}
max_profits = {s: 0 for s in SYMBOLS}
auto_trading = {s: True for s in SYMBOLS}
loss_counts = {s: 0 for s in SYMBOLS}
candles = {s: [] for s in SYMBOLS}


def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
    except:
        pass

def sign(msg, secret):
    return base64.b64encode(hmac.new(secret.encode(), msg.encode(), hashlib.sha256).digest()).decode()

def get_headers(method, path, body=''):
    t = str(int(time.time() * 1000))
    prehash = t + method + path + body
    return {
        'ACCESS-KEY': API_KEY,
        'ACCESS-SIGN': sign(prehash, API_SECRET),
        'ACCESS-TIMESTAMP': t,
        'ACCESS-PASSPHRASE': API_PASSPHRASE,
        'locale': 'en-US'
    }

def get_balance():
    path = "/api/v2/account/all-account-balance"
    url = f"https://api.bitget.com{path}"
    headers = get_headers("GET", path)
    try:
        res = requests.get(url, headers=headers).json()
        for a in res.get("data", []):
            if a.get("accountType") == "futures":
                return float(a.get("usdtBalance", 0))
    except:
        return None

def place_market_order(symbol, side):
    url = "https://api.bitget.com/api/mix/v1/order/place"
    data = {
        "symbol": symbol,
        "marginCoin": "USDT",
        "size": str(SYMBOLS[symbol]["amount"]),
        "side": side,
        "orderType": "market",
        "force": "gtc"
    }
    headers = get_headers("POST", "/api/mix/v1/order/place", json.dumps(data))
    res = requests.post(url, headers=headers, json=data).json()
    return res

def get_price(symbol):
    url = f"https://api.bitget.com/api/mix/v1/market/ticker?symbol={symbol}&productType=USDT-FUTURES"
    try:
        res = requests.get(url).json()
        return float(res["data"].get("last", 0))
    except:
        return 0

def calculate_cci(candles, period=14):
    if len(candles) < period:
        return None
    closes = np.array([float(c[4]) for c in candles[-period:]])
    highs = np.array([float(c[2]) for c in candles[-period:]])
    lows = np.array([float(c[3]) for c in candles[-period:]])
    tps = (highs + lows + closes) / 3
    ma = np.mean(tps)
    md = np.mean(np.abs(tps - ma))
    if md == 0:
        return 0
    return (tps[-1] - ma) / (0.015 * md)

def calculate_adx(candles, period=5):
    if len(candles) < period + 1:
        return None
    highs = np.array([float(c[2]) for c in candles])
    lows = np.array([float(c[3]) for c in candles])
    closes = np.array([float(c[4]) for c in candles])
    plus_dm = highs[1:] - highs[:-1]
    minus_dm = lows[:-1] - lows[1:]
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm < 0] = 0
    tr = np.maximum.reduce([highs[1:] - lows[1:],
                            np.abs(highs[1:] - closes[:-1]),
                            np.abs(lows[1:] - closes[:-1])])
    tr_sum = np.sum(tr[-period:])
    plus_di = 100 * np.sum(plus_dm[-period:]) / tr_sum
    minus_di = 100 * np.sum(minus_dm[-period:]) / tr_sum
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    return dx

def determine_direction(symbol):
    if len(candles[symbol]) < 20:
        return None
    cci = calculate_cci(candles[symbol])
    adx = calculate_adx(candles[symbol])
    if cci is None or adx is None:
        return None
    if cci > 100 and adx > 25:
        return "long"
    elif cci < -100 and adx > 25:
        return "short"
    return None

async def ws_loop():
    uri = "wss://ws.bitget.com/v2/ws/public"
    while True:
        try:
            async with websockets.connect(uri, ping_interval=20, ping_timeout=10) as ws:
                subs = [{"instType": INST_TYPE, "channel": CHANNEL, "instId": s} for s in SYMBOLS]
                await ws.send(json.dumps({"op": "subscribe", "args": subs}))
                send_telegram(f"✅ WebSocket 연결 완료. 잔액: {get_balance()} USDT")

                while True:
                    msg = json.loads(await ws.recv())
                    if msg.get("action") != "update": continue
                    data = msg["data"][0]
                    symbol = msg["arg"]["instId"]
                    price = float(data[4])
                    candles[symbol].append(data)
                    if len(candles[symbol]) > 100:
                        candles[symbol] = candles[symbol][-100:]

                    direction = determine_direction(symbol)
                    if positions[symbol] is None and auto_trading[symbol] and direction:
                        side = "open_long" if direction == "long" else "open_short"
                        res = place_market_order(symbol, side)
                        if res.get("code") == "00000":
                            entry_prices[symbol] = price
                            positions[symbol] = direction
                            trailing_active[symbol] = False
                            max_profits[symbol] = price
                            send_telegram(f"📈 {symbol} {direction.upper()} 진입: {price}")
                        else:
                            send_telegram(f"❌ {symbol} 진입 실패: {res.get('msg')}")

                    elif positions[symbol]:
                        entry = entry_prices[symbol]
                        pos = positions[symbol]
                        profit_pct = ((price - entry) / entry * 100) if pos == "long" else ((entry - price) / entry * 100)
                        if not trailing_active[symbol] and profit_pct >= 3:
                            trailing_active[symbol] = True
                            max_profits[symbol] = price
                            send_telegram(f"⚡ {symbol} 트레일링 시작됨 (+3%)")
                        elif trailing_active[symbol]:
                            if (pos == "long" and price > max_profits[symbol]) or (pos == "short" and price < max_profits[symbol]):
                                max_profits[symbol] = price
                            elif (pos == "long" and price < max_profits[symbol] * 0.995) or (pos == "short" and price > max_profits[symbol] * 1.005):
                                close_side = "close_long" if pos == "long" else "close_short"
                                place_market_order(symbol, close_side)
                                send_telegram(f"❌ {symbol} 청산 @ {price} / 수익률: {profit_pct:.2f}%")
                                positions[symbol] = None
                                if profit_pct < 0:
                                    loss_counts[symbol] += 1
                                    if loss_counts[symbol] >= 3:
                                        auto_trading[symbol] = False
                                        send_telegram(f"⚠️ {symbol} 연속 손절 3회로 중지됨")
                        elif profit_pct <= -2:
                            close_side = "close_long" if pos == "long" else "close_short"
                            place_market_order(symbol, close_side)
                            send_telegram(f"🛑 {symbol} 손절 -2% 청산 @ {price}")
                            positions[symbol] = None
                            loss_counts[symbol] += 1
                            if loss_counts[symbol] >= 3:
                                auto_trading[symbol] = False
                                send_telegram(f"⚠️ {symbol} 연속 손절 3회로 중지됨")
        except Exception as e:
            send_telegram(f"🚨 WebSocket 오류 발생: {e}\n5초 후 재연결 시도")
            await asyncio.sleep(5)

@app.route("/텔레그램", methods=['POST'])
def telegram_webhook():
    msg = request.json.get("message", {}).get("text", "")
    for symbol in SYMBOLS:
        if msg == "/시작":
            auto_trading[symbol] = True
        elif msg == "/중지":
            auto_trading[symbol] = False
        elif msg == "/상태":
            state = "ON" if auto_trading[symbol] else "OFF"
            send_telegram(f"📌 {symbol} 상태: {state} / 손절: {loss_counts[symbol]}")
        elif msg == "/잔액":
            bal = get_balance()
            send_telegram(f"📊 잔액: {bal:.2f} USDT")
        elif msg in ["/이익률", "/수익률"]:
            if positions[symbol]:
                price = get_price(symbol)
                entry = entry_prices[symbol]
                direction = positions[symbol]
                profit_pct = ((price - entry) / entry * 100) if direction == "long" else ((entry - price) / entry * 100)
                send_telegram(f"📈 {symbol} 수익률: {profit_pct:.2f}% ({direction})")
            else:
                send_telegram(f"📈 {symbol} 포지션 없음")
        elif msg == "/포지션":
            if positions[symbol]:
                send_telegram(f"📌 {symbol} {positions[symbol].upper()} 진입가: {entry_prices[symbol]}")
            else:
                send_telegram(f"📌 {symbol} 포지션 없음")
    return "ok"

def run_flask():
    app.run(host="0.0.0.0", port=8080)

if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    asyncio.run(ws_loop())
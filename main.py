import asyncio, json, websockets, requests, hmac, hashlib, time, base64
from datetime import datetime
from flask import Flask, request
import threading

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
positions = {s: False for s in SYMBOLS}
trailing_active = {s: False for s in SYMBOLS}
max_profits = {s: 0 for s in SYMBOLS}
auto_trading = {s: True for s in SYMBOLS}
loss_counts = {s: 0 for s in SYMBOLS}


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
    return requests.post(url, headers=headers, json=data).json()

def get_price(symbol):
    url = f"https://api.bitget.com/api/mix/v1/market/ticker?symbol={symbol}&productType=USDT-FUTURES"
    try:
        res = requests.get(url).json()
        return float(res["data"].get("last", 0))
    except:
        return 0

async def ws_loop():
    uri = "wss://ws.bitget.com/v2/ws/public"
    async with websockets.connect(uri, ping_interval=20) as ws:
        subs = [{"instType": INST_TYPE, "channel": CHANNEL, "instId": s} for s in SYMBOLS]
        await ws.send(json.dumps({"op": "subscribe", "args": subs}))
        send_telegram(f"✅ WebSocket 연결 완료. 잔액: {get_balance()} USDT")

        while True:
            msg = json.loads(await ws.recv())
            if msg.get("action") != "update": continue
            data = msg["data"][0]
            symbol = msg["arg"]["instId"]
            price = float(data[4])

            if not positions[symbol] and auto_trading[symbol] and should_enter():
                place_market_order(symbol, "open_long")
                entry_prices[symbol] = price
                positions[symbol] = True
                trailing_active[symbol] = False
                max_profits[symbol] = price
                send_telegram(f"📈 {symbol} 진입: {price}")

            elif positions[symbol]:
                profit_pct = (price - entry_prices[symbol]) / entry_prices[symbol] * 100
                if not trailing_active[symbol] and profit_pct >= 3:
                    trailing_active[symbol] = True
                    max_profits[symbol] = price
                    send_telegram(f"⚡ {symbol} 트레일링 시작됨 (+3%)")
                elif trailing_active[symbol]:
                    if price > max_profits[symbol]:
                        max_profits[symbol] = price
                    elif price < max_profits[symbol] * 0.995:
                        place_market_order(symbol, "close_long")
                        send_telegram(f"❌ {symbol} 청산 @ {price} / 수익률: {profit_pct:.2f}%")
                        positions[symbol] = False
                        if profit_pct < 0:
                            loss_counts[symbol] += 1
                            if loss_counts[symbol] >= 3:
                                auto_trading[symbol] = False
                                send_telegram(f"⚠️ {symbol} 연속 손절 3회로 중지됨")
                elif profit_pct <= -2:
                    place_market_order(symbol, "close_long")
                    send_telegram(f"🛑 {symbol} 손절 -2% 청산 @ {price}")
                    positions[symbol] = False
                    loss_counts[symbol] += 1
                    if loss_counts[symbol] >= 3:
                        auto_trading[symbol] = False
                        send_telegram(f"⚠️ {symbol} 연속 손절 3회로 중지됨")

def should_enter():
    return True

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
                profit_pct = (price - entry_prices[symbol]) / entry_prices[symbol] * 100
                send_telegram(f"📈 {symbol} 수익률: {profit_pct:.2f}%")
            else:
                send_telegram(f"📈 {symbol} 포지션 없음")
        elif msg == "/포지션":
            if positions[symbol]:
                send_telegram(f"📌 {symbol} 진입가: {entry_prices[symbol]}")
            else:
                send_telegram(f"📌 {symbol} 포지션 없음")
    return "ok"

def run_flask():
    app.run(host="0.0.0.0", port=8080)

if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    asyncio.run(ws_loop())

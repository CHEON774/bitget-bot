import asyncio, json, websockets, requests, hmac, hashlib, time, base64, os
from datetime import datetime
import numpy as np
from websockets.exceptions import ConnectionClosedError
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
MAX_CANDLES = 150
INITIAL_BALANCE = 756

candles = {symbol: [] for symbol in SYMBOLS}
positions = {symbol: 0 for symbol in SYMBOLS}
entry_prices = {symbol: 0 for symbol in SYMBOLS}
trailing_highs = {symbol: 0 for symbol in SYMBOLS}
trailing_active = {symbol: False for symbol in SYMBOLS}
auto_trading_enabled = {symbol: True for symbol in SYMBOLS}
consecutive_losses = {symbol: 0 for symbol in SYMBOLS}


def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message.encode('utf-8')})
    except Exception as e:
        print("❌ 텔레그램 전송 실패:", e)


def sign(message, secret):
    return base64.b64encode(hmac.new(secret.encode(), message.encode(), hashlib.sha256).digest()).decode()


def get_timestamp():
    return str(int(time.time() * 1000))


def get_bitget_headers(method, path, body=''):
    timestamp = get_timestamp()
    pre_hash = timestamp + method + path + body
    signature = sign(pre_hash, API_SECRET)
    return {
        'ACCESS-KEY': API_KEY,
        'ACCESS-SIGN': signature,
        'ACCESS-TIMESTAMP': timestamp,
        'ACCESS-PASSPHRASE': API_PASSPHRASE,
        'locale': 'en-US'
    }


def get_price(symbol):
    url = f"https://api.bitget.com/api/mix/v1/market/ticker?symbol={symbol}&productType=USDT-FUTURES"
    try:
        res = requests.get(url)
        data = res.json()
        if data.get("code") == "00000" and "data" in data:
            return float(data["data"].get("last", 0))
    except:
        return None


def get_account_balance(send=False):
    path = "/api/v2/account/all-account-balance"
    url = f"https://api.bitget.com{path}"
    headers = get_bitget_headers("GET", path)
    try:
        res = requests.get(url, headers=headers)
        data = res.json()
        if data.get("code") == "00000":
            balance = float(next((item["usdtBalance"] for item in data["data"] if item["accountType"] == "futures"), 0))
            if send:
                send_telegram(f"📊 현재 선물 계정 잔액: {balance:.2f} USDT")
            return balance
    except:
        return None


def calculate_cci(candles):
    if len(candles) < 14:
        return None
    typical_prices = [(float(c[1]) + float(c[2]) + float(c[3])) / 3 for c in candles[-14:]]
    tp = typical_prices[-1]
    ma = np.mean(typical_prices)
    md = np.mean([abs(x - ma) for x in typical_prices])
    return (tp - ma) / (0.015 * md) if md else 0


def calculate_adx(candles):
    if len(candles) < 20:
        return 0
    highs = np.array([float(c[2]) for c in candles])
    lows = np.array([float(c[3]) for c in candles])
    closes = np.array([float(c[4]) for c in candles])
    plus_dm = highs[1:] - highs[:-1]
    minus_dm = lows[:-1] - lows[1:]
    tr = np.maximum.reduce([highs[1:] - lows[1:], abs(highs[1:] - closes[:-1]), abs(lows[1:] - closes[:-1])])
    plus_di = 100 * (np.convolve(np.where(plus_dm > minus_dm, plus_dm, 0), np.ones(5), 'valid') / np.convolve(tr, np.ones(5), 'valid'))
    minus_di = 100 * (np.convolve(np.where(minus_dm > plus_dm, minus_dm, 0), np.ones(5), 'valid') / np.convolve(tr, np.ones(5), 'valid'))
    dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
    return np.mean(dx[-5:]) if len(dx) >= 5 else 0


def open_position(symbol, side):
    if positions[symbol] != 0:
        return
    path = "/api/mix/v1/order/place"
    url = f"https://api.bitget.com{path}"
    price = get_price(symbol)
    if not price:
        return
    size = round(SYMBOLS[symbol]["amount"] * SYMBOLS[symbol]["leverage"] / price, 3)
    body = json.dumps({
        "symbol": symbol,
        "marginCoin": "USDT",
        "size": str(size),
        "side": "open_long" if side == "long" else "open_short",
        "orderType": "market",
        "productType": INST_TYPE
    })
    headers = get_bitget_headers("POST", path, body)
    res = requests.post(url, headers=headers, data=body)
    data = res.json()
    if data.get("code") == "00000":
        positions[symbol] = 1 if side == "long" else -1
        entry_prices[symbol] = price
        trailing_highs[symbol] = price
        trailing_active[symbol] = False
        send_telegram(f"✅ {symbol} {side.upper()} 진입! 진입가: {price:.2f}")
    return


def check_exit(symbol):
    price = get_price(symbol)
    if not price or positions[symbol] == 0:
        return
    entry = entry_prices[symbol]
    change = (price - entry) / entry * 100 if positions[symbol] > 0 else (entry - price) / entry * 100
    if change <= -2:
        send_telegram(f"🔻 {symbol} 손절 -2% 실행: {price:.2f}")
        positions[symbol] = 0
        consecutive_losses[symbol] += 1
        if consecutive_losses[symbol] >= 3:
            auto_trading_enabled[symbol] = False
            send_telegram(f"⛔ {symbol} 연속 손절 3회 → 자동매매 중단")
    elif change >= 3:
        trailing_active[symbol] = True
    if trailing_active[symbol]:
        if positions[symbol] > 0:
            trailing_highs[symbol] = max(trailing_highs[symbol], price)
            if price <= trailing_highs[symbol] * 0.995:
                send_telegram(f"📉 {symbol} 트레일링 청산: {price:.2f}")
                positions[symbol] = 0
        else:
            trailing_highs[symbol] = min(trailing_highs[symbol], price)
            if price >= trailing_highs[symbol] * 1.005:
                send_telegram(f"📈 {symbol} 트레일링 청산: {price:.2f}")
                positions[symbol] = 0


async def ws_loop():
    uri = "wss://ws.bitget.com/v2/ws/public"
    async with websockets.connect(uri, ping_interval=20, ping_timeout=10, close_timeout=5) as ws:
        args = [{"instType": INST_TYPE, "channel": CHANNEL, "instId": symbol} for symbol in SYMBOLS]
        await ws.send(json.dumps({"op": "subscribe", "args": args}))
        while True:
            try:
                msg = json.loads(await ws.recv())
                if "data" not in msg:
                    continue
                d = msg["data"][0]
                symbol = msg["arg"]["instId"]
                candles[symbol].append(d)
                candles[symbol] = candles[symbol][-MAX_CANDLES:]
                if auto_trading_enabled[symbol] and len(candles[symbol]) >= MAX_CANDLES:
                    cci = calculate_cci(candles[symbol])
                    adx = calculate_adx(candles[symbol])
                    if positions[symbol] == 0:
                        if cci and adx:
                            if cci > 100 and adx > 25:
                                open_position(symbol, "long")
                            elif cci < -100 and adx > 25:
                                open_position(symbol, "short")
                    else:
                        check_exit(symbol)
            except Exception as e:
                print("WebSocket 오류:", e)
                await asyncio.sleep(5)


def start_ws():
    asyncio.run(ws_loop())


def start_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)


@app.route('/텔레그램', methods=['POST'])
def telegram_webhook():
    data = request.json
    msg = data.get("message", {})
    text = msg.get("text", "")
    if not text:
        return "no message", 200
    if "시작" in text:
        for s in auto_trading_enabled:
            auto_trading_enabled[s] = True
        send_telegram("✅ 자동매매 시작!")
    elif "중지" in text:
        for s in auto_trading_enabled:
            auto_trading_enabled[s] = False
        send_telegram("🛑 자동매매 중단!")
    elif "상태" in text:
        status = [f"{s}: {'ON' if auto_trading_enabled[s] else 'OFF'}" for s in SYMBOLS]
        send_telegram("📈 매매 상태:\n" + "\n".join(status))
    elif "수익률" in text:
        bal = get_account_balance()
        if bal:
            rate = ((bal - INITIAL_BALANCE) / INITIAL_BALANCE) * 100
            send_telegram(f"💰 수익률: {rate:.2f}%")
    elif "포지션" in text:
        for s in SYMBOLS:
            if positions[s] != 0:
                send_telegram(f"📌 {s} {'롱' if positions[s] > 0 else '숏'} | 진입가: {entry_prices[s]:.2f}")
            else:
                send_telegram(f"📌 {s} 포지션 없음")
    return "ok", 200


if __name__ == '__main__':
    get_account_balance(send=True)
    threading.Thread(target=start_ws).start()
    start_flask()


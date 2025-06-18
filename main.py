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
candles = {symbol: [] for symbol in SYMBOLS}
positions = {symbol: None for symbol in SYMBOLS}  # long/short/None
entry_prices = {symbol: None for symbol in SYMBOLS}
trailing_active = {symbol: False for symbol in SYMBOLS}
auto_trading = {symbol: True for symbol in SYMBOLS}
consecutive_losses = {symbol: 0 for symbol in SYMBOLS}


def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
    except Exception as e:
        print("❌ 텔레그램 전송 실패:", e)


def sign(message, secret):
    return base64.b64encode(hmac.new(secret.encode(), message.encode(), hashlib.sha256).digest()).decode()


def get_timestamp():
    return str(int(time.time() * 1000))


def get_headers(method, path, body=''):
    t = get_timestamp()
    prehash = t + method + path + body
    signature = sign(prehash, API_SECRET)
    return {
        'ACCESS-KEY': API_KEY,
        'ACCESS-SIGN': signature,
        'ACCESS-TIMESTAMP': t,
        'ACCESS-PASSPHRASE': API_PASSPHRASE,
        'Content-Type': 'application/json'
    }


def get_price(symbol):
    url = f"https://api.bitget.com/api/mix/v1/market/ticker?symbol={symbol}_UMCBL"
    try:
        res = requests.get(url).json()
        return float(res["data"]["last"])
    except:
        return 0


def calculate_cci(data, period=14):
    tp = np.array([(float(c[1]) + float(c[2]) + float(c[3])) / 3 for c in data])
    ma = np.convolve(tp, np.ones(period) / period, mode='valid')
    md = np.array([np.mean(np.abs(tp[i:i + period] - ma[idx])) for idx, i in enumerate(range(len(tp) - period + 1))])
    cci = (tp[period - 1:] - ma) / (0.015 * md)
    return cci[-1] if len(cci) else None


def calculate_adx(data, period=5):
    highs = np.array([float(c[2]) for c in data])
    lows = np.array([float(c[3]) for c in data])
    closes = np.array([float(c[4]) for c in data])
    plus_dm = highs[1:] - highs[:-1]
    minus_dm = lows[:-1] - lows[1:]
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm < 0] = 0
    tr = np.maximum(highs[1:], closes[:-1]) - np.minimum(lows[1:], closes[:-1])
    atr = np.convolve(tr, np.ones(period)/period, mode='valid')
    plus_di = 100 * (np.convolve(plus_dm, np.ones(period)/period, mode='valid') / atr)
    minus_di = 100 * (np.convolve(minus_dm, np.ones(period)/period, mode='valid') / atr)
    dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = np.convolve(dx, np.ones(period)/period, mode='valid')
    return adx[-1] if len(adx) else None


def determine_direction(symbol):
    data = candles[symbol][-20:]
    if len(data) < 20:
        return None
    cci = calculate_cci(data)
    adx = calculate_adx(data)
    if cci is None or adx is None:
        return None
    if cci > 100 and adx > 25:
        return "long"
    elif cci < -100 and adx > 25:
        return "short"
    return None


def place_market_order(symbol, direction):
    price = get_price(symbol)
    if not price:
        return
    side = "open_long" if direction == "long" else "open_short"
    path = "/api/mix/v1/order/place"
    url = f"https://api.bitget.com{path}"
    data = {
        "symbol": f"{symbol}_UMCBL",
        "marginCoin": "USDT",
        "size": str(round(SYMBOLS[symbol]["amount"] / price, 4)),
        "side": side,
        "orderType": "market",
        "force": "gtc"
    }
    headers = get_headers("POST", path, json.dumps(data))
    try:
        res = requests.post(url, headers=headers, data=json.dumps(data)).json()
        if res.get("code") == "00000":
            entry_prices[symbol] = price
            positions[symbol] = direction
            trailing_active[symbol] = False
            send_telegram(f"📈 {symbol} {direction.upper()} 진입: {price}")
    except Exception as e:
        print(f"진입 실패: {symbol} - {e}")


def check_exit(symbol, price):
    if positions[symbol] is None:
        return
    entry = entry_prices[symbol]
    direction = positions[symbol]
    profit = ((price - entry) / entry * 100) if direction == "long" else ((entry - price) / entry * 100)

    if not trailing_active[symbol] and profit >= 3:
        trailing_active[symbol] = True
        send_telegram(f"⚡ {symbol} 트레일링 시작 (+3%)")

    if trailing_active[symbol]:
        max_price = max(entry, price) if direction == "long" else min(entry, price)
        threshold = max_price * (0.995 if direction == "long" else 1.005)
        if (direction == "long" and price < threshold) or (direction == "short" and price > threshold):
            side = "close_long" if direction == "long" else "close_short"
            path = "/api/mix/v1/order/place"
            url = f"https://api.bitget.com{path}"
            data = {
                "symbol": f"{symbol}_UMCBL",
                "marginCoin": "USDT",
                "size": str(round(SYMBOLS[symbol]["amount"] / entry, 4)),
                "side": side,
                "orderType": "market",
                "force": "gtc"
            }
            headers = get_headers("POST", path, json.dumps(data))
            requests.post(url, headers=headers, data=json.dumps(data))
            send_telegram(f"❌ {symbol} 청산 @ {price} / 수익률: {profit:.2f}%")
            positions[symbol] = None
            if profit < 0:
                consecutive_losses[symbol] += 1
                if consecutive_losses[symbol] >= 3:
                    auto_trading[symbol] = False
                    send_telegram(f"⚠️ {symbol} 연속 손절 3회로 자동매매 중단")

    elif profit <= -2:
        side = "close_long" if direction == "long" else "close_short"
        path = "/api/mix/v1/order/place"
        url = f"https://api.bitget.com{path}"
        data = {
            "symbol": f"{symbol}_UMCBL",
            "marginCoin": "USDT",
            "size": str(round(SYMBOLS[symbol]["amount"] / entry, 4)),
            "side": side,
            "orderType": "market",
            "force": "gtc"
        }
        headers = get_headers("POST", path, json.dumps(data))
        requests.post(url, headers=headers, data=json.dumps(data))
        send_telegram(f"🛑 {symbol} 손절 -2% 청산 @ {price}")
        positions[symbol] = None
        consecutive_losses[symbol] += 1
        if consecutive_losses[symbol] >= 3:
            auto_trading[symbol] = False
            send_telegram(f"⚠️ {symbol} 연속 손절 3회로 자동매매 중단")


async def ws_loop():
    uri = "wss://ws.bitget.com/v2/ws/public"
    async with websockets.connect(uri, ping_interval=20) as ws:
        await ws.send(json.dumps({"op": "subscribe", "args": [
            {"instType": INST_TYPE, "channel": CHANNEL, "instId": f"{symbol}"} for symbol in SYMBOLS
        ]}))
        send_telegram(f"✅ WebSocket 연결됨 / candle15m 구독 완료")
        while True:
            try:
                msg = json.loads(await ws.recv())
                if msg.get("action") != "update": continue
                d = msg["data"][0]
                symbol = msg["arg"]["instId"]
                candles[symbol].append(d)
                if len(candles[symbol]) > 150:
                    candles[symbol] = candles[symbol][-150:]

                price = float(d[4])

                if positions[symbol] is None and auto_trading[symbol]:
                    direction = determine_direction(symbol)
                    if direction:
                        place_market_order(symbol, direction)
                elif positions[symbol]:
                    check_exit(symbol, price)

            except ConnectionClosedError:
                print("🔄 WebSocket 재연결 중...")
                break
            except Exception as e:
                print("에러:", e)
                continue


@app.route('/텔레그램', methods=['POST'])
def telegram_webhook():
    try:
        msg = request.json.get("message", {}).get("text", "")
        for symbol in SYMBOLS:
            if msg == "/시작":
                auto_trading[symbol] = True
                send_telegram(f"🚀 {symbol} 자동매매 시작됨")
            elif msg == "/중지":
                auto_trading[symbol] = False
                send_telegram(f"⏹️ {symbol} 자동매매 중지됨")
            elif msg == "/상태":
                status = "ON" if auto_trading[symbol] else "OFF"
                send_telegram(f"📊 {symbol} 상태: {status} / 손절: {consecutive_losses[symbol]}")
            elif msg == "/수익률":
                if positions[symbol]:
                    price = get_price(symbol)
                    entry = entry_prices[symbol]
                    direction = positions[symbol]
                    profit = ((price - entry) / entry * 100) if direction == "long" else ((entry - price) / entry * 100)
                    send_telegram(f"📈 {symbol} 수익률: {profit:.2f}% ({direction})")
                else:
                    send_telegram(f"📈 {symbol} 포지션 없음")
            elif msg == "/포지션":
                if positions[symbol]:
                    send_telegram(f"📌 {symbol} {positions[symbol].upper()} 진입가: {entry_prices[symbol]}")
                else:
                    send_telegram(f"📌 {symbol} 포지션 없음")
    except Exception as e:
        print("텔레그램 처리 에러:", e)
    return "ok"


if __name__ == '__main__':
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))).start()
    asyncio.run(ws_loop())
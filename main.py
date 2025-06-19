# 기준 코드에 실주문만 추가한 최종본
import asyncio, json, websockets, hmac, hashlib, requests, time
from datetime import datetime
import numpy as np

API_KEY = "bg_a9c07aa3168e846bfaa713fe9af79d14"
API_SECRET = "5be628fd41dce5eff78a607f31d096a4911d4e2156b6d66a14be20f027068043"
API_PASSPHRASE = "1q2w3e4r"
TELEGRAM_TOKEN = "7776435078:AAFsM_jIDSx1Eij4YJyqJp-zEDtQVtKohnU"
TELEGRAM_CHAT_ID = "1797494660"

SYMBOLS = {
    "BTCUSDT": {"leverage": 10, "amount": 150},
    "ETHUSDT": {"leverage": 7, "amount": 120}
}
INST_TYPE = "USDT-FUTURES"
CHANNEL = "candle15m"
MAX_CANDLES = 150

candles = {s: [] for s in SYMBOLS}
cci_values, adx_values, last_prices = {}, {}, {}
positions, trail_highs = {}, {}

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": text})
    except:
        pass

def get_timestamp():
    return str(int(time.time() * 1000))

def sign_request(timestamp, method, path, body=""):
    msg = f"{timestamp}{method}{path}{body}"
    return hmac.new(API_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()

def place_market_order(symbol, side, size):
    url_path = "/api/mix/v1/order/place"
    timestamp = get_timestamp()
    body = json.dumps({
        "symbol": symbol,
        "marginCoin": "USDT",
        "size": str(size),
        "side": side,
        "orderType": "market",
        "tradeSide": side,
        "productType": "umcbl"
    })
    sign = sign_request(timestamp, "POST", url_path, body)
    headers = {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": API_PASSPHRASE,
        "Content-Type": "application/json"
    }
    try:
        res = requests.post("https://api.bitget.com" + url_path, headers=headers, data=body).json()
        print(f"🛒 주문 응답: {res}")
        return res
    except Exception as e:
        print(f"❌ 주문 실패: {e}")
        return None

def calculate_cci(data):
    try:
        tps = [(float(o)+float(h)+float(l))/3 for o,h,l in zip(data[:,1], data[:,2], data[:,3])]
        ma = np.mean(tps)
        md = np.mean(np.abs(tps - ma))
        return (tps[-1] - ma) / (0.015 * md)
    except:
        return None

def calculate_adx(data):
    try:
        highs, lows, closes = data[:,2].astype(float), data[:,3].astype(float), data[:,4].astype(float)
        tr = np.maximum(highs[1:], closes[:-1]) - np.minimum(lows[1:], closes[:-1])
        plus_dm = np.where((highs[1:] - highs[:-1]) > (lows[:-1] - lows[1:]), highs[1:] - highs[:-1], 0)
        minus_dm = np.where((lows[:-1] - lows[1:]) > (highs[1:] - highs[:-1]), lows[:-1] - lows[1:], 0)
        tr_avg = np.mean(tr[-5:])
        plus_di = 100 * (np.mean(plus_dm[-5:]) / tr_avg)
        minus_di = 100 * (np.mean(minus_dm[-5:]) / tr_avg)
        return 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    except:
        return None

def on_msg(msg):
    try:
        if "data" not in msg: return
        arg = msg.get("arg", {})
        symbol = arg.get("instId")
        d = msg["data"][0]
        candles[symbol].append(d)
        if len(candles[symbol]) > MAX_CANDLES:
            candles[symbol].pop(0)
        np_data = np.array(candles[symbol])
        cci = calculate_cci(np_data[-14:])
        adx = calculate_adx(np_data[-6:])
        price = float(d[4])
        cci_values[symbol], adx_values[symbol], last_prices[symbol] = cci, adx, price

        conf = SYMBOLS[symbol]
        size = round(conf["amount"] * conf["leverage"] / price, 4)

        if symbol not in positions:
            if adx is not None and adx > 25:
                if cci is not None and cci > 100:
                    place_market_order(symbol, "open_long", size)
                    positions[symbol] = {"entry": price, "size": size, "side": "open_long"}
                    trail_highs[symbol] = price
                    send_telegram(f"🟢 롱 진입: {symbol} @ {price}")
                elif cci is not None and cci < -100:
                    place_market_order(symbol, "open_short", size)
                    positions[symbol] = {"entry": price, "size": size, "side": "open_short"}
                    trail_highs[symbol] = price
                    send_telegram(f"🔴 숏 진입: {symbol} @ {price}")
        else:
            entry = positions[symbol]["entry"]
            side = positions[symbol]["side"]
            profit = (price - entry) / entry if side == "open_long" else (entry - price) / entry
            trail = trail_highs[symbol]
            if profit >= 0.03:
                trail_highs[symbol] = max(trail, price) if side == "open_long" else min(trail, price)
            if profit <= -0.02 or (profit >= 0.03 and (
                (side == "open_long" and price < trail * 0.995) or
                (side == "open_short" and price > trail * 1.005)
            )):
                place_market_order(symbol, "close_long" if side == "open_long" else "close_short", positions[symbol]["size"])
                send_telegram(f"📤 청산 완료: {symbol} @ {price}")
                del positions[symbol], trail_highs[symbol]

    except Exception as e:
        print(f"⚠️ 메시지 처리 오류: {e}")

async def ws_loop():
    uri = "wss://ws.bitget.com/v2/ws/public"
    async with websockets.connect(uri, ping_interval=20) as ws:
        sub = {
            "op": "subscribe",
            "args": [{"instType": INST_TYPE, "channel": CHANNEL, "instId": s} for s in SYMBOLS]
        }
        await ws.send(json.dumps(sub))
        print("✅ WS 연결됨 / 15분봉 구독 중")
        while True:
            msg = json.loads(await ws.recv())
            if msg.get("action") in ("snapshot", "update"):
                on_msg(msg)

if __name__ == "__main__":
    asyncio.run(ws_loop())


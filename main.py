import asyncio, json, websockets, requests, hmac, hashlib, time, base64
from datetime import datetime, timedelta, timezone
import numpy as np

# === 설정 ===
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
MAX_CANDLES = 100
candles = {symbol: [] for symbol in SYMBOLS}
positions = {}
last_balance_check = datetime.now(timezone.utc)

# === 유틸 ===
def send_telegram(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      data={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
    except Exception as e:
        print("❌ 텔레그램 오류:", e)

def sign(message, secret):
    return base64.b64encode(hmac.new(secret.encode(), message.encode(), hashlib.sha256).digest()).decode()

def get_timestamp():
    return str(int(time.time() * 1000))

def get_headers(method, path, body=''):
    timestamp = get_timestamp()
    pre_hash = timestamp + method + path + body
    signature = sign(pre_hash, API_SECRET)
    return {
        'ACCESS-KEY': API_KEY,
        'ACCESS-SIGN': signature,
        'ACCESS-TIMESTAMP': timestamp,
        'ACCESS-PASSPHRASE': API_PASSPHRASE,
        'Content-Type': 'application/json'
    }

# === 주문 ===
def place_order(symbol, side, size):
    url = "https://api.bitget.com/api/mix/v1/order/place-order"
    data = {
        "symbol": symbol,
        "marginCoin": "USDT",
        "side": side,
        "orderType": "market",
        "size": str(size),
        "tradeSide": side,
        "price": "",
        "timeInForceValue": "normal",
        "leverage": str(SYMBOLS[symbol]["leverage"]),
        "presetTakeProfit": "",
        "presetStopLoss": ""
    }
    headers = get_headers("POST", "/api/mix/v1/order/place-order", json.dumps(data))
    res = requests.post(url, headers=headers, data=json.dumps(data))
    if res.status_code == 200:
        send_telegram(f"✅ 실 주문 전송 완료: {symbol} {side.upper()} ${SYMBOLS[symbol]['amount']}")
    else:
        send_telegram(f"❌ 주문 실패: {res.text}")

# === 지표 ===
def calculate_cci(prices, period=14):
    tp = (prices[:,1] + prices[:,2] + prices[:,3]) / 3
    ma = np.convolve(tp, np.ones(period)/period, mode='valid')
    md = np.array([np.mean(np.abs(tp[i-period+1:i+1] - ma[i-period+1])) for i in range(period-1, len(tp))])
    cci = (tp[period-1:] - ma) / (0.015 * md)
    return cci

def calculate_adx(prices, period=5):
    high, low, close = prices[:,2], prices[:,3], prices[:,4]
    plus_dm = np.where((high[1:] - high[:-1]) > (low[:-1] - low[1:]), high[1:] - high[:-1], 0)
    minus_dm = np.where((low[:-1] - low[1:]) > (high[1:] - high[:-1]), low[:-1] - low[1:], 0)
    tr = np.maximum(high[1:], close[:-1]) - np.minimum(low[1:], close[:-1])
    tr_smooth = np.convolve(tr, np.ones(period)/period, mode='valid')
    plus_di = 100 * np.convolve(plus_dm, np.ones(period)/period, mode='valid') / tr_smooth
    minus_di = 100 * np.convolve(minus_dm, np.ones(period)/period, mode='valid') / tr_smooth
    dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = np.convolve(dx, np.ones(period)/period, mode='valid')
    return adx

# === 전략 ===
def check_strategy(symbol):
    if len(candles[symbol]) < 30:
        return
    prices = np.array(candles[symbol], dtype=float)
    cci = calculate_cci(prices)[-1]
    adx = calculate_adx(prices)[-1]
    price = float(prices[-1][4])
    
    if symbol not in positions:
        if cci > 100 and adx > 25:
            positions[symbol] = {"side": "open_long", "entry": price, "trail": price}
            place_order(symbol, "open_long", SYMBOLS[symbol]["amount"])
        elif cci < -100 and adx > 25:
            positions[symbol] = {"side": "open_short", "entry": price, "trail": price}
            place_order(symbol, "open_short", SYMBOLS[symbol]["amount"])
    else:
        pos = positions[symbol]
        entry = pos["entry"]
        trail = pos["trail"]
        side = pos["side"]
        profit = (price - entry) / entry if "long" in side else (entry - price) / entry

        if profit >= 0.03:
            pos["trail"] = max(trail, price) if "long" in side else min(trail, price)
        elif profit <= -0.02:
            place_order(symbol, "close_long" if "long" in side else "close_short", SYMBOLS[symbol]["amount"])
            positions.pop(symbol)
        elif ("long" in side and price < trail * 0.995) or ("short" in side and price > trail * 1.005):
            place_order(symbol, "close_long" if "long" in side else "close_short", SYMBOLS[symbol]["amount"])
            positions.pop(symbol)

# === WebSocket 처리 ===
def on_message(msg):
    try:
        data = msg["data"][0]
        symbol = data["instId"]
        ts = int(data["ts"])
        k = [ts, float(data["o"]), float(data["h"]), float(data["l"]), float(data["c"]), float(data["v"])]
        if candles[symbol] and candles[symbol][-1][0] == ts:
            candles[symbol][-1] = k
        else:
            candles[symbol].append(k)
            if len(candles[symbol]) > MAX_CANDLES:
                candles[symbol].pop(0)
            check_strategy(symbol)
    except Exception as e:
        print(f"⚠️ 메시지 처리 오류: {e}")

# === WebSocket 루프 ===
async def ws_loop():
    uri = "wss://ws.bitget.com/v2/ws/public"
    async with websockets.connect(uri, ping_interval=20) as ws:
        args = [{"instType": INST_TYPE, "channel": "candle15m", "instId": s} for s in SYMBOLS]
        await ws.send(json.dumps({"op": "subscribe", "args": args}))
        print("✅ WS 연결됨 / 15분봉 구독 중")
        while True:
            try:
                msg = json.loads(await ws.recv())
                if "data" in msg:
                    on_message(msg)

                # 1시간마다 잔액 확인
                global last_balance_check
                if datetime.now(timezone.utc) - last_balance_check > timedelta(hours=1):
                    last_balance_check = datetime.now(timezone.utc)
                    send_telegram("🕒 1시간 경과 - 시스템 동작 중입니다.")

            except Exception as e:
                print(f"⚠️ WebSocket 오류: {e}")
                await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(ws_loop())


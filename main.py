import asyncio, json, websockets, requests, hmac, hashlib, time, base64
from datetime import datetime
import numpy as np
from websockets.exceptions import ConnectionClosedError
import threading

# === 설정 ===
API_KEY = 'bg_a9c07aa3168e846bfaa713fe9af79d14'
API_SECRET = '5be628fd41dce5eff78a607f31d096a4911d4e2156b6d66a14be20f027068043'
API_PASSPHRASE = '1q2w3e4r'
TELEGRAM_TOKEN = '7776435078:AAFsM_jIDSx1Eij4YJyqJp-zEDtQVtKohnU'
TELEGRAM_CHAT_ID = '1797494660'

SYMBOLS = {
    "BTCUSDT": {"leverage": 10, "amount": 150},
    "ETHUSDT": {"leverage": 7, "amount": 120},
}
INST_TYPE = "USDT-FUTURES"
CHANNEL = "candle15m"
MAX_CANDLES = 150
candles = {symbol: [] for symbol in SYMBOLS}
positions = {}

# === 텔레그램 ===
def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
    except Exception as e:
        print(f"❌ 텔레그램 오류: {e}")

# === 서명 ===
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
        'locale': 'en-US'
    }

# === 잔액 확인 ===
def get_account_balance():
    path = "/api/v2/account/all-account-balance"
    url = f"https://api.bitget.com{path}"
    headers = get_headers("GET", path)
    try:
        res = requests.get(url, headers=headers)
        data = res.json()
        if data.get("code") == "00000":
            balance = float(next((x['usdtBalance'] for x in data['data'] if x['accountType'] == 'futures'), 0))
            send_telegram(f"📊 현재 선물 잔액: {balance:.2f} USDT")
    except Exception as e:
        print(f"잔액 조회 실패: {e}")

# === 지표 ===
def calculate_cci(candles, period=14):
    if len(candles) < period:
        return None
    tp = np.array([(c[2] + c[3] + c[4]) / 3 for c in candles[-period:]])
    ma = np.mean(tp)
    md = np.mean(np.abs(tp - ma))
    return (tp[-1] - ma) / (0.015 * md) if md != 0 else 0

def calculate_adx(candles, period=5):
    if len(candles) < period + 1:
        return None
    high = np.array([c[2] for c in candles])
    low = np.array([c[3] for c in candles])
    close = np.array([c[4] for c in candles])
    tr = np.maximum(high[1:], close[:-1]) - np.minimum(low[1:], close[:-1])
    plus_dm = np.where((high[1:] - high[:-1]) > (low[:-1] - low[1:]), high[1:] - high[:-1], 0)
    minus_dm = np.where((low[:-1] - low[1:]) > (high[1:] - high[:-1]), low[:-1] - low[1:], 0)
    atr = np.mean(tr[-period:])
    plus_di = 100 * np.mean(plus_dm[-period:]) / atr if atr != 0 else 0
    minus_di = 100 * np.mean(minus_dm[-period:]) / atr if atr != 0 else 0
    return abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) != 0 else 0

# === 전략 ===
def strategy(symbol):
    cs = candles[symbol]
    if len(cs) < 20:
        return
    cci = calculate_cci(cs, 14)
    adx = calculate_adx(cs, 5)
    price = cs[-1][4]
    if cci is None or adx is None:
        return

    pos = positions.get(symbol)
    if pos is None:
        if cci > 100 and adx > 25:
            positions[symbol] = {"side": "long", "entry": price, "max": price}
            send_telegram(f"🟢 {symbol} 롱 진입 @ {price}")
        elif cci < -100 and adx > 25:
            positions[symbol] = {"side": "short", "entry": price, "min": price}
            send_telegram(f"🔴 {symbol} 숏 진입 @ {price}")
    else:
        entry = pos["entry"]
        side = pos["side"]
        pnl = (price - entry) / entry if side == "long" else (entry - price) / entry

        # 트레일링
        if side == "long":
            pos["max"] = max(pos["max"], price)
            if pos["max"] > entry * 1.03 and price < pos["max"] * 0.995:
                send_telegram(f"🔺 {symbol} 롱 청산 @ {price:.2f} | 트레일링 스탑")
                positions[symbol] = None
        else:
            pos["min"] = min(pos["min"], price)
            if pos["min"] < entry * 0.97 and price > pos["min"] * 1.005:
                send_telegram(f"🔺 {symbol} 숏 청산 @ {price:.2f} | 트레일링 스탑")
                positions[symbol] = None

        # 고정 손절
        if pnl <= -0.02:
            send_telegram(f"🔻 {symbol} 손절 청산 @ {price:.2f} ({pnl*100:.2f}%)")
            positions[symbol] = None

# === 메시지 처리 ===
def on_msg(msg):
    try:
        if not isinstance(msg, dict):
            return
        data = msg.get("data")
        if not isinstance(data, list) or not data:
            return
        d = data[0]
        symbol = d.get("instId")
        if symbol not in SYMBOLS:
            return
        ts = int(d.get("ts", 0))
        k = [ts, float(d["o"]), float(d["h"]), float(d["l"]), float(d["c"]), float(d["v"])]
        if candles[symbol] and candles[symbol][-1][0] == ts:
            candles[symbol][-1] = k
        else:
            candles[symbol].append(k)
            if len(candles[symbol]) > MAX_CANDLES:
                candles[symbol].pop(0)
            strategy(symbol)
    except Exception as e:
        print(f"⚠️ 메시지 처리 오류: {e}")

# === WebSocket 루프 ===
async def ws_loop():
    uri = "wss://ws.bitget.com/v2/ws/public"
    async with websockets.connect(uri, ping_interval=20) as ws:
        args = [{"instType": INST_TYPE, "channel": "candle15m", "instId": s} for s in SYMBOLS]
        await ws.send(json.dumps({"op": "subscribe", "args": args}))
        print("✅ WS 연결됨 / 15분봉 구독 중")
        get_account_balance()
        while True:
            try:
                msg = json.loads(await ws.recv())
                on_msg(msg)
            except Exception as e:
                print(f"⚠️ WebSocket 오류: {e}")
                await asyncio.sleep(5)

# === 잔액 주기적 확인 ===
def balance_checker():
    while True:
        get_account_balance()
        time.sleep(3600)

if __name__ == "__main__":
    threading.Thread(target=balance_checker, daemon=True).start()
    asyncio.run(ws_loop())

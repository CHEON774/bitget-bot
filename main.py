import asyncio, json, websockets, requests, hmac, hashlib, time, base64
from datetime import datetime, timedelta
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
INST_TYPE = "UMCBL"
CHANNEL = "candle15m"
MAX_CANDLES = 100
candles = {symbol: [] for symbol in SYMBOLS}
positions = {symbol: None for symbol in SYMBOLS}
trailing_stops = {symbol: None for symbol in SYMBOLS}
auto_trading_enabled = {symbol: True for symbol in SYMBOLS}
last_balance_check = datetime.utcnow()

# === 함수 ===
def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
    except Exception as e:
        print("❌ 텔레그램 오류:", e)

def sign(msg, secret):
    return base64.b64encode(hmac.new(secret.encode(), msg.encode(), hashlib.sha256).digest()).decode()

def get_timestamp():
    return str(int(time.time() * 1000))

def get_headers(method, path, body=''):
    ts = get_timestamp()
    prehash = ts + method + path + body
    signature = sign(prehash, API_SECRET)
    return {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": signature,
        "ACCESS-TIMESTAMP": ts,
        "ACCESS-PASSPHRASE": API_PASSPHRASE,
        "locale": "en-US"
    }

def get_balance():
    path = "/api/v2/account/all-account-balance"
    url = f"https://api.bitget.com{path}"
    headers = get_headers("GET", path)
    try:
        res = requests.get(url, headers=headers)
        data = res.json()
        if data.get("code") == "00000":
            usdt = next((float(a['usdtBalance']) for a in data['data'] if a['accountType'] == 'futures'), 0)
            return usdt
    except:
        return None

def calculate_cci(data, period=14):
    if len(data) < period:
        return None
    tp = np.array([(float(k[2]) + float(k[3]) + float(k[4])) / 3 for k in data[-period:]])
    ma = np.mean(tp)
    md = np.mean(np.abs(tp - ma))
    return 0 if md == 0 else (tp[-1] - ma) / (0.015 * md)

def calculate_adx(data, period=5):
    if len(data) < period + 1:
        return None
    highs = np.array([float(k[2]) for k in data])
    lows = np.array([float(k[3]) for k in data])
    closes = np.array([float(k[4]) for k in data])
    plus_dm = highs[1:] - highs[:-1]
    minus_dm = lows[:-1] - lows[1:]
    plus_dm = np.where(plus_dm > minus_dm, np.maximum(plus_dm, 0), 0)
    minus_dm = np.where(minus_dm > plus_dm, np.maximum(minus_dm, 0), 0)
    tr = np.maximum(highs[1:], closes[:-1]) - np.minimum(lows[1:], closes[:-1])
    atr = np.mean(tr[-period:])
    plus_di = 100 * np.mean(plus_dm[-period:]) / atr if atr else 0
    minus_di = 100 * np.mean(minus_dm[-period:]) / atr if atr else 0
    return abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) != 0 else 0

def try_entry(symbol, cci, adx, price):
    if positions[symbol] is not None:
        return
    if cci > 100 and adx > 25:
        positions[symbol] = {"side": "long", "entry": price, "trail": False, "max": price}
        send_telegram(f"🟢 {symbol} 롱 진입 @ {price:.2f}")
    elif cci < -100 and adx > 25:
        positions[symbol] = {"side": "short", "entry": price, "trail": False, "max": price}
        send_telegram(f"🔴 {symbol} 숏 진입 @ {price:.2f}")

def try_exit(symbol, price):
    pos = positions[symbol]
    if pos is None:
        return
    entry = pos['entry']
    side = pos['side']
    ratio = (price - entry) / entry * (1 if side == 'long' else -1)
    
    if not pos['trail']:
        if ratio >= 0.03:
            pos['trail'] = True
            pos['max'] = price
    else:
        if side == 'long':
            pos['max'] = max(pos['max'], price)
            if price < pos['max'] * 0.995:
                send_telegram(f"🔺 {symbol} 롱 청산 @ {price:.2f}")
                positions[symbol] = None
        else:
            pos['max'] = min(pos['max'], price)
            if price > pos['max'] * 1.005:
                send_telegram(f"🔺 {symbol} 숏 청산 @ {price:.2f}")
                positions[symbol] = None
    if ratio <= -0.02:
        send_telegram(f"🔻 {symbol} 손절 청산 @ {price:.2f}")
        positions[symbol] = None

def handle_candle(symbol, k):
    candles[symbol].append(k)
    if len(candles[symbol]) > MAX_CANDLES:
        candles[symbol].pop(0)
    cci = calculate_cci(candles[symbol])
    adx = calculate_adx(candles[symbol])
    close = float(k[4])
    if cci is not None and adx is not None:
        send_telegram(f"📊 {symbol} CCI: {cci:.2f} | ADX: {adx:.2f}")
        try_entry(symbol, cci, adx, close)
        try_exit(symbol, close)

# === WebSocket ===
async def ws_loop():
    global last_balance_check
    uri = "wss://ws.bitget.com/v2/ws/public"
    async with websockets.connect(uri, ping_interval=20) as ws:
        args = [{"instType": INST_TYPE, "channel": "candle15m", "instId": s} for s in SYMBOLS]
        await ws.send(json.dumps({"op": "subscribe", "args": args}))
        print("✅ WS 연결됨 / 15분봉 구독 중")
        while True:
            try:
                msg = json.loads(await ws.recv())
                if isinstance(msg.get("data"), list):
                    for d in msg["data"]:
                        symbol = d["instId"]
                        ts = int(d["ts"])
                        candle = [ts, d["o"], d["h"], d["l"], d["c"], d["v"]]
                        handle_candle(symbol, candle)
                # 1시간마다 잔액 알림
                if datetime.utcnow() - last_balance_check > timedelta(hours=1):
                    balance = get_balance()
                    if balance:
                        send_telegram(f"💰 현재 잔액: {balance:.2f} USDT")
                    last_balance_check = datetime.utcnow()
            except Exception as e:
                print(f"⚠️ 메시지 처리 오류: {e}")

# === 시작 ===
if __name__ == "__main__":
    asyncio.run(ws_loop())


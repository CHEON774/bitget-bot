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
    "ETHUSDT": {"leverage": 7, "amount": 120}
}
INST_TYPE = "USDT-FUTURES"
CHANNEL = "candle15m"
MAX_CANDLES = 150
candles = {symbol: [] for symbol in SYMBOLS}

# === 텔레그램 알림 ===
def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message})
    except Exception as e:
        print("❌ 텔레그램 전송 실패:", e)

# === CCI & ADX 계산 ===
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
    plus_dm = np.where((high[1:] - high[:-1]) > (low[:-1] - low[1:]),
                       np.maximum(high[1:] - high[:-1], 0), 0)
    minus_dm = np.where((low[:-1] - low[1:]) > (high[1:] - high[:-1]),
                        np.maximum(low[:-1] - low[1:], 0), 0)
    atr = np.mean(tr[-period:])
    plus_di = 100 * (np.mean(plus_dm[-period:]) / atr) if atr != 0 else 0
    minus_di = 100 * (np.mean(minus_dm[-period:]) / atr) if atr != 0 else 0
    return abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) != 0 else 0

# === 잔액 조회 ===
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

def get_account_balance():
    path = "/api/v2/account/all-account-balance"
    url = f"https://api.bitget.com{path}"
    headers = get_bitget_headers("GET", path)
    try:
        res = requests.get(url, headers=headers)
        data = res.json()
        if data.get("code") == "00000":
            for item in data["data"]:
                if item.get("accountType") == "futures":
                    return float(item.get("usdtBalance", 0))
    except:
        return None

# === 메시지 처리 ===
def on_msg(d):
    symbol = d["instId"]
    ts = int(d["ts"])
    o, h, l, c, v = map(float, [d["o"], d["h"], d["l"], d["c"], d["v"]])
    kline = [ts, o, h, l, c, v]
    candles[symbol].append(kline)
    if len(candles[symbol]) > MAX_CANDLES:
        candles[symbol].pop(0)
    
    if ts % (15 * 60 * 1000) == 0:
        cci = calculate_cci(candles[symbol])
        adx = calculate_adx(candles[symbol])
        send_telegram(f"[{symbol}] 가격: {c:.2f}\nCCI: {cci:.2f} | ADX: {adx:.2f}")

# === WebSocket 연결 ===
async def ws_loop():
    uri = "wss://ws.bitget.com/v2/ws/public"
    async with websockets.connect(uri, ping_interval=20) as ws:
        args = [{"instType": INST_TYPE, "channel": "candle15m", "instId": s} for s in SYMBOLS]
        await ws.send(json.dumps({"op": "subscribe", "args": args}))
        print("✅ WS 연결됨 / 15분봉 구독 중")
        send_telegram("✅ 자동매매 봇 실행됨. 잔액 및 지표 모니터링 시작")
        balance = get_account_balance()
        if balance:
            send_telegram(f"💰 현재 잔액: {balance:.2f} USDT")

        # 1시간마다 잔액 알림 스레드 시작
        def hourly_balance():
            while True:
                b = get_account_balance()
                if b:
                    send_telegram(f"⏰ 1시간 알림 - 현재 잔액: {b:.2f} USDT")
                time.sleep(3600)
        threading.Thread(target=hourly_balance, daemon=True).start()

        while True:
            try:
                msg = json.loads(await ws.recv())
                if "data" in msg:
                    for d in msg["data"]:
                        try:
                            on_msg(d)
                        except Exception as e:
                            print(f"⚠️ 메시지 처리 오류: {e}")
            except Exception as e:
                print(f"⚠️ WebSocket 오류: {e}")
                await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(ws_loop())


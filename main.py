import asyncio, json, websockets, requests, hmac, hashlib, time, base64
from datetime import datetime
import numpy as np
from websockets.exceptions import ConnectionClosedError
import threading

# === 기본 설정 ===
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

# === 텔레그램 ===
def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message})
    except Exception as e:
        print("❌ 텔레그램 전송 실패:", e)

# === API 서명 ===
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

# === 잔액 조회 ===
def get_account_balance(send=False):
    path = "/api/v2/account/all-account-balance"
    url = f"https://api.bitget.com{path}"
    headers = get_headers("GET", path)
    try:
        res = requests.get(url, headers=headers)
        data = res.json()
        if data.get("code") == "00000":
            balance = float(next((item["usdtBalance"] for item in data["data"] if item["accountType"] == "futures"), 0))
            if send:
                send_telegram(f"\ud83d\udcca 현재 선물 계정 잔액: {balance:.2f} USDT")
            return balance
    except Exception as e:
        print("잔액 조회 오류:", e)
    return None

# === 메시지 핸들러 ===
def on_msg(msg):
    try:
        data_list = msg.get("data", [])
        if not isinstance(data_list, list) or not data_list:
            return
        d = data_list[0]

        symbol = d.get("instId")
        ts = int(d["ts"])
        k = [ts, float(d["o"]), float(d["h"]), float(d["l"]), float(d["c"]), float(d["v"])]

        if ts % (15 * 60 * 1000) == 0:
            candles[symbol].append(k)
            if len(candles[symbol]) > MAX_CANDLES:
                candles[symbol].pop(0)
            print(f"✅ 완성된 캔들: {symbol} | {datetime.fromtimestamp(ts/1000)}")

    except Exception as e:
        print(f"⚠️ 메시지 처리 오류: {e}")

# === 잔액 알림 루프 ===
def balance_loop():
    while True:
        get_account_balance(send=True)
        time.sleep(3600)

# === WebSocket ===
async def ws_loop():
    uri = "wss://ws.bitget.com/v2/ws/public"
    try:
        async with websockets.connect(uri, ping_interval=20) as ws:
            args = [{"instType": INST_TYPE, "channel": CHANNEL, "instId": s} for s in SYMBOLS]
            await ws.send(json.dumps({"op": "subscribe", "args": args}))
            print("✅ WS 연결됨 / 15분봉 구독 중")
            send_telegram("✅ 자동매매 봇 실행됨 (15분봉 캔들 수신 시작)")
            get_account_balance(send=True)
            while True:
                msg = json.loads(await ws.recv())
                if "data" in msg:
                    on_msg(msg)
    except Exception as e:
        print(f"⚠️ WebSocket 오류: {e}")
        send_telegram(f"❌ WebSocket 오류 발생: {e}")

# === 실행 ===
if __name__ == "__main__":
    threading.Thread(target=balance_loop, daemon=True).start()
    asyncio.run(ws_loop())

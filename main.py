import asyncio, json, websockets, requests, hmac, hashlib, time, base64
from datetime import datetime
import numpy as np
from websockets.exceptions import ConnectionClosedError
from flask import Flask, request
import threading

# Flask 앱 시작
app = Flask(__name__)

# Bitget API 인증 정보
API_KEY = 'bg_a9c07aa3168e846bfaa713fe9af79d14'
API_SECRET = '5be628fd41dce5eff78a607f31d096a4911d4e2156b6d66a14be20f027068043'
API_PASSPHRASE = '1q2w3e4r'

# 텔레그램 알림 설정
TELEGRAM_TOKEN = '7776435078:AAFsM_jIDSx1Eij4YJyqJp-zEDtQVtKohnU'
TELEGRAM_CHAT_ID = '1797494660'

# 거래 설정
SYMBOLS = {
    "BTCUSDT": {"leverage": 10, "amount": 150},
    "ETHUSDT": {"leverage": 7, "amount": 120}
}
CHANNEL = "candle15m"
INST_TYPE = "USDT-FUTURES"
MAX_CANDLES = 150
candles = {symbol: [] for symbol in SYMBOLS.keys()}
positions = {}
entry_prices = {}
trailing_active = {}
consecutive_losses = {symbol: 0 for symbol in SYMBOLS.keys()}
auto_trading_enabled = {symbol: True for symbol in SYMBOLS.keys()}


def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message})
    except Exception as e:
        print("❌ 텔레그램 전송 실패:", e, flush=True)


def sign(message, secret_key):
    mac = hmac.new(bytes(secret_key, encoding='utf8'),
                   bytes(message, encoding='utf-8'), digestmod='sha256')
    return base64.b64encode(mac.digest()).decode()


def get_timestamp():
    return str(int(time.time() * 1000))


def get_bitget_headers(method, path, body=''):
    timestamp = get_timestamp()
    pre_hash = timestamp + method + path + body
    signature = sign(pre_hash, API_SECRET)
    headers = {
        'ACCESS-KEY': API_KEY,
        'ACCESS-SIGN': signature,
        'ACCESS-TIMESTAMP': timestamp,
        'ACCESS-PASSPHRASE': API_PASSPHRASE,
        'locale': 'en-US'
    }
    return headers


def get_account_balance(send_alert=False):
    path = "/api/v2/account/all-account-balance"
    url = f"https://api.bitget.com{path}"
    headers = get_bitget_headers("GET", path)
    try:
        res = requests.get(url, headers=headers)
        res.raise_for_status()
        data = res.json()
        if data.get("code") == "00000":
            futures_balance = next((item["usdtBalance"] for item in data["data"] if item["accountType"] == "futures"), None)
            print(f"✅ 선물 계정 잔액: {futures_balance} USDT", flush=True)
            if send_alert:
                send_telegram(f"📊 Bitget 선물 계정 잔액: {futures_balance} USDT")
            return futures_balance
        else:
            print("❌ 잔액 조회 실패: 응답 코드 오류", data, flush=True)
            return None
    except requests.exceptions.RequestException as e:
        print("❌ 잔액 조회 실패:", e, flush=True)
        return None


def place_order(symbol, side, amount):
    path = '/api/mix/v1/order/place'
    url = f'https://api.bitget.com{path}'
    data = {
        "symbol": symbol,
        "marginCoin": "USDT",
        "size": str(amount),
        "side": side,
        "orderType": "market",
        "tradeSide": side,
        "productType": "USDT-FUTURES"
    }
    headers = get_bitget_headers('POST', path, json.dumps(data))
    try:
        res = requests.post(url, headers=headers, json=data)
        res.raise_for_status()
        print(f"✅ 주문 완료: {symbol} {side} {amount}")
    except requests.exceptions.RequestException as e:
        print("❌ 주문 실패:", e)


@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def telegram_webhook():
    data = request.get_json()
    if "message" in data:
        text = data["message"].get("text", "")
        chat_id = data["message"]["chat"]["id"]

        if text == "/상태":
            msg = "\n".join([f"{s}: {'✅ 작동 중' if auto_trading_enabled[s] else '⛔ 중지됨'}" for s in SYMBOLS])
            send_telegram(msg)
        elif text.startswith("/중지 "):
            sym = text.split()[1]
            auto_trading_enabled[sym] = False
            send_telegram(f"⛔ {sym} 자동매매 중지함")
        elif text.startswith("/시작 "):
            sym = text.split()[1]
            auto_trading_enabled[sym] = True
            send_telegram(f"✅ {sym} 자동매매 다시 시작함")
        elif text == "/잔액":
            bal = get_account_balance()
            send_telegram(f"📊 현재 잔액: {bal} USDT")

    return "ok"


def run_flask():
    app.run(host="0.0.0.0", port=5000)


flask_thread = threading.Thread(target=run_flask)
flask_thread.start()

get_account_balance(send_alert=True)
# asyncio.run(ws_loop())  # 여기에 WebSocket 루프를 실행시키는 코드 넣으세요
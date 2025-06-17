import asyncio, json, websockets, requests, hmac, hashlib, time, base64
from datetime import datetime
import numpy as np
from websockets.exceptions import ConnectionClosedError
from flask import Flask, request

app = Flask(__name__)

# Bitget API 인증 정보
API_KEY = 'bg_a9c07aa3168e846bfaa713fe9af79d14'
API_SECRET = '5be628043'
API_PASSPHRASE = '1q2w3e4r'

# 텔레그램 설정
TELEGRAM_TOKEN = '7776435078:AAFsM_jIDSx1Eij4YJyqJp-zEDtQVtKohnU'
TELEGRAM_CHAT_ID = '1797494660'
BASE_BALANCE = 756  # 기준 잔액

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

# 텔레그램 전송 함수
def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message})
    except Exception as e:
        print("❌ 텔레그램 전송 실패:", e, flush=True)

# 서명 생성

def sign(message, secret_key):
    mac = hmac.new(bytes(secret_key, encoding='utf8'),
                   bytes(message, encoding='utf-8'), digestmod='sha256')
    return base64.b64encode(mac.digest()).decode()

# 시간 생성

def get_timestamp():
    return str(int(time.time() * 1000))

# 인증 헤더 생성

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

# 잔액 조회 함수

def get_account_balance(send=False):
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
            if send:
                send_telegram(f"📊 현재 선물 계정 잔액: {futures_balance} USDT")
            return float(futures_balance)
        else:
            print("❌ 잔액 조회 실패: 응답 코드 오류", data, flush=True)
    except requests.exceptions.RequestException as e:
        print("❌ 잔액 조회 실패:", e, flush=True)
    return None

# 텔레그램 Webhook 처리
@app.route('/', methods=['POST'])
def telegram_webhook():
    data = request.get_json()
    if 'message' in data and 'text' in data['message']:
        text = data['message']['text'].strip()

        if text == '/잔액':
            get_account_balance(send=True)

        elif text == '/이익':
            current = get_account_balance()
            if current is not None:
                profit = current - BASE_BALANCE
                send_telegram(f"💰 기준대비 이익: {profit:.2f} USDT")

        elif text == '/수익':
            current = get_account_balance()
            if current is not None:
                diff = current - BASE_BALANCE
                rate = (diff / BASE_BALANCE) * 100
                send_telegram(f"📈 기준대비 수익률: {rate:.2f}% (+{diff:.2f} USDT)")

    return 'ok'

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

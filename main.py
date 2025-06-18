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
positions = {symbol: None for symbol in SYMBOLS}
entry_prices = {}
trailing_active = {}
auto_trading = {symbol: True for symbol in SYMBOLS}
consecutive_losses = {symbol: 0 for symbol in SYMBOLS}


def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message})
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
        res = requests.get(url)
        data = res.json()
        if data.get("code") == "00000" and "data" in data:
            return float(data["data"].get("last", 0))
    except:
        return None


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
        "size": str(SYMBOLS[symbol]["amount"] / price),
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


# 이하 청산 로직 등 유지...

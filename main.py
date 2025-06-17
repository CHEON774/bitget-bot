import asyncio, json, websockets, requests, hmac, hashlib, time, base64
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
positions = {}
entry_prices = {}
trailing_active = {}
auto_trading_enabled = {symbol: True for symbol in SYMBOLS}
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

def get_price(symbol):
    url = f"https://api.bitget.com/api/mix/v1/market/ticker?symbol={symbol}&productType=USDT-FUTURES"
    try:
        res = requests.get(url)
        data = res.json()
        if data.get("code") == "00000" and "data" in data:
            return float(data["data"].get("last", 0))
    except:
        return None

def get_account_balance(send=False):
    path = "/api/v2/account/all-account-balance"
    url = f"https://api.bitget.com{path}"
    headers = get_bitget_headers("GET", path)
    try:
        res = requests.get(url, headers=headers)
        data = res.json()
        if data.get("code") == "00000":
            balance = float(next((item["usdtBalance"] for item in data["data"] if item["accountType"] == "futures"), 0))
            if send:
                send_telegram(f"📊 현재 선물 계정 잔액: {balance:.2f} USDT")
            return balance
    except:
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
        requests.post(url, headers=headers, json=data)
    except:
        pass

def calculate_cci(candles, period=14):
    if len(candles) < period:
        return None
    tp = [(float(c[2]) + float(c[3]) + float(c[4])) / 3 for c in candles[-period:]]
    ma = np.mean(tp)
    md = np.mean(np.abs(tp - ma))
    return 0 if md == 0 else (tp[-1] - ma) / (0.015 * md)

def calculate_adx(candles, period=5):
    if len(candles) < period + 1:
        return None
    highs = np.array([float(c[2]) for c in candles])
    lows = np.array([float(c[3]) for c in candles])
    closes = np.array([float(c[4]) for c in candles])
    tr = np.maximum(highs[1:], closes[:-1]) - np.minimum(lows[1:], closes[:-1])
    plus_dm = np.where((highs[1:] - highs[:-1]) > (lows[:-1] - lows[1:]), np.maximum(highs[1:] - highs[:-1], 0), 0)
    minus_dm = np.where((lows[:-1] - lows[1:]) > (highs[1:] - highs[:-1]), np.maximum(lows[:-1] - lows[1:], 0), 0)
    atr = np.mean(tr[-period:])
    plus_di = 100 * (np.mean(plus_dm[-period:]) / atr) if atr else 0
    minus_di = 100 * (np.mean(minus_dm[-period:]) / atr) if atr else 0
    return abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) != 0 else 0

def handle_candle(symbol, data):
    ts, o, h, l, c, v = int(data[0]), *data[1:6]
    candle = [ts, o, h, l, c, v]
    store = candles[symbol]
    if store and store[-1][0] == ts:
        store[-1] = candle
    else:
        store.append(candle)
        if len(store) > MAX_CANDLES:
            store.pop(0)
        if not auto_trading_enabled[symbol] or len(store) < 20:
            return
        if entry_prices.get(symbol) and positions.get(symbol):
            entry = entry_prices[symbol]
            pnl = (float(c) - entry) / entry * 100 if positions[symbol] == 'long' else (entry - float(c)) / entry * 100
            if pnl >= 2:
                if not trailing_active[symbol]:
                    trailing_active[symbol] = float(c)
                else:
                    trailing_active[symbol] = max(trailing_active[symbol], float(c))
            if trailing_active[symbol] and (
                (positions[symbol] == 'long' and float(c) < trailing_active[symbol] * 0.995) or
                (positions[symbol] == 'short' and float(c) > trailing_active[symbol] * 1.005)
            ):
                send_telegram(f"💰 {symbol} 트레일링 스탑 청산! 수익률: {pnl:.2f}%")
                place_order(symbol, 'close_long' if positions[symbol] == 'long' else 'close_short', SYMBOLS[symbol]['amount'])
                if pnl < 0:
                    consecutive_losses[symbol] += 1
                    if consecutive_losses[symbol] >= 3:
                        auto_trading_enabled[symbol] = False
                        send_telegram(f"⚠️ {symbol} 3연속 손실로 자동매매 중지됨")
                else:
                    consecutive_losses[symbol] = 0
                positions[symbol] = None
                entry_prices[symbol] = None
                trailing_active[symbol] = None
        cci = calculate_cci(store[:-1], 14)
        adx = calculate_adx(store[:-1], 5)
        if cci is None or adx is None:
            return
        if adx > 25:
            if cci > 100 and positions.get(symbol) != 'long':
                send_telegram(f"🚨 {symbol} 진입조건 충족: 롱 진입 예정")
                positions[symbol] = 'long'
                entry_prices[symbol] = float(c)
                trailing_active[symbol] = None
                send_telegram(f"🚀 {symbol} 롱 진입 @ {c}")
                place_order(symbol, 'open_long', SYMBOLS[symbol]['amount'])
            elif cci < -100 and positions.get(symbol) != 'short':
                send_telegram(f"🚨 {symbol} 진입조건 충족: 숏 진입 예정")
                positions[symbol] = 'short'
                entry_prices[symbol] = float(c)
                trailing_active[symbol] = None
                send_telegram(f"🔻 {symbol} 숏 진입 @ {c}")
                place_order(symbol, 'open_short', SYMBOLS[symbol]['amount'])

async def ws_loop():
    uri = "wss://ws.bitget.com/v2/ws/public"
    while True:
        try:
            async with websockets.connect(uri, ping_interval=20) as ws:
                args = [{"instType": INST_TYPE, "channel": CHANNEL, "instId": symbol} for symbol in SYMBOLS]
                await ws.send(json.dumps({"op": "subscribe", "args": args}))
                print("✅ WebSocket 연결 완료")
                while True:
                    msg = json.loads(await ws.recv())
                    if msg.get("action") in ("snapshot", "update"):
                        symbol = msg["arg"]["instId"]
                        if symbol in SYMBOLS:
                            handle_candle(symbol, msg["data"][0])
        except Exception as e:
            print("❌ WebSocket 오류:", e)
            await asyncio.sleep(5)

@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    data = request.get_json()
    if 'message' in data and 'text' in data['message']:
        text = data['message']['text'].strip()
        if text in ["/시작"]:
            for k in auto_trading_enabled:
                auto_trading_enabled[k] = True
            send_telegram("✅ 자동매매 시작됨")
        elif text in ["/중지"]:
            for k in auto_trading_enabled:
                auto_trading_enabled[k] = False
            send_telegram("🛑 자동매매 중지됨")
        elif text in ["/상태"]:
            msg = "📊 현재 상태\n"
            for k in auto_trading_enabled:
                msg += f"{k}: {'ON' if auto_trading_enabled[k] else 'OFF'}\n"
            send_telegram(msg)
        elif text == "/잔액":
            balance = get_account_balance()
            send_telegram(f"💰 현재 잔액: {balance:.2f} USDT")
        elif text == "/이익":
            balance = get_account_balance()
            profit = balance - INITIAL_BALANCE
            send_telegram(f"📈 총 이익: {profit:.2f} USDT")
        elif text == "/수익":
            balance = get_account_balance()
            percent = ((balance - INITIAL_BALANCE) / INITIAL_BALANCE) * 100
            send_telegram(f"📊 수익률: {percent:.2f}%")
        elif text == "/시세":
            btc = get_price("BTCUSDT")
            eth = get_price("ETHUSDT")
            if btc and eth:
                send_telegram(f"📈 현재 시세\nBTCUSDT: {btc:.2f} USDT\nETHUSDT: {eth:.2f} USDT")
            else:
                send_telegram("❌ 시세 정보를 가져오지 못했습니다.")
    return "ok"

if __name__ == '__main__':
    threading.Thread(target=lambda: asyncio.run(ws_loop()), daemon=True).start()
    get_account_balance(send=True)
    app.run(host='0.0.0.0', port=5000)
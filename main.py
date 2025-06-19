import asyncio, json, websockets, requests, hmac, hashlib, time, base64
from datetime import datetime
import numpy as np
from websockets.exceptions import ConnectionClosedError
import threading

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
MAX_CANDLES = 150

candles = {symbol: [] for symbol in SYMBOLS}
positions = {}
entry_prices = {}
trailing_active = {}
auto_trading_enabled = {symbol: True for symbol in SYMBOLS}
consecutive_losses = {symbol: 0 for symbol in SYMBOLS}

# === 텔레그램 알림 ===
def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message})
    except Exception as e:
        print("❌ 텔레그램 전송 실패:", e)

# === 시그니처 생성 ===
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

# === 잔액 조회 ===
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
                send_telegram(f"\uD83D\uDCCA 현재 선물 계정 잔액: {balance:.2f} USDT")
            return balance
    except Exception as e:
        print("잔액 조회 실패:", e)
        return None

# === 지표 계산 ===
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
def strategy(symbol):
    if len(candles[symbol]) < 30:
        return
    prices = np.array(candles[symbol], dtype=float)
    cci = calculate_cci(prices)[-1]
    adx = calculate_adx(prices)[-1]
    price = float(prices[-1][4])

    pos = positions.get(symbol)
    if pos is None:
        if cci > 100 and adx > 25:
            entry_prices[symbol] = price
            positions[symbol] = "long"
            trailing_active[symbol] = False
            send_telegram(f"\uD83D\uDFE2 {symbol} 롱 진입 @ {price}")
        elif cci < -100 and adx > 25:
            entry_prices[symbol] = price
            positions[symbol] = "short"
            trailing_active[symbol] = False
            send_telegram(f"\uD83D\uDD34 {symbol} 숏 진입 @ {price}")
    else:
        entry = entry_prices[symbol]
        side = positions[symbol]
        change = ((price - entry) / entry) * (1 if side == "long" else -1)

        if not trailing_active[symbol] and change >= 0.03:
            trailing_active[symbol] = True
            trailing_active[symbol] = price
        elif trailing_active[symbol]:
            peak = trailing_active[symbol]
            if side == "long":
                trailing_active[symbol] = max(peak, price)
                if price < trailing_active[symbol] * 0.995:
                    send_telegram(f"\uD83D\uDD3B {symbol} 롱 청산 @ {price}")
                    positions[symbol] = None
            else:
                trailing_active[symbol] = min(peak, price)
                if price > trailing_active[symbol] * 1.005:
                    send_telegram(f"\uD83D\uDD39 {symbol} 숏 청산 @ {price}")
                    positions[symbol] = None

        if change <= -0.02:
            send_telegram(f"\u274C {symbol} 손절 청산 @ {price}")
            positions[symbol] = None

# === 메시지 처리 ===
def on_msg(msg):
    try:
        dlist = msg.get("data")
        for d in dlist:
            symbol = d["instId"]
            ts = int(d["ts"])
            k = [ts, float(d["o"]), float(d["h"]), float(d["l"]), float(d["c"]), float(d["v"])]
            if ts % (15 * 60 * 1000) == 0:
                candles[symbol].append(k)
                if len(candles[symbol]) > MAX_CANDLES:
                    candles[symbol].pop(0)
                strategy(symbol)
    except Exception as e:
        print(f"⚠️ 메시지 처리 오류: {e}")

# === WebSocket ===
async def ws_loop():
    uri = "wss://ws.bitget.com/v2/ws/public"
    while True:
        try:
            async with websockets.connect(uri, ping_interval=20, ping_timeout=30) as ws:
                args = [{"instType": INST_TYPE, "channel": CHANNEL, "instId": s} for s in SYMBOLS]
                await ws.send(json.dumps({"op": "subscribe", "args": args}))
                print("✅ WS 연결됨 / 15분봉 구독 중")
                get_account_balance(send=True)
                while True:
                    try:
                        msg = json.loads(await ws.recv())
                        if isinstance(msg, dict):
                            if msg.get("event") == "error":
                                print(f"❌ 에러 응답: {msg}")
                            elif msg.get("action") in ["snapshot", "update"]:
                                on_msg(msg)
                    except Exception as e:
                        print(f"⚠️ 메시지 처리 오류: {e}")
        except Exception as e:
            print(f"⚠️ WebSocket 오류: {e}")
            await asyncio.sleep(5)

# === 주기적 잔액 알림 ===
def balance_notifier():
    while True:
        time.sleep(3600)
        get_account_balance(send=True)

# === 메인 ===
if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=8080)).start()
    asyncio.run(ws_loop())

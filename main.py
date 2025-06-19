import asyncio, json, websockets, requests, hmac, hashlib, time
from datetime import datetime, timedelta
import numpy as np

# 환경 설정
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
positions = {symbol: None for symbol in SYMBOLS}
auto_trading_enabled = {symbol: True for symbol in SYMBOLS}
consecutive_losses = {symbol: 0 for symbol in SYMBOLS}
last_balance_check = datetime.utcnow()

# 텔레그램
def send_telegram(message):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": message}
        )
    except Exception as e:
        print("❌ 텔레그램 전송 실패:", e)

# 인증 헤더
def sign(message, secret):
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()

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

# 잔액 조회
def get_balance(send=False):
    url = "https://api.bitget.com/api/mix/v1/account/account?marginCoin=USDT"
    headers = get_headers("GET", "/api/mix/v1/account/account?marginCoin=USDT")
    try:
        res = requests.get(url, headers=headers)
        data = res.json()
        if data["code"] == "00000":
            balance = float(data["data"]["available"])
            if send:
                send_telegram(f"💰 현재 잔액: {balance:.2f} USDT")
            return balance
    except Exception as e:
        print("잔액 조회 실패:", e)
        return None

# 실 주문 실행
def place_order(symbol, side, amount, leverage):
    url = "https://api.bitget.com/api/mix/v1/order/placeOrder"
    path = "/api/mix/v1/order/placeOrder"
    order_type = "open_long" if side == "long" else "open_short"
    body = {
        "symbol": symbol,
        "marginCoin": "USDT",
        "size": str(round(amount * leverage / get_price(symbol), 3)),
        "side": "buy" if side == "long" else "sell",
        "tradeSide": order_type,
        "orderType": "market",
        "leverage": str(leverage)
    }
    headers = get_headers("POST", path, json.dumps(body))
    try:
        res = requests.post(url, headers=headers, data=json.dumps(body))
        data = res.json()
        if data["code"] == "00000":
            send_telegram(f"✅ {symbol} {side.upper()} 진입 완료")
            return True
    except Exception as e:
        print("주문 실패:", e)
    return False

def get_price(symbol):
    url = f"https://api.bitget.com/api/mix/v1/market/ticker?symbol={symbol}&productType=USDT-FUTURES"
    try:
        res = requests.get(url)
        data = res.json()
        if data["code"] == "00000":
            return float(data["data"]["last"])
    except:
        return None

# 지표 계산
def calculate_cci(data, period=14):
    if len(data) < period:
        return None
    tp = [(float(d[2]) + float(d[3]) + float(d[4])) / 3 for d in data[-period:]]
    ma = np.mean(tp)
    md = np.mean(np.abs(tp - ma))
    return (tp[-1] - ma) / (0.015 * md) if md != 0 else 0

def calculate_adx(data, period=5):
    if len(data) < period + 1:
        return None
    highs = np.array([float(d[2]) for d in data])
    lows = np.array([float(d[3]) for d in data])
    closes = np.array([float(d[4]) for d in data])
    plus_dm = highs[1:] - highs[:-1]
    minus_dm = lows[:-1] - lows[1:]
    plus_dm = np.where(plus_dm > minus_dm, plus_dm, 0)
    minus_dm = np.where(minus_dm > plus_dm, minus_dm, 0)
    tr = np.maximum(highs[1:], closes[:-1]) - np.minimum(lows[1:], closes[:-1])
    tr = np.where(tr == 0, 1e-6, tr)
    plus_di = 100 * np.mean(plus_dm[-period:]) / np.mean(tr[-period:])
    minus_di = 100 * np.mean(minus_dm[-period:]) / np.mean(tr[-period:])
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    return dx

# 전략 실행
def strategy(symbol):
    data = candles[symbol]
    if len(data) < 20:
        return
    cci = calculate_cci(data, 14)
    adx = calculate_adx(data, 5)
    price = float(data[-1][4])
    position = positions[symbol]

    if position is None:
        if cci is not None and adx is not None and adx > 25:
            if cci > 100:
                if place_order(symbol, "long", SYMBOLS[symbol]["amount"], SYMBOLS[symbol]["leverage"]):
                    positions[symbol] = {"side": "long", "entry": price, "trail": False, "peak": price}
            elif cci < -100:
                if place_order(symbol, "short", SYMBOLS[symbol]["amount"], SYMBOLS[symbol]["leverage"]):
                    positions[symbol] = {"side": "short", "entry": price, "trail": False, "peak": price}
    else:
        entry = position["entry"]
        side = position["side"]
        ratio = (price - entry) / entry if side == "long" else (entry - price) / entry

        if not position["trail"] and ratio >= 0.03:
            position["trail"] = True
            position["peak"] = price
        elif position["trail"]:
            if side == "long":
                position["peak"] = max(position["peak"], price)
                if price < position["peak"] * 0.995:
                    send_telegram(f"🔻 {symbol} LONG 트레일링 스탑 청산")
                    positions[symbol] = None
            else:
                position["peak"] = min(position["peak"], price)
                if price > position["peak"] * 1.005:
                    send_telegram(f"🔻 {symbol} SHORT 트레일링 스탑 청산")
                    positions[symbol] = None

        if ratio <= -0.02:
            send_telegram(f"🛑 {symbol} {side.upper()} 손절 (-2%)")
            positions[symbol] = None

# 메시지 핸들링
def on_msg(msg):
    try:
        for d in msg["data"]:
            symbol = d["instId"]
            ts = int(d["ts"])
            k = [ts, float(d["o"]), float(d["h"]), float(d["l"]), float(d["c"]), float(d["v"])]
            if candles[symbol] and candles[symbol][-1][0] == ts:
                candles[symbol][-1] = k
            else:
                candles[symbol].append(k)
                if len(candles[symbol]) > MAX_CANDLES:
                    candles[symbol].pop(0)
                strategy(symbol)
    except Exception as e:
        print("⚠️ 메시지 처리 오류:", e)

# WebSocket 실행
async def ws_loop():
    global last_balance_check
    uri = "wss://ws.bitget.com/v2/ws/public"
    async with websockets.connect(uri, ping_interval=20) as ws:
        args = [{"instType": INST_TYPE, "channel": "candle15m", "instId": s} for s in SYMBOLS]
        await ws.send(json.dumps({"op": "subscribe", "args": args}))
        print("✅ WS 연결됨 / 15분봉 구독 중")
        get_balance(send=True)
        while True:
            try:
                msg = json.loads(await ws.recv())
                if "data" in msg:
                    on_msg(msg)
                # 1시간마다 잔액 체크
                if datetime.utcnow() - last_balance_check > timedelta(hours=1):
                    get_balance(send=True)
                    last_balance_check = datetime.utcnow()
            except Exception as e:
                print("⚠️ WebSocket 오류:", e)
                await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(ws_loop())


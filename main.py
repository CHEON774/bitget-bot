import asyncio, json, websockets, requests, hmac, hashlib, time, base64
from datetime import datetime, timedelta, timezone
import numpy as np

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
positions = {}
entry_prices = {}
trailing_active = {}
auto_trading_enabled = {symbol: True for symbol in SYMBOLS}
consecutive_losses = {symbol: 0 for symbol in SYMBOLS}
last_balance_check = datetime.now(timezone.utc)

# === 텔레그램 ===
def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message})
    except Exception as e:
        print("❌ 텔레그램 전송 실패:", e)

# === 서명 및 헤더 ===
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
                send_telegram(f"📊 현재 선물 계정 잔액: {balance:.2f} USDT")
            return balance
    except:
        return None

# === 지표 계산 ===
def calculate_cci(prices, period=14):
    tp = (prices[:, 1] + prices[:, 2] + prices[:, 3]) / 3
    ma = np.convolve(tp, np.ones(period)/period, mode='valid')
    md = np.array([np.mean(np.abs(tp[i - period + 1:i + 1] - ma[i - period + 1])) for i in range(period - 1, len(tp))])
    cci = (tp[period - 1:] - ma) / (0.015 * md)
    return cci

def calculate_adx(prices, period=5):
    high, low, close = prices[:, 2], prices[:, 3], prices[:, 4]
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
def place_market_order(symbol, side, amount, leverage):
    send_telegram(f"🔴 {symbol} {side.upper()} 진입")
    entry_price = candles[symbol][-1][4]
    positions[symbol] = {
        "side": side,
        "entry": entry_price,
        "trail_mode": False,
        "trail_max": entry_price
    }

def close_position(symbol, price, reason):
    if symbol in positions and positions[symbol]:
        entry = positions[symbol]["entry"]
        side = positions[symbol]["side"]
        pnl = ((price - entry) / entry) * (1 if side == "long" else -1) * 100
        send_telegram(f"🔺 {symbol} {side.upper()} 청산 @ {price:.2f} ({pnl:.2f}%) | {reason}")
        positions[symbol] = None

def strategy(symbol):
    if len(candles[symbol]) < 30:
        return
    prices = np.array(candles[symbol], dtype=float)
    cci = calculate_cci(prices)[-1]
    adx = calculate_adx(prices)[-1]
    price = prices[-1][4]

    pos = positions.get(symbol)
    if pos is None:
        if cci > 100 and adx > 25:
            place_market_order(symbol, "long", SYMBOLS[symbol]["amount"], SYMBOLS[symbol]["leverage"])
        elif cci < -100 and adx > 25:
            place_market_order(symbol, "short", SYMBOLS[symbol]["amount"], SYMBOLS[symbol]["leverage"])
    else:
        entry = pos["entry"]
        side = pos["side"]
        ratio = ((price - entry) / entry) * (1 if side == "long" else -1)

        if not pos["trail_mode"]:
            if ratio >= 0.03:
                pos["trail_mode"] = True
                pos["trail_max"] = price
        else:
            if side == "long":
                pos["trail_max"] = max(pos["trail_max"], price)
                if price < pos["trail_max"] * 0.995:
                    close_position(symbol, price, "트레일링 스탑")
            else:
                pos["trail_max"] = min(pos["trail_max"], price)
                if price > pos["trail_max"] * 1.005:
                    close_position(symbol, price, "트레일링 스탑")

        if ratio <= -0.02:
            close_position(symbol, price, "손절")

# === WebSocket 처리 ===
def handle_message(msg):
    global last_balance_check
    try:
        for d in msg["data"]:
            symbol = d["instId"]
            ts = int(d["ts"])
            candle = [ts, float(d["o"]), float(d["h"]), float(d["l"]), float(d["c"]), float(d["v"])]
            if not candles[symbol] or candles[symbol][-1][0] != ts:
                candles[symbol].append(candle)
                if len(candles[symbol]) > MAX_CANDLES:
                    candles[symbol].pop(0)
                strategy(symbol)

        # 잔액 1시간마다 알림
        if datetime.now(timezone.utc) - last_balance_check > timedelta(hours=1):
            get_account_balance(send=True)
            last_balance_check = datetime.now(timezone.utc)

    except Exception as e:
        print(f"⚠️ 메시지 처리 오류: {e}")

# === WebSocket 루프 ===
async def ws_loop():
    uri = "wss://ws.bitget.com/v2/ws/public"
    while True:
        try:
            async with websockets.connect(uri, ping_interval=20) as ws:
                args = [{"instType": INST_TYPE, "channel": "candle15m", "instId": s} for s in SYMBOLS]
                await ws.send(json.dumps({"op": "subscribe", "args": args}))
                print("✅ WS 연결됨 / 15분봉 구독 중")
                while True:
                    msg = json.loads(await ws.recv())
                    if isinstance(msg, dict) and msg.get("action") in ["snapshot", "update"]:
                        handle_message(msg)
        except Exception as e:
            print(f"⚠️ WebSocket 오류: {e}\n🔁 재연결 중...")
            await asyncio.sleep(5)

# === 메인 ===
if __name__ == "__main__":
    asyncio.run(ws_loop())


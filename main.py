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
MAX_CANDLES = 150
candles = {s: [] for s in SYMBOLS}
positions = {}
auto_trading_enabled = {s: True for s in SYMBOLS}
trailing_data = {}

last_balance_check = datetime.utcnow()

# === 함수 ===
def sign(msg, secret):
    return base64.b64encode(hmac.new(secret.encode(), msg.encode(), hashlib.sha256).digest()).decode()

def get_timestamp():
    return str(int(time.time() * 1000))

def get_headers(method, path, body=''):
    ts = get_timestamp()
    msg = ts + method + path + body
    return {
        'ACCESS-KEY': API_KEY,
        'ACCESS-SIGN': sign(msg, API_SECRET),
        'ACCESS-TIMESTAMP': ts,
        'ACCESS-PASSPHRASE': API_PASSPHRASE,
        'locale': 'en-US'
    }

def send_telegram(text):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      data={"chat_id": TELEGRAM_CHAT_ID, "text": text})
    except Exception as e:
        print("텔레그램 오류:", e)

def get_balance():
    path = "/api/v2/account/all-account-balance"
    try:
        res = requests.get("https://api.bitget.com" + path, headers=get_headers("GET", path))
        data = res.json()
        if data['code'] == '00000':
            bal = next((float(a['usdtBalance']) for a in data['data'] if a['accountType'] == 'futures'), 0)
            return bal
    except:
        return None

def calculate_cci(prices, period=14):
    tp = (prices[:,2] + prices[:,3] + prices[:,4]) / 3
    ma = np.mean(tp[-period:])
    md = np.mean(np.abs(tp[-period:] - ma))
    return 0 if md == 0 else (tp[-1] - ma) / (0.015 * md)

def calculate_adx(prices, period=5):
    high, low, close = prices[:,2], prices[:,3], prices[:,4]
    plus_dm = np.where((high[1:] - high[:-1]) > (low[:-1] - low[1:]), high[1:] - high[:-1], 0)
    minus_dm = np.where((low[:-1] - low[1:]) > (high[1:] - high[:-1]), low[:-1] - low[1:], 0)
    tr = np.maximum(high[1:], close[:-1]) - np.minimum(low[1:], close[:-1])
    atr = np.mean(tr[-period:])
    plus_di = 100 * np.mean(plus_dm[-period:]) / atr if atr != 0 else 0
    minus_di = 100 * np.mean(minus_dm[-period:]) / atr if atr != 0 else 0
    return abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) != 0 else 0

def place_order(symbol, side):
    price = candles[symbol][-1][4]
    positions[symbol] = {"side": side, "entry": price}
    trailing_data[symbol] = {"active": False, "peak": price}
    send_telegram(f"{'🟢' if side == 'long' else '🔴'} {symbol} {side.upper()} 진입 @ {price}")

def close_position(symbol, reason):
    price = candles[symbol][-1][4]
    entry = positions[symbol]['entry']
    side = positions[symbol]['side']
    pnl = (price - entry) / entry * (1 if side == 'long' else -1)
    send_telegram(f"🔺 {symbol} {side.upper()} 청산 @ {price} ({pnl*100:.2f}%) | {reason}")
    del positions[symbol]
    del trailing_data[symbol]

def evaluate_strategy(symbol):
    if len(candles[symbol]) < 20: return
    prices = np.array(candles[symbol], dtype=float)
    cci = calculate_cci(prices)
    adx = calculate_adx(prices)
    current = prices[-1][4]

    if symbol not in positions:
        if cci > 100 and adx > 25:
            place_order(symbol, 'long')
        elif cci < -100 and adx > 25:
            place_order(symbol, 'short')
    else:
        pos = positions[symbol]
        trail = trailing_data[symbol]
        entry = pos['entry']
        side = pos['side']
        pnl = (current - entry) / entry * (1 if side == 'long' else -1)

        if not trail['active'] and pnl >= 0.03:
            trail['active'] = True
            trail['peak'] = current
        elif trail['active']:
            if side == 'long':
                trail['peak'] = max(trail['peak'], current)
                if current <= trail['peak'] * 0.995:
                    close_position(symbol, '트레일링 스탑')
            else:
                trail['peak'] = min(trail['peak'], current)
                if current >= trail['peak'] * 1.005:
                    close_position(symbol, '트레일링 스탑')

        if pnl <= -0.02:
            close_position(symbol, '손절')

# === 메시지 핸들러 ===
def handle_message(msg):
    try:
        for d in msg['data']:
            symbol = d['instId']
            if symbol not in SYMBOLS: continue
            k = [int(d['ts']), float(d['o']), float(d['h']), float(d['l']), float(d['c']), float(d['v'])]
            if candles[symbol] and candles[symbol][-1][0] == k[0]:
                candles[symbol][-1] = k
            else:
                candles[symbol].append(k)
                if len(candles[symbol]) > MAX_CANDLES:
                    candles[symbol].pop(0)
                evaluate_strategy(symbol)
    except Exception as e:
        print(f"⚠️ 메시지 처리 오류: {e}")

# === WS 루프 ===
async def ws_loop():
    global last_balance_check
    uri = "wss://ws.bitget.com/v2/ws/public"
    async with websockets.connect(uri, ping_interval=20, ping_timeout=30) as ws:
        await ws.send(json.dumps({"op": "subscribe", "args": [
            {"instType": INST_TYPE, "channel": "candle15m", "instId": s} for s in SYMBOLS
        ]}))
        print("✅ WS 연결됨 / 15분봉 구독 중")
        send_telegram("✅ 자동매매 봇 시작됨")
        send_telegram(f"💰 시작 잔액: {get_balance()} USDT")

        while True:
            try:
                msg = json.loads(await ws.recv())
                if 'data' in msg:
                    handle_message(msg)

                if datetime.utcnow() - last_balance_check > timedelta(hours=1):
                    bal = get_balance()
                    if bal:
                        send_telegram(f"⏰ 잔액 리마인더: {bal:.2f} USDT")
                    last_balance_check = datetime.utcnow()
            except Exception as e:
                print(f"⚠️ WebSocket 오류: {e}")
                await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(ws_loop())

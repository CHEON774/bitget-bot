import asyncio, json, websockets, requests, hmac, hashlib, time, base64
from datetime import datetime
import numpy as np
from websockets.exceptions import ConnectionClosedError

# === 기본 설정 ===
API_KEY = 'bg_a9c07aa3168e846bfaa713fe9af79d14'
API_SECRET = '5be628fd41dce5eff78a607f31d096a4911d4e2156b6d66a14be20f027068043'
API_PASSPHRASE = '1q2w3e4r'
TELEGRAM_TOKEN = '7776435078:AAFsM_jIDSx1Eij4YJyqJp-zEDtQVtKohnU'
TELEGRAM_CHAT_ID = '1797494660'

SYMBOLS = {
    "BTCUSDT": {"leverage": 10, "amount": 150},
    "ETHUSDT": {"leverage": 7, "amount": 120},
}
INST_TYPE = "USDT-FUTURES"
CHANNEL = "candle15m"
MAX_CANDLES = 150

candles = {symbol: [] for symbol in SYMBOLS}
positions = {}
trailing_active = {}
auto_trading_enabled = {symbol: True for symbol in SYMBOLS}
consecutive_losses = {symbol: 0 for symbol in SYMBOLS}

# === 유틸 함수 ===
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

def calculate_cci(candles, period=14):
    if len(candles) < period:
        return None
    tp = np.array([(float(c[2]) + float(c[3]) + float(c[4])) / 3 for c in candles[-period:]])
    ma = np.mean(tp)
    md = np.mean(np.abs(tp - ma))
    return 0 if md == 0 else (tp[-1] - ma) / (0.015 * md)

def calculate_adx(candles, period=5):
    if len(candles) < period + 1:
        return None
    high = np.array([float(c[2]) for c in candles])
    low = np.array([float(c[3]) for c in candles])
    close = np.array([float(c[4]) for c in candles])
    tr = np.maximum(high[1:], close[:-1]) - np.minimum(low[1:], close[:-1])
    plus_dm = np.where((high[1:] - high[:-1]) > (low[:-1] - low[1:]),
                       np.maximum(high[1:] - high[:-1], 0), 0)
    minus_dm = np.where((low[:-1] - low[1:]) > (high[1:] - high[:-1]),
                        np.maximum(low[:-1] - low[1:], 0), 0)
    atr = np.mean(tr[-period:])
    plus_di = 100 * (np.mean(plus_dm[-period:]) / atr) if atr != 0 else 0
    minus_di = 100 * (np.mean(minus_dm[-period:]) / atr) if atr != 0 else 0
    return abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) != 0 else 0

def place_order(symbol, side, price):
    positions[symbol] = {
        'side': side,
        'entry': price,
        'trail_mode': False,
        'trail_max': price
    }
    send_telegram(f"{'🟢' if side=='long' else '🔴'} {symbol} {side.upper()} 진입 @ {price:.2f}")

def close_position(symbol, price, reason):
    if symbol not in positions or not positions[symbol]:
        return
    entry = positions[symbol]['entry']
    side = positions[symbol]['side']
    pnl = ((price - entry) / entry) * (1 if side == "long" else -1) * 100
    send_telegram(f"🔺 {symbol} {side.upper()} 청산 @ {price:.2f} ({pnl:.2f}%) | {reason}")
    if pnl < 0:
        consecutive_losses[symbol] += 1
        if consecutive_losses[symbol] >= 3:
            auto_trading_enabled[symbol] = False
            send_telegram(f"⛔ {symbol} 연속 손절로 자동매매 중단됨")
    else:
        consecutive_losses[symbol] = 0
    positions[symbol] = None

def evaluate_strategy(symbol):
    if not auto_trading_enabled[symbol]:
        return
    if len(candles[symbol]) < 20:
        return
    cci = calculate_cci(candles[symbol])
    adx = calculate_adx(candles[symbol])
    price = float(candles[symbol][-1][4])
    if cci is None or adx is None:
        return
    pos = positions.get(symbol)
    if not pos:
        if cci > 100 and adx > 25:
            place_order(symbol, "long", price)
        elif cci < -100 and adx > 25:
            place_order(symbol, "short", price)
    else:
        entry = pos['entry']
        side = pos['side']
        ratio = ((price - entry) / entry) * (1 if side == 'long' else -1)
        if not pos['trail_mode'] and ratio >= 0.03:
            pos['trail_mode'] = True
            pos['trail_max'] = price
        elif pos['trail_mode']:
            if side == "long":
                pos['trail_max'] = max(pos['trail_max'], price)
                if price < pos['trail_max'] * 0.995:
                    close_position(symbol, price, "트레일링 스탑")
            else:
                pos['trail_max'] = min(pos['trail_max'], price)
                if price > pos['trail_max'] * 1.005:
                    close_position(symbol, price, "트레일링 스탑")
        if ratio <= -0.02:
            close_position(symbol, price, "손절")

def on_msg(msg):
    for d in msg['data']:
        symbol = d['instId']
        ts = int(d['ts'])
        candle = [ts, float(d['o']), float(d['h']), float(d['l']), float(d['c']), float(d['v'])]
        if not candles[symbol] or candles[symbol][-1][0] != ts:
            candles[symbol].append(candle)
            if len(candles[symbol]) > MAX_CANDLES:
                candles[symbol].pop(0)
            evaluate_strategy(symbol)
        else:
            candles[symbol][-1] = candle

async def ws_loop():
    uri = "wss://ws.bitget.com/v2/ws/public"
    while True:
        try:
            async with websockets.connect(uri, ping_interval=20, ping_timeout=30) as ws:
                args = [{"instType": INST_TYPE, "channel": CHANNEL, "instId": symbol} for symbol in SYMBOLS]
                await ws.send(json.dumps({"op": "subscribe", "args": args}))
                print("✅ WS 연결됨 / 15분봉 구독 중")
                while True:
                    msg = json.loads(await ws.recv())
                    if msg.get("action") in ["snapshot", "update"]:
                        on_msg(msg)
        except Exception as e:
            print(f"⚠️ WebSocket 오류: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(ws_loop())


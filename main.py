import asyncio, json, websockets, requests, hmac, hashlib, time
from datetime import datetime
import numpy as np

# Bitget API 인증 정보
API_KEY = 'bg_534f4dcd8acb22273de01247d163845e'
API_SECRET = 'df5f0c3a596070ab8f940a8faeb2ebac2fdba90b8e1e096a05bb2e01ad13cf9d'
API_PASSPHRASE = '1q2w3e4r'

# 기본 설정
SYMBOLS = {
    "BTCUSDT": {"leverage": 10, "amount": 150},
    "ETHUSDT": {"leverage": 7, "amount": 120}
}
CHANNEL = "candle15m"
INST_TYPE = "UMCBL"
MAX_CANDLES = 150
candles = {symbol: [] for symbol in SYMBOLS.keys()}
positions = {}
entry_prices = {}
trailing_active = {}

# 텔레그램 설정
TELEGRAM_TOKEN = '7787612607:AAEHWXld8OqmK3OeGmo2nJdmx-Bg03h85UQ'
TELEGRAM_CHAT_ID = '1797494660'

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message})
    except Exception as e:
        print("❌ 텔레그램 전송 실패:", e, flush=True)

def get_bitget_headers(method, path, body=''):
    timestamp = str(int(time.time() * 1000))
    message = f'{timestamp}{method}{path}{body}'
    signature = hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
    return {
        'ACCESS-KEY': API_KEY,
        'ACCESS-SIGN': signature,
        'ACCESS-TIMESTAMP': timestamp,
        'ACCESS-PASSPHRASE': API_PASSPHRASE,
        'Content-Type': 'application/json'
    }

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
        "productType": "UMCBL"
    }
    headers = get_bitget_headers('POST', path, json.dumps(data))
    res = requests.post(url, headers=headers, json=data)
    if res.status_code == 200:
        print(f"✅ 실전 주문 완료: {symbol} {side} {amount}", flush=True)
    else:
        print(f"❌ 주문 실패: {res.text}", flush=True)


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
    plus_di = 100 * (np.mean(plus_dm[-period:]) / atr) if atr != 0 else 0
    minus_di = 100 * (np.mean(minus_dm[-period:]) / atr) if atr != 0 else 0
    return abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) != 0 else 0

def handle_candle(symbol, data):
    global positions, entry_prices, trailing_active

    ts, o, h, l, c, v = int(data[0]), *data[1:6]
    candle = [ts, o, h, l, c, v]
    store = candles[symbol]

    if store and store[-1][0] == ts:
        store[-1] = candle
    else:
        store.append(candle)
        if len(store) > MAX_CANDLES:
            store.pop(0)
        print(f"🕒 {symbol} | {datetime.fromtimestamp(ts/1000):%Y-%m-%d %H:%M:%S} | O:{o} H:{h} L:{l} C:{c} V:{v}", flush=True)

        if len(store) < 20:
            return

        prev_ts = store[-2][0]
        if entry_prices.get(symbol) and trailing_active.get(symbol):
            entry = entry_prices[symbol]
            pnl = (float(c) - entry) / entry * 100 if positions[symbol] == 'long' else (entry - float(c)) / entry * 100
            if pnl >= 2:
                trailing_active[symbol] = float(c)
            elif trailing_active[symbol] and ((positions[symbol] == 'long' and float(c) < trailing_active[symbol] - trailing_active[symbol]*0.003) or
                                               (positions[symbol] == 'short' and float(c) > trailing_active[symbol] + trailing_active[symbol]*0.003)):
                print(f"💰 {symbol} 청산! 수익률: {pnl:.2f}%", flush=True)
                send_telegram(f"💰 {symbol} 청산! 수익률: {pnl:.2f}%")
                positions[symbol] = None
                entry_prices[symbol] = None
                trailing_active[symbol] = None
                place_order(symbol, 'close_long' if positions[symbol] == 'long' else 'close_short', SYMBOLS[symbol]['amount'])

        # 진입 판단
        cci = calculate_cci(store[:-1], 14)
        adx = calculate_adx(store[:-1], 5)
        if cci is None or adx is None:
            return

        if adx > 25:
            if cci > 100 and positions.get(symbol) != 'long':
                positions[symbol] = 'long'
                entry_prices[symbol] = float(c)
                trailing_active[symbol] = None
                send_telegram(f"🚀 {symbol} 롱 진입 @ {c}")
                place_order(symbol, 'open_long', SYMBOLS[symbol]['amount'])
            elif cci < -100 and positions.get(symbol) != 'short':
                positions[symbol] = 'short'
                entry_prices[symbol] = float(c)
                trailing_active[symbol] = None
                send_telegram(f"🔻 {symbol} 숏 진입 @ {c}")
                place_order(symbol, 'open_short', SYMBOLS[symbol]['amount'])

async def ws_loop():
    uri = "wss://ws.bitget.com/v2/ws/public"
    while True:
        try:
            async with websockets.connect(uri, ping_interval=30, ping_timeout=10) as ws:
                args = [{"instType": INST_TYPE, "channel": CHANNEL, "instId": symbol} for symbol in SYMBOLS.keys()]
                await ws.send(json.dumps({"op": "subscribe", "args": args}))
                print("✅ WebSocket 연결 및 구독 완료", flush=True)

                while True:
                    msg = json.loads(await ws.recv())
                    if msg.get("action") in ["snapshot", "update"] and "arg" in msg:
                        symbol = msg["arg"]["instId"]
                        if symbol in SYMBOLS:
                            handle_candle(symbol, msg["data"][0])
        except Exception as e:
            print(f"⚠️ 메시지 처리 오류: {e}", flush=True)
        print("🔁 5초 후 재연결 시도...", flush=True)
        await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(ws_loop())

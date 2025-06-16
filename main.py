import asyncio, json, hmac, hashlib, time, requests, websockets
from datetime import datetime
import numpy as np

# === 사용자 설정 ===
API_KEY = 'bg_534f4dcd8acb22273de01247d163845e'
API_SECRET = 'df5f0c3a596070ab8f940a8faeb2ebac2fdba90b8e1e096a05bb2e01ad13cf9d'
API_PASSPHRASE = '1q2w3e4r'
BASE_URL = "https://api.bitget.com"
BOT_TOKEN = "7787612607:AAEHWXld8OqmK3OeGmo2nJdmx-Bg03h85UQ"
CHAT_ID = "1797494660"

SYMBOLS = ["BTCUSDT", "ETHUSDT"]
INST_TYPE = "USDT-FUTURES"
CANDLE_CHANNEL = "candle15m"
TICKER_CHANNEL = "ticker"
MAX_CANDLES = 150

# === 상태 ===
candles = {s: [] for s in SYMBOLS}
last_ts = {s: None for s in SYMBOLS}
position = {s: None for s in SYMBOLS}  # {'entry': float, 'trail_active': bool, 'trail_stop': float, 'max_price': float}

# === 텔레그램 전송 ===
def send_telegram(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except Exception as e:
        print(f"⚠️ 텔레그램 전송 실패: {e}")

# === WebSocket 서명 ===
def get_ws_signature(timestamp):
    message = f'{timestamp}GET/user/verify'
    sign = hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
    return sign

# === 주문 전송 ===
def place_order(symbol, side):
    timestamp = str(int(time.time() * 1000))
    path = "/api/mix/v1/order/place"
    url = BASE_URL + path
    body = {
        "symbol": symbol,
        "marginCoin": "USDT",
        "side": side,
        "orderType": "market",
        "size": "0.01",
        "productType": "umcbl"
    }
    message = timestamp + "POST" + path + json.dumps(body)
    sign = hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
    headers = {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": API_PASSPHRASE,
        "Content-Type": "application/json"
    }
    res = requests.post(url, headers=headers, json=body)
    print(f"\n📤 주문 전송 ({side}) {symbol} → {res.status_code}: {res.text}")
    send_telegram(f"📤 주문 전송 ({side}) {symbol}\n응답: {res.status_code} - {res.text}")

# === 지표 계산 ===
def calculate_cci(c, period=14):
    if len(c) < period: return None
    tp = np.array([(float(x[2])+float(x[3])+float(x[4]))/3 for x in c[-period:]])
    ma = np.mean(tp)
    md = np.mean(np.abs(tp - ma))
    return 0 if md == 0 else (tp[-1]-ma)/(0.015*md)

def calculate_adx(c, period=5):
    if len(c) < period + 1: return None
    high = np.array([float(x[2]) for x in c])
    low = np.array([float(x[3]) for x in c])
    close = np.array([float(x[4]) for x in c])
    tr = np.maximum(high[1:], close[:-1]) - np.minimum(low[1:], close[:-1])
    plus_dm = np.where((high[1:]-high[:-1]) > (low[:-1]-low[1:]), np.maximum(high[1:]-high[:-1], 0), 0)
    minus_dm = np.where((low[:-1]-low[1:]) > (high[1:]-high[:-1]), np.maximum(low[:-1]-low[1:], 0), 0)
    atr = np.mean(tr[-period:])
    plus_di = 100 * (np.mean(plus_dm[-period:]) / atr) if atr != 0 else 0
    minus_di = 100 * (np.mean(minus_dm[-period:]) / atr) if atr != 0 else 0
    return abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) != 0 else 0

# === 메시지 처리 ===
def handle_candle(symbol, d):
    ts = int(d[0])
    candle = [ts, d[1], d[2], d[3], d[4], d[5]]
    c = candles[symbol]

    if c and c[-1][0] == ts:
        c[-1] = candle
    else:
        c.append(candle)
        if len(c) > MAX_CANDLES:
            c.pop(0)

        if len(c) >= 20:
            prev = c[-2]
            if last_ts[symbol] == prev[0]: return
            last_ts[symbol] = prev[0]
            cci = calculate_cci(c[:-1])
            adx = calculate_adx(c[:-1])
            print(f"\n✅ {symbol} | CCI: {cci:.2f}, ADX: {adx:.2f}")
            send_telegram(f"✅ {symbol} | CCI(14): {cci:.2f}, ADX(5): {adx:.2f}")
            if cci and adx and cci > 100 and adx > 25 and position[symbol] is None:
                entry = float(prev[4])
                position[symbol] = {'entry': entry, 'trail_active': False, 'trail_stop': None, 'max_price': entry}
                place_order(symbol, 'open_long')
                print(f"🚀 진입: {symbol} @ {entry}")
                send_telegram(f"🚀 {symbol} 진입 @ {entry:.2f}")

# === 실시간 가격 추적 ===
def handle_ticker(symbol, d):
    current = float(d['last'])
    pos = position.get(symbol)
    if not pos: return
    entry = pos['entry']
    if not pos['trail_active']:
        if current >= entry * 1.02:
            pos['trail_active'] = True
            pos['max_price'] = current
            pos['trail_stop'] = current * 0.997
            print(f"🎯 트레일링 시작: {symbol} @ {current:.2f} (스탑가 {pos['trail_stop']:.2f})")
            send_telegram(f"🎯 {symbol} 트레일링 시작 @ {current:.2f}\n스탑가: {pos['trail_stop']:.2f}")
    else:
        pos['max_price'] = max(pos['max_price'], current)
        pos['trail_stop'] = pos['max_price'] * 0.997
        if current <= pos['trail_stop']:
            place_order(symbol, 'close_long')
            print(f"💥 청산: {symbol} @ {current:.2f}")
            send_telegram(f"💥 {symbol} 청산 @ {current:.2f}")
            position[symbol] = None

# === WebSocket 연결 ===
async def ws_loop():
    uri = "wss://ws.bitget.com/v2/ws/public"
    async with websockets.connect(uri) as ws:
        args = []
        for s in SYMBOLS:
            args.append({"instType": INST_TYPE, "channel": CANDLE_CHANNEL, "instId": s})
            args.append({"instType": INST_TYPE, "channel": TICKER_CHANNEL, "instId": s})
        await ws.send(json.dumps({"op": "subscribe", "args": args}))
        print("✅ WebSocket 연결 및 구독 완료")

        while True:
            msg = json.loads(await ws.recv())
            if 'data' not in msg: continue
            symbol = msg['arg']['instId']
            if msg['arg']['channel'] == CANDLE_CHANNEL:
                handle_candle(symbol, msg['data'][0])
            elif msg['arg']['channel'] == TICKER_CHANNEL:
                handle_ticker(symbol, msg['data'])

if __name__ == "__main__":
    asyncio.run(ws_loop())

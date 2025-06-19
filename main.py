import asyncio, json, websockets, requests, hmac, hashlib, time, numpy as np
from datetime import datetime

# === 설정 ===
SYMBOLS = {
    "BTCUSDT": {"leverage": 10, "amount": 150},
    "ETHUSDT": {"leverage": 7, "amount": 120},
}
INST_TYPE = "USDT-FUTURES"
CHANNEL = "candle15m"
MAX_CANDLES = 100
candles = {symbol: [] for symbol in SYMBOLS}
position_data = {symbol: None for symbol in SYMBOLS}

API_KEY = "bg_a9c07aa3168e846bfaa713fe9af79d14"
API_SECRET = "5be628fd41dce5eff78a607f31d096a4911d4e2156b6d66a14be20f027068043"
API_PASSPHRASE = "1q2w3e4r"
TELEGRAM_TOKEN = "7776435078:AAFsM_jIDSx1Eij4YJyqJp-zEDtQVtKohnU"
TELEGRAM_CHAT_ID = "1797494660"

# === 지표 계산 ===
def calculate_cci(prices, period=14):
    if len(prices) < period:
        return None
    tp = (prices[:,1] + prices[:,2] + prices[:,3]) / 3
    ma = np.convolve(tp, np.ones(period)/period, mode='valid')
    md = np.array([np.mean(np.abs(tp[i-period+1:i+1] - ma[i-period+1])) for i in range(period-1, len(tp))])
    cci = (tp[period-1:] - ma) / (0.015 * md)
    return cci[-1] if len(cci) > 0 else None

def calculate_adx(prices, period=5):
    if len(prices) <= period + 1:
        return None
    high, low, close = prices[:,2], prices[:,3], prices[:,4]
    plus_dm = np.where((high[1:] - high[:-1]) > (low[:-1] - low[1:]), high[1:] - high[:-1], 0)
    minus_dm = np.where((low[:-1] - low[1:]) > (high[1:] - high[:-1]), low[:-1] - low[1:], 0)
    tr = np.maximum(high[1:], close[:-1]) - np.minimum(low[1:], close[:-1])
    tr_smooth = np.convolve(tr, np.ones(period)/period, mode='valid')
    plus_di = 100 * np.convolve(plus_dm, np.ones(period)/period, mode='valid') / tr_smooth
    minus_di = 100 * np.convolve(minus_dm, np.ones(period)/period, mode='valid') / tr_smooth
    dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = np.convolve(dx, np.ones(period)/period, mode='valid')
    return adx[-1] if len(adx) > 0 else None

# === 텔레그램 ===
def send_telegram(msg):
    try:
        requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                     params={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
    except Exception as e:
        print(f"텔레그램 오류: {e}")

# === 주문 ===
def place_market_order(symbol, side):
    entry_price = candles[symbol][-1][4]
    print(f"[주문] {symbol} {side.upper()} ${entry_price}")
    send_telegram(f"{'🟢' if side=='long' else '🔴'} {symbol} {side} 진입 @ {entry_price}")
    position_data[symbol] = {
        "side": side,
        "entry": float(entry_price),
        "trail_mode": False,
        "trail_max": float(entry_price)
    }

# === 청산 ===
def close_position(symbol, price, reason):
    pos = position_data[symbol]
    entry = pos["entry"]
    side = pos["side"]
    pnl = ((price - entry) / entry) * (1 if side == "long" else -1) * 100
    send_telegram(f"{'🔺' if pnl > 0 else '🔻'} {symbol} {side} 청산 @ {price:.2f} ({pnl:.2f}%) | {reason}")
    position_data[symbol] = None

# === 전략 ===
def strategy(symbol):
    if len(candles[symbol]) < 30:
        return
    prices = np.array(candles[symbol], dtype=float)
    cci = calculate_cci(prices)
    adx = calculate_adx(prices)
    price = float(prices[-1][4])

    if cci is None or adx is None:
        return

    pos = position_data[symbol]
    if pos is None:
        if cci > 100 and adx > 25:
            place_market_order(symbol, "long")
        elif cci < -100 and adx > 25:
            place_market_order(symbol, "short")
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

# === 메시지 처리 ===
def on_msg(msg):
    d = msg["data"][0]
    symbol = d["instId"]
    k = [int(d["ts"]), float(d["o"]), float(d["h"]), float(d["l"]), float(d["c"]), float(d["v"])]
    if candles[symbol] and candles[symbol][-1][0] == k[0]:
        candles[symbol][-1] = k
    else:
        candles[symbol].append(k)
        if len(candles[symbol]) > MAX_CANDLES:
            candles[symbol].pop(0)
        strategy(symbol)

# === WebSocket ===
async def ws_loop():
    uri = "wss://ws.bitget.com/v2/ws/public"
    async with websockets.connect(uri, ping_interval=20, ping_timeout=30) as ws:
        args = [{"instType": INST_TYPE, "channel": CHANNEL, "instId": s} for s in SYMBOLS]
        await ws.send(json.dumps({"op": "subscribe", "args": args}))
        print("✅ WS 연결됨 / candle15m 구독 시도")
        while True:
            msg = json.loads(await ws.recv())
            if msg.get("event") == "error":
                print(f"❌ 에러 응답: {msg}")
                break
            if msg.get("action") in ["snapshot", "update"]:
                on_msg(msg)

# === 실행 ===
if __name__ == "__main__":
    asyncio.run(ws_loop())



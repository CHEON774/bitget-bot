import asyncio, json, websockets
from datetime import datetime
import numpy as np

SYMBOL = "BTCUSDT"
INST_TYPE = "USDT-FUTURES"
CHANNEL = "candle1m"
MAX_CANDLES = 150
candles = []

def calculate_cci(candles, period=14):
    if len(candles) < period:
        return None
    tp = np.array([(float(c[2]) + float(c[3]) + float(c[4])) / 3 for c in candles[-period:]])
    ma = np.mean(tp)
    md = np.mean(np.abs(tp - ma))
    if md == 0:
        return 0
    return (tp[-1] - ma) / (0.015 * md)

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
    dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) != 0 else 0
    return dx

def on_msg(msg):
    d = msg["data"][0]
    ts = int(d[0])
    candle = [ts, d[1], d[2], d[3], d[4], d[5]]
    candles.append(candle)
    if len(candles) > MAX_CANDLES:
        candles.pop(0)

    # 출력
    time_str = f"{datetime.fromtimestamp(ts/1000):%Y-%m-%d %H:%M:%S}"
    print(f"\n🕒 {time_str} | O:{d[1]} H:{d[2]} L:{d[3]} C:{d[4]} V:{d[5]}")

    if len(candles) >= 20:
        cci = calculate_cci(candles, 14)
        adx = calculate_adx(candles, 5)
        print(f"📊 CCI(14): {cci:.2f} | ADX(5): {adx:.2f}" if cci is not None and adx is not None else "⏳ 지표 계산 중...")

async def ws_loop():
    uri = "wss://ws.bitget.com/v2/ws/public"
    async with websockets.connect(uri, ping_interval=20) as ws:
        await ws.send(json.dumps({
            "op": "subscribe",
            "args": [{
                "instType": INST_TYPE,
                "channel": CHANNEL,
                "instId": SYMBOL
            }]
        }))
        print("✅ WS 연결됨 / candle1m 구독 시도")
        while True:
            msg = json.loads(await ws.recv())
            if msg.get("event") == "error":
                print(f"❌ 에러 응답: {msg}")
                return
            if msg.get("action") in ["snapshot", "update"]:
                on_msg(msg)

if __name__ == "__main__":
    asyncio.run(ws_loop())

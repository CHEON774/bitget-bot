import asyncio, json, pandas as pd, numpy as np
from datetime import datetime
import websockets

symbol = "BTCUSDT_UMCBL"
channel = "candle1m"
inst_type = "mix"
MAX = 200
candles = []

def calc(df):
    tp = (df.high + df.low + df.close) / 3
    df["CCI"] = (tp - tp.rolling(14).mean()) / (0.015 * tp.rolling(14).apply(lambda x: np.mean(abs(x - x.mean()))))
    df["EMA10"] = df.close.ewm(span=10).mean()
    df["ADX"] = 100 * abs(df.high.diff() - df.low.diff()).rolling(5).mean() / df.close.diff().rolling(5).mean()
    return df

def on_msg(msg):
    data = msg.get("data")
    if not isinstance(data, list) or not data:
        print("📩 비정상 수신:", msg)
        return
    ohlcv = data[0]  # 리스트 안의 첫 번째 캔들
    candles.append({
        "timestamp": int(ohlcv[0]),
        "open": float(ohlcv[1]),
        "close": float(ohlcv[2]),
        "high": float(ohlcv[3]),
        "low": float(ohlcv[4]),
        "volume": float(ohlcv[5])
    })
    if len(candles) > MAX:
        candles.pop(0)
    if len(candles) >= 20:
        df = calc(pd.DataFrame(candles))
        lt = df.iloc[-1]
        t = datetime.fromtimestamp(lt.timestamp / 1000).strftime("%H:%M")
        print(f"🕒 {t} | 💰 {lt.close:.2f} | CCI {lt.CCI:.2f} | EMA10 {lt.EMA10:.2f} | ADX {lt.ADX:.2f}")
    else:
        print(f"📉 수신 중... ({len(candles)})")

async def ws_loop():
    async with websockets.connect("wss://ws.bitget.com/v2/ws/public") as ws:
        sub = {"op": "subscribe", "args": [{"instType": inst_type, "channel": channel, "instId": symbol}]}
        await ws.send(json.dumps(sub))
        print("✅ WebSocket connected, subscribing candle1m...")
        while True:
            msg = json.loads(await ws.recv())
            print("📩", msg)
            if "data" in msg:
                on_msg(msg)

if __name__ == "__main__":
    asyncio.run(ws_loop())


import asyncio, json, pandas as pd, numpy as np
from datetime import datetime
import websockets

symbol = "BTCUSDT"
channel = "candle1m"
inst_type = "USDT-FUTURES"
MAX = 200
candles = []

def calc(df):
    tp = (df.high + df.low + df.close) / 3
    df["CCI"] = (tp - tp.rolling(14).mean()) / (0.015 * tp.rolling(14).apply(lambda x: np.mean(abs(x-x.mean()))))
    df["EMA10"] = df.close.ewm(span=10).mean()
    df["ADX"] = 100 * abs(df.high.diff() - df.low.diff()).rolling(5).mean() / df.close.diff().rolling(5).mean()
    return df

def on_msg(msg):
    d, ts = msg["data"], msg["ts"]
    candles.append({
        "timestamp": ts,
        "open": float(d["o"]), "high": float(d["h"]),
        "low": float(d["l"]), "close": float(d["c"]), "volume": float(d["v"])
    })
    if len(candles) > MAX: candles.pop(0)
    if len(candles) >= 20:
        df = calc(pd.DataFrame(candles)); lt = df.iloc[-1]
        t = datetime.fromtimestamp(lt.timestamp/1000).strftime("%H:%M")
        print(f"🕒 {t} | Close: {lt.close:.2f} | CCI: {lt.CCI:.2f} | EMA10: {lt.EMA10:.2f} | ADX: {lt.ADX:.2f}")
    else:
        print(f"📉 collecting {len(candles)}")

async def ws_loop():
    uri = "wss://ws.bitget.com/v2/ws/public"
    async with websockets.connect(uri) as ws:
        subscribe_msg = {
            "op": "subscribe",
            "args": [{
                "instType": inst_type,
                "channel": channel,
                "instId": symbol
            }]
        }
        await ws.send(json.dumps(subscribe_msg))
        print("✅ Connected to V2 WS, subscribing candle1m...")
        while True:
            msg = json.loads(await ws.recv())
            print("📩", msg)
            if msg.get("data"):
                on_msg(msg)

if __name__ == "__main__":
    asyncio.run(ws_loop())


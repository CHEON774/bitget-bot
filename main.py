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
    df["CCI"] = (tp - tp.rolling(14).mean()) / (0.015 * tp.rolling(14).apply(lambda x: np.mean(abs(x - x.mean()))))
    df["EMA10"] = df.close.ewm(span=10).mean()
    df["ADX"] = 100 * abs(df.high.diff() - df.low.diff()).rolling(5).mean() / df.close.diff().rolling(5).mean()
    return df

def on_msg(msg):
    d = msg.get("data"); ts = msg.get("ts", 0)
    if not d: return print("⚠️ no data", msg)
    candles.append({"timestamp": ts, "open":float(d["o"]), "high":float(d["h"]), "low":float(d["l"]), "close":float(d["c"]), "volume":float(d["v"])})
    if len(candles) > MAX: candles.pop(0)
    if len(candles) >= 20:
        df = calc(pd.DataFrame(candles))
        lt = df.iloc[-1]
        t = datetime.fromtimestamp(lt.timestamp/1000).strftime("%Y-%m-%d %H:%M:%S")
        print(f"🕒 {t} | 💰 {lt.close:.2f} | CCI {lt.CCI:.2f} | EMA10 {lt.EMA10:.2f} | ADX {lt.ADX:.2f}")
    else:
        print(f"📉 collecting... {len(candles)}")

async def ws_loop():
    uri = "wss://ws.bitget.com/mix/v1/stream"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({
            "op":"subscribe",
            "args":[{
                "instType": inst_type,
                "channel": channel,
                "instId": symbol
            }]
        }))
        print("✅ WebSocket connected, subscribing candle1m...")
        while True:
            try:
                msg = json.loads(await ws.recv())
                if "data" in msg: on_msg(msg)
                else: print("📩", msg)
            except Exception as e:
                print("❌ WS error:", e)
                break

if __name__=="__main__":
    asyncio.run(ws_loop())

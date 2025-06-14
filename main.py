import asyncio, json, pandas as pd, numpy as np
from datetime import datetime
import websockets

symbol = "BTCUSDT_UMCBL"
channel = "candle1m"
inst_type = "mc"
candles = []

def calc(df):
    tp = (df.high + df.low + df.close) / 3
    df["CCI"] = (tp - tp.rolling(14).mean()) / (0.015 * tp.rolling(14).apply(lambda x: np.mean(abs(x - x.mean()))))
    df["EMA10"] = df.close.ewm(span=10).mean()
    df["ADX"] = 100 * abs(df.high.diff() - df.low.diff()).rolling(5).mean() / df.close.diff().rolling(5).mean()
    return df

def on_msg(msg):
    data = msg.get("data")
    if not data or not isinstance(data, list):
        print("❌ 잘못된 데이터 형식:", msg)
        return

    d = data[0]  # ✅ 리스트 안의 첫 dict
    ts = int(msg["ts"])
    candles.append({
        "timestamp": ts,
        "open": float(d[1]),
        "high": float(d[3]),
        "low": float(d[4]),
        "close": float(d[2]),
        "volume": float(d[5])
    })
    if len(candles) > 200:
        candles.pop(0)

    if len(candles) >= 20:
        df = calc(pd.DataFrame(candles))
        lt = df.iloc[-1]
        t = datetime.fromtimestamp(lt.timestamp / 1000).strftime("%H:%M")
        print(f"🕒 {t} | Close: {lt.close:.2f} | CCI: {lt.CCI:.2f} | EMA10: {lt.EMA10:.2f} | ADX: {lt.ADX:.2f}")
    else:
        print(f"📉 수신 중... ({len(candles)}개 수집됨)")

async def ws_loop():
    uri = "wss://ws.bitget.com/v2/ws/public"
    async with websockets.connect(uri) as ws:
        sub_msg = {
            "op": "subscribe",
            "args": [{
                "instType": inst_type,
                "channel": channel,
                "instId": symbol
            }]
        }
        await ws.send(json.dumps(sub_msg))
        print("✅ WebSocket connected, subscribing candle1m...")

        while True:
            raw = await ws.recv()
            msg = json.loads(raw)
            print("📩 수신 원문:", msg)
            if "data" in msg:
                on_msg(msg)

if __name__ == "__main__":
    asyncio.run(ws_loop())


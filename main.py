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
    df["CCI"] = (tp - tp.rolling(150).mean()) / (0.015 * tp.rolling(150).apply(lambda x: np.mean(abs(x-x.mean()))))
    return df

def on_msg(msg):
    data = msg.get("data")
    if not data or not isinstance(data, list):
        print("📩 수신 이상:", msg)
        return
    ohlcv = data[0]
    candles.append({
        "timestamp": int(ohlcv[0]),
        "open": float(ohlcv[1]),
        "high": float(ohlcv[2]),
        "low": float(ohlcv[3]),
        "close": float(ohlcv[4]),
        "volume": float(ohlcv[5])
    })
    if len(candles) > MAX: candles.pop(0)
    if len(candles) >= 150:
        df = pd.DataFrame(candles)
        df = calc(df)
        latest = df.iloc[-1]
        t = datetime.fromtimestamp(latest.timestamp / 1000).strftime("%H:%M")
        print(f"🕒 {t} | Close: {latest.close:.2f} | CCI: {latest.CCI:.2f}")
    else:
        print(f"📉 수신 중... {len(candles)}/{150}")

async def ws_loop():
    async with websockets.connect("wss://ws.bitget.com/v2/ws/public") as ws:
        await ws.send(json.dumps({
            "op": "subscribe",
            "args": [{
                "instType": inst_type,
                "channel": channel,
                "instId": symbol
            }]
        }))
        print("✅ WS 연결됨, candle1m 구독 시도")
        while True:
            msg = json.loads(await ws.recv())
            print("📩", msg)
            if "data" in msg:
                on_msg(msg)

if __name__=="__main__":
    asyncio.run(ws_loop())

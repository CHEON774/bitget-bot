import asyncio
import websockets
import json
import pandas as pd
import numpy as np
from datetime import datetime

symbol = "BTCUSDT"
channel = "candle1m"
inst_type = "USDT-FUTURES"
MAX_CANDLES = 200
candles = []

def calculate_indicators(df):
    tp = (df["high"] + df["low"] + df["close"]) / 3
    ma = tp.rolling(14).mean()
    md = tp.rolling(14).apply(lambda x: np.mean(np.abs(x - np.mean(x))), raw=True)
    cci = (tp - ma) / (0.015 * md)
    ema10 = df["close"].ewm(span=10).mean()
    df["CCI"] = cci
    df["EMA10"] = ema10
    return df

def handle_message(msg):
    global candles
    d = msg["data"]
    ts = msg["ts"]

    candles.append({
        "timestamp": ts,
        "open": float(d["o"]),
        "high": float(d["h"]),
        "low": float(d["l"]),
        "close": float(d["c"]),
        "volume": float(d["v"])
    })

    if len(candles) > MAX_CANDLES:
        candles.pop(0)

    if len(candles) >= 20:
        df = pd.DataFrame(candles)
        df = calculate_indicators(df)
        latest = df.iloc[-1]
        t = datetime.fromtimestamp(latest["timestamp"] / 1000).strftime("%H:%M")
        print(f"🕒 {t} | 💰 Close: {latest['close']:.2f} | CCI: {latest['CCI']:.2f} | EMA10: {latest['EMA10']:.2f}")
    else:
        print(f"📉 수신 중... ({len(candles)}개 캔들 수집됨)")

async def subscribe_ws():
    uri = "wss://ws.bitget.com/mix/v1/stream"
    async with websockets.connect(uri) as ws:
        subscribe_msg = {
            "op": "subscribe",
            "args": [{
                "instType": "USDT-FUTURES",
                "channel": "candle1m",
                "instId": "BTCUSDT"
            }]
        }
        await ws.send(json.dumps(subscribe_msg))
        print("✅ WebSocket connected, subscribing candle1m...")

        while True:
            try:
                msg = await ws.recv()
                data = json.loads(msg)
                print("📩 수신 원문:", data)
                if "data" in data:
                    handle_message(data)
            except Exception as e:
                print(f"❌ WebSocket 에러: {e}")
                break

if __name__ == "__main__":
    asyncio.run(subscribe_ws())


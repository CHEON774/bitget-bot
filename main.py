import asyncio
import websockets
import json
import pandas as pd
import numpy as np
from datetime import datetime

symbol = "BTCUSDT"
channel = "candle15m"
inst_type = "USDT-FUTURES"
MAX_CANDLES = 150
candles = []

def calculate_indicators(df):
    tp = (df["high"] + df["low"] + df["close"]) / 3
    ma = tp.rolling(14).mean()
    md = tp.rolling(14).apply(lambda x: np.mean(np.abs(x - np.mean(x))), raw=True)
    cci = (tp - ma) / (0.015 * md)
    ema10 = df["close"].ewm(span=10).mean()

    delta_high = df["high"].diff()
    delta_low = df["low"].diff()
    plus_dm = np.where((delta_high > delta_low) & (delta_high > 0), delta_high, 0)
    minus_dm = np.where((delta_low > delta_high) & (delta_low > 0), delta_low, 0)
    tr = pd.concat([
        df["high"] - df["low"],
        abs(df["high"] - df["close"].shift(1)),
        abs(df["low"] - df["close"].shift(1))
    ], axis=1).max(axis=1)
    atr = tr.rolling(5).mean()
    plus_di = 100 * pd.Series(plus_dm).rolling(5).mean() / atr
    minus_di = 100 * pd.Series(minus_dm).rolling(5).mean() / atr
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = dx.rolling(5).mean()

    df["CCI"] = cci
    df["EMA10"] = ema10
    df["ADX"] = adx
    return df

def handle_candle(data):
    global candles
    d = data[0]  # WebSocket 응답은 리스트로 감싸짐
    candles.append({
        "timestamp": int(d[0]),
        "open": float(d[1]),
        "high": float(d[2]),
        "low": float(d[3]),
        "close": float(d[4]),
        "volume": float(d[5])
    })
    if len(candles) > MAX_CANDLES:
        candles.pop(0)

    if len(candles) >= 20:
        df = pd.DataFrame(candles)
        df = calculate_indicators(df)
        latest = df.iloc[-1]
        time_str = datetime.fromtimestamp(latest["timestamp"] / 1000).strftime('%Y-%m-%d %H:%M')
        print(f"\n🕒 {time_str} | 💰C: {latest['close']:.2f} | CCI: {latest['CCI']:.2f} | EMA10: {latest['EMA10']:.2f} | ADX: {latest['ADX']:.2f}")
    else:
        print(f"📉 수신 중... {len(candles)}/{MAX_CANDLES}")

async def ws_loop():
    uri = "wss://ws.bitget.com/mix/v1/stream"
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
        print("✅ WebSocket connected, subscribing candle15m...")

        while True:
            try:
                msg = await ws.recv()
                data = json.loads(msg)
                if "data" in data:
                    print(f"📩 {data}")
                    handle_candle(data["data"])
                elif "event" in data and data["event"] == "error":
                    print(f"❌ 에러 응답: {data}")
            except Exception as e:
                print(f"❌ WebSocket 예외: {e}")
                break

if __name__ == "__main__":
    asyncio.run(ws_loop())


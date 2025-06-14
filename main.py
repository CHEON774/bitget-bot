import asyncio
import websockets
import json
import pandas as pd
import numpy as np
from datetime import datetime

# 설정
symbol = "BTCUSDT_UMCBL"
channel = "candle1m"
MAX_CANDLES = 200
candles = []

# 지표 계산
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

# 수신 처리
def on_msg(msg):
    global candles
    if "data" not in msg:
        print(f"📩 수신 원문: {msg}")
        return

    d = msg["data"][0]  # 리스트 내부 dict 구조

    candles.append({
        "timestamp": int(d[0]),
        "open": float(d[1]),
        "close": float(d[2]),
        "high": float(d[3]),
        "low": float(d[4]),
        "volume": float(d[5]),
    })

    if len(candles) > MAX_CANDLES:
        candles.pop(0)

    if len(candles) >= 20:
        df = pd.DataFrame(candles)
        df = calculate_indicators(df)
        latest = df.iloc[-1]
        time_str = datetime.fromtimestamp(latest["timestamp"] / 1000).strftime('%Y-%m-%d %H:%M:%S')
        print(f"🕒 {time_str} | 💰 Close: {latest['close']:.2f} | CCI: {latest['CCI']:.2f} | EMA10: {latest['EMA10']:.2f} | ADX: {latest['ADX']:.2f}")
    else:
        print(f"📉 수신 중... ({len(candles)}개 캔들 수집됨)")

# WebSocket 루프
async def ws_loop():
    uri = "wss://ws.bitget.com/mix/v1/stream"
    async with websockets.connect(uri) as ws:
        sub = {
            "op": "subscribe",
            "args": [{
                "instType": "UMCBL",
                "channel": channel,
                "instId": symbol
            }]
        }
        await ws.send(json.dumps(sub))
        print("✅ WebSocket connected, subscribing candle1m...")

        while True:
            try:
                msg = await ws.recv()
                data = json.loads(msg)
                on_msg(data)
            except Exception as e:
                print(f"❌ Error: {e}")
                break

# 실행
if __name__ == "__main__":
    asyncio.run(ws_loop())


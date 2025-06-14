import asyncio
import websockets
import json
import pandas as pd
import numpy as np
from datetime import datetime

# ========= 설정 =========
symbol = "BTCUSDT"          # Bitget 선물 WebSocket용 instId
channel = "candle1m"        # 1분봉 채널 (소문자 m)
inst_type = "USDT-FUTURES"  # 선물 마켓 식별자
MAX_CANDLES = 200
candles = []

# ========= 지표 계산 =========
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

# ========= 수신 처리 =========
def handle_candle_message(msg):
    global candles
    d = msg.get("data")
    ts = msg.get("ts", 0)
    if not d:
        print(f"⚠️ 수신된 데이터 없음: {msg}")
        return

    candles.append({
        "timestamp": ts,
        "open": float(d["o"]),
        "high": float(d["h"]),
        "low": float(d["l"]),
        "close": float(d["c"]),
        "volume": float(d["v"]),
    })
    if len(candles) > MAX_CANDLES:
        candles.pop(0)

    if len(candles) >= 20:
        df = calculate_indicators(pd.DataFrame(candles))
        latest = df.iloc[-1]
        time_str = datetime.fromtimestamp(latest["timestamp"] / 1000).strftime('%Y-%m-%d %H:%M:%S')
        print(f"🕒 {time_str} | 💰 {latest['close']:.2f} | CCI {latest['CCI']:.2f} | EMA10 {latest['EMA10']:.2f} | ADX {latest['ADX']:.2f}")
    else:
        print(f"📉 수신 중... ({len(candles)}개 수집됨)")

# ========= Ping =========
async def send_ping(ws):
    while True:
        try:
            await ws.ping()
        except Exception as e:
            print(f"❌ Ping 실패: {e}")
            break
        await asyncio.sleep(20)

# ========= WebSocket 연결 =========
async def connect_ws():
    uri = "wss://ws.bitget.com/mix/v1/stream"
    async with websockets.connect(uri) as ws:
        sub = {
            "op": "subscribe",
            "args": [{
                "instType": inst_type,
                "channel": channel,
                "instId": symbol
            }]
        }
        await ws.send(json.dumps(sub))
        print("✅ WebSocket 연결됨. 실시간 1분봉 수신 시작\n")
        asyncio.create_task(send_ping(ws))

        while True:
            try:
                msg = await ws.recv()
                data = json.loads(msg)
                if "data" in data:
                    handle_candle_message(data)
                else:
                    print(f"📩 수신 원문: {data}")
            except Exception as e:
                print(f"❌ WebSocket 에러: {e}")
                break

if __name__ == "__main__":
    asyncio.run(connect_ws())


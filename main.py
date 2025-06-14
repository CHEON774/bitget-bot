import asyncio
import json
import websockets
from datetime import datetime

# Constants
SYMBOL = "BTCUSDT"
CHANNEL = "candle1m"
INST_TYPE = "USDT-FUTURES"
MAX_CANDLES = 150
candles = []

# WebSocket Endpoint
WS_URL = "wss://ws.bitget.com/mix/v1/stream"

# Function: Process incoming message
def on_msg(msg):
    global candles
    if 'data' in msg:
        d = msg["data"][0]  # 첫 번째 캔들
        ts = int(d[0])  # timestamp
        candles.append({
            "timestamp": ts,
            "open": float(d[1]),
            "high": float(d[2]),
            "low": float(d[3]),
            "close": float(d[4]),
            "volume": float(d[5]),
        })
        if len(candles) > MAX_CANDLES:
            candles.pop(0)

        dt = datetime.fromtimestamp(ts / 1000).strftime('%Y-%m-%d %H:%M:%S')
        print(f"\n🕒 {dt} | 📉 O:{float(d[1]):.1f} H:{float(d[2]):.1f} L:{float(d[3]):.1f} C:{float(d[4]):.1f} | 📊 Vol:{float(d[5]):.3f} | 💵 Value: {float(d[6]):,.2f}")
    else:
        print("📩 수신된 데이터에 'data' 없음")

# Async function: WebSocket connection
async def ws_loop():
    async with websockets.connect(WS_URL, ping_interval=20) as ws:
        print("✅ WebSocket connected, subscribing candle1m...")

        # 구독 요청
        sub = {
            "op": "subscribe",
            "args": [
                {
                    "instType": INST_TYPE,
                    "channel": CHANNEL,
                    "instId": SYMBOL
                }
            ]
        }
        await ws.send(json.dumps(sub))

        while True:
            try:
                msg = await ws.recv()
                data = json.loads(msg)
                if isinstance(data, dict):
                    if data.get("event") == "error":
                        print(f"❌ 에러 응답: {data}")
                    elif data.get("action") == "update":
                        on_msg(data)
                    else:
                        print(f"📩 기타 응답: {data}")
            except websockets.exceptions.ConnectionClosed as e:
                print(f"❌ WebSocket 연결 종료: {e}")
                break
            except Exception as e:
                print(f"❌ 예외 발생: {e}")
                continue

if __name__ == "__main__":
    try:
        asyncio.run(ws_loop())
    except KeyboardInterrupt:
        print("🛑 종료됨")


import asyncio
import websockets
import json
import datetime

# WebSocket URL
WS_URL = "wss://ws.bitget.com/mix/v1/stream"

# 구독할 채널 정보
SUBSCRIBE_DATA = {
    "op": "subscribe",
    "args": [
        {
            "instType": "UMCBL",
            "channel": "candle15m",
            "instId": "BTCUSDT_UMCBL"
        }
    ]
}

# 메시지 처리 함수
def handle_message(msg):
    if "data" not in msg:
        return

    for candle in msg["data"]:
        timestamp = int(candle[0]) // 1000
        dt = datetime.datetime.fromtimestamp(timestamp)
        o, h, l, c, vol = map(float, candle[1:6])
        print(f"\n🕒 {dt.strftime('%Y-%m-%d %H:%M:%S')} | O:{o} H:{h} L:{l} C:{c} V:{vol}")

# WebSocket 루프
async def ws_loop():
    async with websockets.connect(WS_URL, ping_interval=30) as ws:
        await ws.send(json.dumps(SUBSCRIBE_DATA))
        print("\n✅ WebSocket connected, subscribing candle15m...")

        while True:
            try:
                msg = await ws.recv()
                data = json.loads(msg)
                print(f"\n📩 수신 원문: {data}")
                handle_message(data)
            except Exception as e:
                print(f"\n❌ WebSocket 예외: {e}")
                break

if __name__ == "__main__":
    asyncio.run(ws_loop())


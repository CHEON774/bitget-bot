import asyncio
import websockets
import json

async def main():
    uri = "wss://stream.bybit.com/v5/public/linear"
    async with websockets.connect(uri, ping_interval=10, ping_timeout=10) as ws:
        print("✅ WebSocket 연결됨")
        sub = {
            "op": "subscribe",
            "args": [
                "kline.15.BTCUSDT",
                "kline.15.ETHUSDT",
                "kline.15.SOLUSDT"
            ]
        }
        await ws.send(json.dumps(sub))
        while True:
            msg = await ws.recv()
            print(msg)  # 실제로 들어오는 원본 메시지 출력!

asyncio.run(main())


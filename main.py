import asyncio, json, pandas as pd, numpy as np
from datetime import datetime
import websockets

symbol = "BTCUSDT"
channel = "candle1m"
inst_type = "UMCBL"

async def ws_loop():
    uri = "wss://ws.bitget.com/mix/v1/stream"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({
            "op": "subscribe",
            "args": [{
                "instType": inst_type,
                "channel": channel,
                "instId": symbol
            }]
        }))
        print("✅ WebSocket connected, subscribing candle1m...")
        while True:
            msg = json.loads(await ws.recv())
            print("📩", msg)
            if "data" in msg:
                print("📉 캔들 수신 성공!")
                break  # 여기까지만 테스트


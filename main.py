import asyncio
import json
import websockets
from datetime import datetime

SYMBOL = "BTCUSDT"
INST_TYPE = "USDT-FUTURES"
CHANNEL = "candle15m"

async def subscribe(ws):
    await ws.send(json.dumps({
        "op": "subscribe",
        "args": [{
            "instType": INST_TYPE,
            "channel": CHANNEL,
            "instId": SYMBOL
        }]
    }))
    print("✅ WebSocket 연결 및 구독 완료")

def on_msg(msg):
    try:
        d = msg["data"][0]
        ts = int(d[0])
        print(f"🕒 {datetime.fromtimestamp(ts/1000):%Y-%m-%d %H:%M:%S} | O:{d[1]} H:{d[2]} L:{d[3]} C:{d[4]} V:{d[5]}")
    except Exception as e:
        print(f"⚠️ 메시지 처리 오류: {e}")

async def ws_loop():
    uri = "wss://ws.bitget.com/v2/ws/public"
    while True:
        try:
            async with websockets.connect(uri, ping_interval=20, ping_timeout=20) as ws:
                await subscribe(ws)
                while True:
                    raw = await ws.recv()
                    msg = json.loads(raw)
                    if msg.get("event") == "error":
                        print(f"❌ 에러 응답: {msg}")
                        break
                    if msg.get("action") in ("snapshot", "update"):
                        on_msg(msg)
        except Exception as e:
            print(f"⚠️ 연결 오류: {e}\n🔁 5초 후 재연결 시도...")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(ws_loop())

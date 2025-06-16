import asyncio, json, websockets
from datetime import datetime

SYMBOL = "BTCUSDT"
INST_TYPE = "USDT-FUTURES"
CHANNEL = "candle1m"
MAX_CANDLES = 150
candles = []

def on_msg(msg):
    d = msg["data"][0]
    ts = int(d[0])
    print(f"🕒 {datetime.fromtimestamp(ts/1000):%Y-%m-%d %H:%M:%S} | O:{d[1]} H:{d[2]} L:{d[3]} C:{d[4]} V:{d[5]}")

async def ws_loop():
    uri = "wss://ws.bitget.com/v2/ws/public"
    async with websockets.connect(uri, ping_interval=20) as ws:
        await ws.send(json.dumps({
            "op": "subscribe",
            "args": [{
                "instType": INST_TYPE,
                "channel": CHANNEL,
                "instId": SYMBOL
            }]
        }))
        print("✅ WS 연결됨 / candle1m 구독 시도")
        while True:
            msg = json.loads(await ws.recv())
            if msg.get("event") == "error":
                print(f"❌ 에러 응답: {msg}")
                return
            if msg.get("action") == "snapshot" or msg.get("action") == "update":
                on_msg(msg)

if __name__ == "__main__":
    asyncio.run(ws_loop())
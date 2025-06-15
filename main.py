import asyncio, json, websockets, requests
from datetime import datetime
import numpy as np

# === 사용자 설정 ===
SYMBOL = "BTCUSDT"
INST_TYPE = "USDT-FUTURES"
CHANNEL = "candle1m"
MAX_CANDLES = 150
BOT_TOKEN = "7776435078:AAFsM_jIDSx1Eij4YJyqJp-zEDtQVtKohnU"
CHAT_ID = "1797494660"
# ==================

candles = []
last_completed_ts = None

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": msg}
    try:
        requests.post(url, data=data)
    except Exception as e:
        print(f"⚠️ 텔레그램 전송 실패: {e}")

def calculate_cci(candles, period=14):
    if len(candles) < period:
        return None
    tp = np.array([(float(c[2]) + float(c[3]) + float(c[4])) / 3 for c in candles[-period:]])
    ma = np.mean(tp)
    md = np.mean(np.abs(tp - ma))
    if md == 0:
        return 0
    return (tp[-1] - ma) / (0.015 * md)

def calculate_adx(candles, period=5):
    if len(candles) < period + 1:
        return None
    high = np.array([float(c[2]) for c in candles])
    low = np.array([float(c[3]) for c in candles])
    close = np.array([float(c[4]) for c in candles])

    tr = np.maximum(high[1:], close[:-1]) - np.minimum(low[1:], close[:-1])
    plus_dm = np.where((high[1:] - high[:-1]) > (low[:-1] - low[1:]), 
                       np.maximum(high[1:] - high[:-1], 0), 0)
    minus_dm = np.where((low[:-1] - low[1:]) > (high[1:] - high[:-1]),
                        np.maximum(low[:-1] - low[1:], 0), 0)

    atr = np.mean(tr[-period:])
    plus_di = 100 * (np.mean(plus_dm[-period:]) / atr) if atr != 0 else 0
    minus_di = 100 * (np.mean(minus_dm[-period:]) / atr) if atr != 0 else 0
    dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) != 0 else 0
    return dx

def on_msg(msg):
    global last_completed_ts
    d = msg["data"][0]
    ts = int(d[0])
    candle = [ts, d[1], d[2], d[3], d[4], d[5]]

    if candles and candles[-1][0] == ts:
        candles[-1] = candle
    else:
        candles.append(candle)
        if len(candles) > MAX_CANDLES:
            candles.pop(0)

    if len(candles) >= 20:
        prev_candle = candles[-2]
        prev_ts = prev_candle[0]
        if last_completed_ts == prev_ts:
            return
        last_completed_ts = prev_ts

        time_str = f"{datetime.fromtimestamp(prev_ts / 1000):%Y-%m-%d %H:%M:%S}"
        print(f"\n🕒 {time_str} | O:{prev_candle[1]} H:{prev_candle[2]} L:{prev_candle[3]} C:{prev_candle[4]} V:{prev_candle[5]}")

        cci = calculate_cci(candles[:-1], 14)
        adx = calculate_adx(candles[:-1], 5)

        if cci is not None and adx is not None:
            print(f"📊 CCI(14): {cci:.2f} | ADX(5): {adx:.2f}")

            if adx > 25:
                if cci > 100:
                    msg = f"📈 [LONG 진입] CCI={cci:.2f}, ADX={adx:.2f} | {time_str}"
                    print(msg)
                    send_telegram(msg)
                elif cci < -100:
                    msg = f"📉 [SHORT 진입] CCI={cci:.2f}, ADX={adx:.2f} | {time_str}"
                    print(msg)
                    send_telegram(msg)
        else:
            print("⏳ 지표 계산 중...")

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
        print("✅ WS 연결됨 / candle15m 구독 시도")
        while True:
            msg = json.loads(await ws.recv())
            if msg.get("event") == "error":
                print(f"❌ 에러 응답: {msg}")
                return
            if msg.get("action") in ["snapshot", "update"]:
                on_msg(msg)

if __name__ == "__main__":
    asyncio.run(ws_loop())


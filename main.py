import asyncio, json, websockets, requests
from datetime import datetime
import numpy as np

SYMBOL = "BTCUSDT"
INST_TYPE = "USDT-FUTURES"
CHANNEL = "candle1m"
MAX_CANDLES = 150
candles = []

BOT_TOKEN = "7776435078:AAFsM_jIDSx1Eij4YJyqJp-zEDtQVtKohnU"
CHAT_ID = "1797494660'"

last_completed_ts = None  # 지표 출력 중복 방지용

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except Exception as e:
        print(f"⚠️ 텔레그램 전송 실패: {e}")

def calculate_cci(candles, period=14):
    if len(candles) < period:
        return None
    tp = np.array([(float(c[2]) + float(c[3]) + float(c[4])) / 3 for c in candles[-period:]])
    ma = np.mean(tp)
    md = np.mean(np.abs(tp - ma))
    return 0 if md == 0 else (tp[-1] - ma) / (0.015 * md)

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
    return abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) != 0 else 0

# ✅ 이 부분이 연동된 WebSocket 기준 코드 (변경 ❌)
def on_msg(msg):
    d = msg["data"][0]
    ts = int(d[0])
    print(f"🕒 {datetime.fromtimestamp(ts/1000):%Y-%m-%d %H:%M:%S} | O:{d[1]} H:{d[2]} L:{d[3]} C:{d[4]} V:{d[5]}")

    # ✅ 아래부터 기능 추가만 허용
    global last_completed_ts
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
        print(f"\n✅ 완성된 캔들 ▶️ {time_str} | O:{prev_candle[1]} H:{prev_candle[2]} L:{prev_candle[3]} C:{prev_candle[4]}")

        cci = calculate_cci(candles[:-1], 14)
        adx = calculate_adx(candles[:-1], 5)

        if cci is not None and adx is not None:
            log = f"📊 CCI(14): {cci:.2f} | ADX(5): {adx:.2f}"
            print(log)
            send_telegram(log)

# ✅ 절대 변경 금지: WebSocket 연결 구조
async def ws_loop():
    uri = "wss://ws.bitget.com/v2/ws/public"
    while True:
        try:
            async with websockets.connect(uri, ping_interval=20, ping_timeout=30) as ws:
                await ws.send(json.dumps({
                    "op": "subscribe",
                    "args": [{
                        "instType": "usdt-futures",   # ✅ Bitget 요구대로 소문자
                        "channel": "candle1m",
                        "instId": "BTCUSDT"
                    }]
                }))
                print(f"✅ WS 연결됨 / {CHANNEL} 구독 시도")
                while True:
                    raw = await ws.recv()
                    msg = json.loads(raw)
                    if msg.get("event") == "error":
                        print(f"❌ 에러 응답: {msg}")
                        break
                    if msg.get("action") in ["snapshot", "update"]:
                        on_msg(msg)
        except Exception as e:
            print(f"⚠️ WebSocket 연결 오류: {e}")
            print("🔁 5초 후 재연결 시도 중...")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(ws_loop())


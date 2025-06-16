import asyncio, json, websockets, requests
from datetime import datetime
import numpy as np

# 설정값
SYMBOL = "BTCUSDT"
INST_TYPE = "USDT-FUTURES"  # ✅ 공식 문서 기준
CHANNEL = "candle1m"
MAX_CANDLES = 150
candles = []

# 텔레그램 설정
BOT_TOKEN = "여기에_봇토큰_입력"
CHAT_ID = "여기에_chat_id_입력"

last_completed_ts = None  # 마지막으로 처리한 캔들 시각

# 텔레그램 메시지 전송 함수
def send_telegram(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except Exception as e:
        print(f"⚠️ 텔레그램 전송 실패: {e}")

# CCI 계산 함수
def calculate_cci(candles, period=14):
    if len(candles) < period:
        return None
    tp = np.array([(float(c[2]) + float(c[3]) + float(c[4])) / 3 for c in candles[-period:]])
    ma = np.mean(tp)
    md = np.mean(np.abs(tp - ma))
    return 0 if md == 0 else (tp[-1] - ma) / (0.015 * md)

# ADX 계산 함수
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

# WebSocket 수신 처리
def on_msg(msg):
    global last_completed_ts
    d = msg["data"][0]
    ts = int(d[0])
    candle = [ts, d[1], d[2], d[3], d[4], d[5]]

    # 최신 캔들 업데이트
    if candles and candles[-1][0] == ts:
        candles[-1] = candle
    else:
        candles.append(candle)
        if len(candles) > MAX_CANDLES:
            candles.pop(0)

        # 캔들 완성 시점 (이전 캔들)
        if len(candles) >= 20:
            prev_candle = candles[-2]
            prev_ts = prev_candle[0]
            if last_completed_ts == prev_ts:
                return  # 중복 방지
            last_completed_ts = prev_ts

            # 출력 및 지표 계산
            time_str = f"{datetime.fromtimestamp(prev_ts / 1000):%Y-%m-%d %H:%M:%S}"
            print(f"\n✅ 완성된 캔들 ▶️ {time_str} | O:{prev_candle[1]} H:{prev_candle[2]} L:{prev_candle[3]} C:{prev_candle[4]}")

            cci = calculate_cci(candles[:-1], 14)
            adx = calculate_adx(candles[:-1], 5)

            if cci is not None and adx is not None:
                log = f"📊 CCI(14): {cci:.2f} | ADX(5): {adx:.2f}"
                print(log)
                send_telegram(log)

    # 실시간 업데이트 로그 (선택적으로 출력 가능)
    print(f"🕒 {datetime.fromtimestamp(ts/1000):%Y-%m-%d %H:%M:%S} | O:{d[1]} H:{d[2]} L:{d[3]} C:{d[4]} V:{d[5]}")

# WebSocket 루프
async def ws_loop():
    uri = "wss://ws.bitget.com/v2/ws/public"
    while True:
        try:
            async with websockets.connect(uri, ping_interval=20, ping_timeout=30) as ws:
                payload = {
                    "op": "subscribe",
                    "args": [{
                        "instType": INST_TYPE,
                        "channel": CHANNEL,
                        "instId": SYMBOL
                    }]
                }
                print("📤 전송 메시지:", json.dumps(payload))
                await ws.send(json.dumps(payload))
                print("✅ WS 연결됨 / candle1m 구독 시도")

                while True:
                    msg = json.loads(await ws.recv())
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

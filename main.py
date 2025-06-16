import asyncio, json, websockets, requests
from datetime import datetime
import numpy as np

# 설정
SYMBOLS = ["BTCUSDT", "ETHUSDT"]
INST_TYPE = "USDT-FUTURES"
CHANNEL = "candle15m"  # ✅ 15분봉으로 변경
MAX_CANDLES = 150
BOT_TOKEN = "7787612607:AAEHWXld8OqmK3OeGmo2nJdmx-Bg03h85UQ"
CHAT_ID = "1797494660"

# 심볼별 상태 저장
candles_dict = {symbol: [] for symbol in SYMBOLS}
last_completed_ts_dict = {symbol: None for symbol in SYMBOLS}

# 텔레그램 전송
def send_telegram(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except Exception as e:
        print(f"⚠️ 텔레그램 전송 실패: {e}")

# CCI 계산
def calculate_cci(candles, period=14):
    if len(candles) < period:
        return None
    tp = np.array([(float(c[2]) + float(c[3]) + float(c[4])) / 3 for c in candles[-period:]])
    ma = np.mean(tp)
    md = np.mean(np.abs(tp - ma))
    return 0 if md == 0 else (tp[-1] - ma) / (0.015 * md)

# ADX 계산
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

# 메시지 처리
def on_msg(symbol, d):
    global candles_dict, last_completed_ts_dict

    ts = int(d[0])
    candle = [ts, d[1], d[2], d[3], d[4], d[5]]
    candles = candles_dict[symbol]

    if candles and candles[-1][0] == ts:
        candles[-1] = candle
    else:
        candles.append(candle)
        if len(candles) > MAX_CANDLES:
            candles.pop(0)

        if len(candles) >= 20:
            prev_candle = candles[-2]
            prev_ts = prev_candle[0]
            if last_completed_ts_dict[symbol] == prev_ts:
                return
            last_completed_ts_dict[symbol] = prev_ts

            time_str = f"{datetime.fromtimestamp(prev_ts / 1000):%Y-%m-%d %H:%M:%S}"
            print(f"\n✅ [{symbol}] 15분봉 완성 ▶️ {time_str} | O:{prev_candle[1]} H:{prev_candle[2]} L:{prev_candle[3]} C:{prev_candle[4]}")

            cci = calculate_cci(candles[:-1], 14)
            adx = calculate_adx(candles[:-1], 5)
            if cci is not None and adx is not None:
                log = f"📊 [{symbol}] CCI(14): {cci:.2f} | ADX(5): {adx:.2f}"
                print(log)
                send_telegram(log)

    # 실시간 출력 (원한다면 생략 가능)
    if last_completed_ts_dict[symbol] != ts:
        print(f"🕒 [{symbol}] {datetime.fromtimestamp(ts/1000):%Y-%m-%d %H:%M:%S} | O:{d[1]} H:{d[2]} L:{d[3]} C:{d[4]} V:{d[5]}")

# WebSocket 루프
async def ws_loop():
    uri = "wss://ws.bitget.com/v2/ws/public"
    try:
        async with websockets.connect(uri, ping_interval=20, ping_timeout=30) as ws:
            args = [{
                "instType": INST_TYPE,
                "channel": CHANNEL,
                "instId": symbol
            } for symbol in SYMBOLS]

            payload = {"op": "subscribe", "args": args}
            print("📤 구독 요청:", json.dumps(payload))
            await ws.send(json.dumps(payload))
            print("✅ WebSocket 연결됨 / 15분봉 구독 시작")

            while True:
                msg = json.loads(await ws.recv())
                if msg.get("event") == "error":
                    print(f"❌ 에러 응답: {msg}")
                    break
                if msg.get("action") in ["snapshot", "update"]:
                    data = msg.get("data", [])
                    if not data:
                        continue
                    d = data[0]
                    inst_id = msg.get("arg", {}).get("instId")
                    if inst_id in SYMBOLS:
                        on_msg(inst_id, d)
    except Exception as e:
        print(f"⚠️ WebSocket 오류: {e}")
        print("🔁 5초 후 재시도")
        await asyncio.sleep(5)
        await ws_loop()

if __name__ == "__main__":
    asyncio.run(ws_loop())

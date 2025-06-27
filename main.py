import asyncio, json, websockets, numpy as np, requests, time
from datetime import datetime, timedelta
from flask import Flask, request
import threading
import pandas as pd

# === 설정 ===
SYMBOLS = {
    "BTCUSDT": {"leverage": 10, "amount": 100, "stop": 0.992, "tp": 1.012, "trail": 0.996},  # 손절 -0.8%, 익절 +1.2%, 트레일링 -0.4%
    "ETHUSDT": {"leverage": 7, "amount": 80,  "stop": 0.99,  "tp": 1.017, "trail": 0.993},   # 손절 -1.0%, 익절 +1.7%, 트레일링 -0.7%
    "SOLUSDT": {"leverage": 5, "amount": 50,  "stop": 0.985, "tp": 1.025, "trail": 0.99},    # 손절 -1.5%, 익절 +2.5%, 트레일링 -1.0%
}
BALANCE = 756.0

# 롱/숏 포지션을 각각 관리 (Bybit 양방향 지원)
positions = {s: {"long": None, "short": None} for s in SYMBOLS}
trade_enabled = {s: True for s in SYMBOLS}
running_flag = True

TELEGRAM_TOKEN = "7776435078:AAFsM_jIDSx1Eij4YJyqJp-zEDtQVtKohnU"
TELEGRAM_CHAT_ID = "1797494660"

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": msg}
        requests.post(url, data=data)
    except: pass

# === 지표 계산 ===
def calc_adx(df, period=5):
    high, low, close = df[:,2], df[:,3], df[:,4]
    if len(close) <= period+2: return np.full(len(close), np.nan)
    plus_dm = np.where(high[1:] - high[:-1] > low[:-1] - low[1:], np.maximum(high[1:] - high[:-1], 0), 0)
    minus_dm = np.where(low[:-1] - low[1:] > high[1:] - high[:-1], np.maximum(low[:-1] - low[1:], 0), 0)
    tr = np.maximum.reduce([high[1:] - low[1:], np.abs(high[1:] - close[:-1]), np.abs(low[1:] - close[:-1])])
    atr = np.convolve(tr, np.ones(period)/period, mode='valid')
    plus_di = 100 * np.convolve(plus_dm, np.ones(period)/period, mode='valid') / atr
    minus_di = 100 * np.convolve(minus_dm, np.ones(period)/period, mode='valid') / atr
    dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = np.convolve(dx, np.ones(period)/period, mode='valid')
    pad = len(close) - len(adx)
    return np.concatenate([np.full(pad, np.nan), adx])

def calc_macd_hist(close):
    if len(close) < 17:
        return np.full(len(close), np.nan)
    ema7 = pd.Series(close).ewm(span=7).mean()
    ema17 = pd.Series(close).ewm(span=17).mean()
    macd = ema7 - ema17
    signal = macd.ewm(span=8).mean()
    hist = macd - signal
    return hist.values

# === 잔고 내에서만 진입 허용 ===
def total_position_amount():
    total = 0
    for sym in SYMBOLS:
        for side in ("long", "short"):
            pos = positions[sym][side]
            if pos:
                total += SYMBOLS[sym]["amount"]
    return total

def can_open_position(symbol):
    remain = BALANCE - total_position_amount()
    return remain >= SYMBOLS[symbol]["amount"]

# === 진입 / 청산 시뮬레이션 ===
def open_position(symbol, side, entry_price):
    conf = SYMBOLS[symbol]
    qty = round(conf["amount"] / entry_price, 6)
    positions[symbol][side] = {
        "side": side, "entry_price": entry_price, "qty": qty,
        "highest": entry_price, "lowest": entry_price
    }
    send_telegram(f"🚀 {symbol} {side.upper()} 진입 @ {entry_price}")

def close_position(symbol, side, price, reason):
    global BALANCE
    pos = positions[symbol][side]
    if not pos: return
    pnl_pct = (price - pos["entry_price"]) / pos["entry_price"]
    if side == "short": pnl_pct *= -1
    profit = SYMBOLS[symbol]["amount"] * pnl_pct
    BALANCE += profit
    positions[symbol][side] = None
    send_telegram(f"💸 {symbol} {side.upper()} 청산 @ {price}\n수익률: {pnl_pct*100:.2f}% / 잔액: ${BALANCE:.2f} / 사유: {reason}")

# === WebSocket & 전략 (Bybit용, 15분봉만) ===
candles_15m = {s: [] for s in SYMBOLS}

def on_msg(symbol, d):
    ts = int(d[0])
    o, h, l, c, v = map(float, d[1:6])
    now = datetime.fromtimestamp(ts/1000) + timedelta(hours=9)
    arr = candles_15m[symbol]
    if arr and arr[-1][0] == ts:
        arr[-1] = [ts, o, h, l, c, v]
    else:
        arr.append([ts, o, h, l, c, v])
        if len(arr) > 150: arr.pop(0)
        analyze(symbol)

def analyze(symbol):
    if not running_flag or not trade_enabled[symbol]: return
    conf = SYMBOLS[symbol]
    df = np.array(candles_15m[symbol])
    if len(df) < 50: return
    close = df[:,4]
    adx = calc_adx(df)
    macd_hist = calc_macd_hist(close)
    if np.isnan(adx[-1]) or np.isnan(macd_hist[-1]) or np.isnan(macd_hist[-2]):
        return

    cond_long = macd_hist[-1] > macd_hist[-2] and adx[-1] > 25
    cond_short = macd_hist[-1] < macd_hist[-2] and adx[-1] > 25

    price = close[-1]

    # 롱 포지션
    pos_long = positions[symbol]["long"]
    if pos_long:
        pos_long["highest"] = max(pos_long["highest"], price)
        if price <= pos_long["entry_price"] * conf["stop"]:
            close_position(symbol, "long", price, f"손절 {100*(conf['stop']-1):.2f}%")
        elif price >= pos_long["entry_price"] * conf["tp"] and price <= pos_long["highest"] * conf["trail"]:
            close_position(symbol, "long", price, f"익절 {100*(conf['tp']-1):.2f}% 도달 후 트레일링")
    elif cond_long and can_open_position(symbol):
        open_position(symbol, "long", price)

    # 숏 포지션
    pos_short = positions[symbol]["short"]
    if pos_short:
        pos_short["lowest"] = min(pos_short["lowest"], price)
        if price >= pos_short["entry_price"] * (2 - conf["stop"]):  # 숏 손절(+)
            close_position(symbol, "short", price, f"손절 {100*(1-conf['stop']):.2f}%")
        elif price <= pos_short["entry_price"] * (2 - conf["tp"]) and price >= pos_short["lowest"] * (2 - conf["trail"]):
            close_position(symbol, "short", price, f"익절 {100*(conf['tp']-1):.2f}% 도달 후 트레일링")
    elif cond_short and can_open_position(symbol):
        open_position(symbol, "short", price)

# === Bybit WebSocket 루프 (15분봉, 양방향 심볼별 구독) ===
async def ws_loop():
    uri = "wss://stream.bybit.com/v5/public/linear"
    while True:
        try:
            print("🔗 WebSocket 연결 시도...")
            async with websockets.connect(
                uri,
                ping_interval=None,     # 바이비트는 서버에서 ping/pong 자체적으로 처리
                ping_timeout=None,
                max_queue=None
            ) as ws:
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
                    raw = await ws.recv()
                    msg = json.loads(raw)
                    print(msg)  # 원본 전체 출력!
                    if isinstance(msg, dict) and msg.get("topic", "").startswith("kline.15.") and msg.get("data"):
                        symbol = msg["topic"].split(".")[-1]
                        on_msg(symbol, msg["data"][0])
        except Exception as e:
            print(f"❌ WebSocket 오류: {e}")
            print("⏳ 3초 후 재연결 시도...")
            await asyncio.sleep(3)


# === 1시간 리포트 ===
def report_telegram():
    while True:
        msg = []
        for sym in SYMBOLS:
            for side in ("long", "short"):
                pos = positions[sym][side]
                if pos:
                    msg.append(f"{sym} | {side.upper()} | 진입가: {pos['entry_price']}")
            if not positions[sym]["long"] and not positions[sym]["short"]:
                msg.append(f"{sym} | 포지션: - | 진입가: -")
        msg.append(f"현재 가상잔고: {BALANCE:.2f}")
        send_telegram("\n".join(msg))
        for _ in range(3600):
            if not running_flag: break
            time.sleep(1)

# === Flask 텔레그램 명령어 제어 ===
app = Flask(__name__)
@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def hook():
    global running_flag
    msg = request.get_json()
    if "message" in msg:
        chat_id = msg["message"]["chat"]["id"]
        text = msg["message"].get("text", "")
        if str(chat_id) != str(TELEGRAM_CHAT_ID): return "no"
        if text == "/시작":
            running_flag = True
            send_telegram("✅ 자동매매 시작")
        elif text == "/중지":
            running_flag = False
            send_telegram("⛔ 자동매매 중지")
        elif text == "/상태":
            msg = f"📊 잔액: ${BALANCE:.2f}\n"
            for sym in SYMBOLS:
                for side in ("long", "short"):
                    pos = positions[sym][side]
                    if pos:
                        msg += f"{sym} {side.upper()} @ {pos['entry_price']}\n"
                if not positions[sym]["long"] and not positions[sym]["short"]:
                    msg += f"{sym} 포지션 없음\n"
            send_telegram(msg)
    return "ok"

# === 실행 ===
if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=5000)).start()
    threading.Thread(target=report_telegram, daemon=True).start()
    asyncio.run(ws_loop())

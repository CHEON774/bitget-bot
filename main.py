import asyncio, json, websockets, numpy as np, requests, time
from datetime import datetime, timedelta
from flask import Flask, request
import threading
import pandas as pd

# === 설정 ===
SYMBOLS = {
    "BTCUSDT": {"leverage": 10, "amount": 100, "stop": 0.992, "tp": 1.012, "trail": 0.996},
    "ETHUSDT": {"leverage": 7,  "amount": 80,  "stop": 0.99,  "tp": 1.017, "trail": 0.993},
    "SOLUSDT": {"leverage": 5,  "amount": 50,  "stop": 0.985, "tp": 1.025, "trail": 0.99},
}
BALANCE = 756.0

positions = {s: {"long": None, "short": None} for s in SYMBOLS}
trade_enabled = {s: True for s in SYMBOLS}
running_flag = True
report_flag = True

trend_30m = {s: "none" for s in SYMBOLS}

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

def calc_ema(arr, period):
    return pd.Series(arr).ewm(span=period).mean().values

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

# === 진입 / 청산 시뮬레이션 (레버리지 실전 적용) ===
def close_position(symbol, side, price, reason):
    global BALANCE
    pos = positions[symbol][side]
    if not pos: return
    entry = pos["entry_price"]
    pnl_pct = (price - entry) / entry
    if side == "short": pnl_pct *= -1
    leverage = SYMBOLS[symbol]["leverage"]
    profit = SYMBOLS[symbol]["amount"] * pnl_pct * leverage
    BALANCE += profit
    positions[symbol][side] = None
    send_telegram(
        f"💸 {symbol} {side.upper()} 청산 @ {price}\n"
        f"수익률: {pnl_pct*100:.2f}% (레버리지 적용시 {pnl_pct*leverage*100:.2f}%)\n"
        f"실현손익: ${profit:.2f}\n"
        f"잔액: ${BALANCE:.2f} / 사유: {reason}"
    )

def open_position(symbol, side, entry_price):
    conf = SYMBOLS[symbol]
    qty = round(conf["amount"] / entry_price * conf["leverage"], 6)
    positions[symbol][side] = {
        "side": side,
        "entry_price": entry_price,
        "qty": qty,
        "highest": entry_price if side == "long" else None,
        "lowest": entry_price if side == "short" else None,
        "trailing_active": False
    }
    send_telegram(f"🚀 {symbol} {side.upper()} 진입 @ {entry_price}")

# === 바이비트 캔들 ===
candles_5m = {s: [] for s in SYMBOLS}
candles_30m = {s: [] for s in SYMBOLS}

def on_msg_5m(symbol, d):
    try:
        ts = int(d['start'])
        o = float(d['open'])
        h = float(d['high'])
        l = float(d['low'])
        c = float(d['close'])
        v = float(d['volume'])
        arr = candles_5m[symbol]
        if arr and arr[-1][0] == ts:
            arr[-1] = [ts, o, h, l, c, v]
        else:
            arr.append([ts, o, h, l, c, v])
            if len(arr) > 200: arr.pop(0)
            analyze(symbol)
    except Exception as e:
        print(f"[{symbol}] 5m 파싱오류: {e}")

def on_msg_30m(symbol, d):
    try:
        ts = int(d['start'])
        o = float(d['open'])
        h = float(d['high'])
        l = float(d['low'])
        c = float(d['close'])
        v = float(d['volume'])
        arr = candles_30m[symbol]
        if arr and arr[-1][0] == ts:
            arr[-1] = [ts, o, h, l, c, v]
        else:
            arr.append([ts, o, h, l, c, v])
            if len(arr) > 100: arr.pop(0)
            analyze_trend_30m(symbol)
    except Exception as e:
        print(f"[{symbol}] 30m 파싱오류: {e}")

def analyze_trend_30m(symbol):
    # 20/50선 골크/데크만 확인
    arr = candles_30m[symbol]
    if len(arr) < 52: return  # 50선, 안정성 위해 52개
    close = np.array(arr)[:,4]
    ema20 = calc_ema(close, 20)
    ema50 = calc_ema(close, 50)
    if ema20[-2] < ema50[-2] and ema20[-1] > ema50[-1]:
        trend_30m[symbol] = "long"
        send_telegram(f"📈 {symbol} 30분봉 골든크로스 추세 감지!")
    elif ema20[-2] > ema50[-2] and ema20[-1] < ema50[-1]:
        trend_30m[symbol] = "short"
        send_telegram(f"📉 {symbol} 30분봉 데드크로스 추세 감지!")
    # 아니면 이전 추세 유지

def analyze(symbol):
    if not running_flag or not trade_enabled[symbol]: return
    conf = SYMBOLS[symbol]
    arr = candles_5m[symbol]
    if len(arr) < 52: return
    close = np.array(arr)[:,4]
    ema20 = calc_ema(close, 20)
    ema50 = calc_ema(close, 50)
    adx = calc_adx(np.array(arr))
    # 골크/데크 + adx
    cond_long = (trend_30m[symbol]=="long" and
                 ema20[-2]<ema50[-2] and ema20[-1]>ema50[-1] and
                 adx[-1]>25)
    cond_short = (trend_30m[symbol]=="short" and
                  ema20[-2]>ema50[-2] and ema20[-1]<ema50[-1] and
                  adx[-1]>25)
    price = close[-1]
    # 롱
    pos_long = positions[symbol]["long"]
    if pos_long:
        if price <= pos_long["entry_price"] * conf["stop"]:
            close_position(symbol, "long", price, f"손절 {100*(conf['stop']-1):.2f}%")
            return
        if not pos_long["trailing_active"] and price >= pos_long["entry_price"] * conf["tp"]:
            pos_long["trailing_active"] = True
            pos_long["highest"] = price
            send_telegram(f"🟢 {symbol} 롱 트레일링 활성화(5m)")
        if pos_long["trailing_active"]:
            pos_long["highest"] = max(pos_long["highest"], price)
            if price <= pos_long["highest"] * conf["trail"]:
                close_position(symbol, "long", price, f"익절 트레일링 도달")
                return
    elif cond_long and can_open_position(symbol):
        open_position(symbol, "long", price)
    # 숏
    pos_short = positions[symbol]["short"]
    if pos_short:
        if price >= pos_short["entry_price"] * (2 - conf["stop"]):
            close_position(symbol, "short", price, f"손절 {100*(1-conf['stop']):.2f}%")
            return
        if not pos_short["trailing_active"] and price <= pos_short["entry_price"] * (2 - conf["tp"]):
            pos_short["trailing_active"] = True
            pos_short["lowest"] = price
            send_telegram(f"🔴 {symbol} 숏 트레일링 활성화(5m)")
        if pos_short["trailing_active"]:
            pos_short["lowest"] = min(pos_short["lowest"], price)
            if price >= pos_short["lowest"] * (2 - conf["trail"]):
                close_position(symbol, "short", price, f"익절 트레일링 도달")
                return
    elif cond_short and can_open_position(symbol):
        open_position(symbol, "short", price)

# === WebSocket 루프(바이비트, 5분/30분 동시 구독) ===
async def ws_loop():
    uri = "wss://stream.bybit.com/v5/public/linear"
    while True:
        try:
            print("🔗 WebSocket 연결 시도...")
            async with websockets.connect(uri, ping_interval=10, ping_timeout=10) as ws:
                print("✅ WebSocket 연결됨")
                sub = {
                    "op": "subscribe",
                    "args": (
                        [f"kline.5.{s}" for s in SYMBOLS] +
                        [f"kline.30.{s}" for s in SYMBOLS]
                    )
                }
                await ws.send(json.dumps(sub))
                while True:
                    raw = await ws.recv()
                    msg = json.loads(raw)
                    topic = msg.get("topic", "")
                    if topic.startswith("kline.5.") and msg.get("data"):
                        symbol = topic.split(".")[-1]
                        on_msg_5m(symbol, msg["data"][0])
                    if topic.startswith("kline.30.") and msg.get("data"):
                        symbol = topic.split(".")[-1]
                        on_msg_30m(symbol, msg["data"][0])
        except Exception as e:
            print(f"❌ WebSocket 오류: {e}")
            print("⏳ 3초 후 재연결 시도...")
            await asyncio.sleep(3)

# === 1시간 리포트 (report_flag 적용, 항상 발송) ===
def report_telegram():
    global report_flag
    while report_flag:
        msg = []
        for sym in SYMBOLS:
            try:
                for side in ("long", "short"):
                    pos = positions[sym][side]
                    if pos:
                        entry = pos['entry_price']
                        price_now = entry
                        if candles_5m.get(sym) and len(candles_5m[sym]) > 0:
                            price_now = candles_5m[sym][-1][4]
                        pnl = (price_now - entry) / entry * 100
                        if side == "short": pnl *= -1
                        leverage = SYMBOLS[sym]["leverage"]
                        trail_state = "O" if pos.get("trailing_active") else "X"
                        msg.append(f"{sym} | {side.upper()} | 진입가: {entry} | 수익률: {pnl:.2f}% | 트레일링:{trail_state}")
                if not positions[sym]["long"] and not positions[sym]["short"]:
                    msg.append(f"{sym} | 포지션: - | 진입가: -")
            except Exception as e:
                msg.append(f"{sym} | 데이터 없음/에러: {e}")
        msg.append(f"현재 가상잔고: {BALANCE:.2f}")
        send_telegram("\n".join(msg))
        for _ in range(3600):
            if not report_flag:
                break
            time.sleep(1)

# === Flask 텔레그램 명령어 제어 ===
app = Flask(__name__)
@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def hook():
    global running_flag, report_flag
    msg = request.get_json()
    if "message" in msg:
        chat_id = msg["message"]["chat"]["id"]
        text = msg["message"].get("text", "")
        if str(chat_id) != str(TELEGRAM_CHAT_ID): return "no"
        if text == "/시작":
            running_flag = True
            report_flag = True
            send_telegram("✅ 자동매매 시작")
        elif text == "/중지":
            running_flag = False
            report_flag = False
            send_telegram("⛔ 자동매매 중지\n모든 포지션 정리중...")
            for sym in SYMBOLS:
                for side in ("long", "short"):
                    pos = positions[sym][side]
                    if pos:
                        price_now = pos["entry_price"]
                        if candles_5m.get(sym) and len(candles_5m[sym]) > 0:
                            price_now = candles_5m[sym][-1][4]
                        close_position(sym, side, price_now, "자동매매 중지(전체 청산)")
            send_telegram("✅ 모든 포지션 정리 완료")
        elif text == "/상태":
            msgtxt = f"📊 잔액: ${BALANCE:.2f}\n"
            for sym in SYMBOLS:
                for side in ("long", "short"):
                    pos = positions[sym][side]
                    if pos:
                        entry = pos['entry_price']
                        price_now = entry
                        if candles_5m.get(sym) and len(candles_5m[sym]) > 0:
                            price_now = candles_5m[sym][-1][4]
                        pnl = (price_now - entry) / entry * 100
                        if side == "short": pnl *= -1
                        leverage = SYMBOLS[sym]["leverage"]
                        trail_state = "O" if pos.get("trailing_active") else "X"
                        msgtxt += f"{sym} {side.upper()} @ {entry} | 수익률: {pnl:.2f}% | 트레일링:{trail_state}\n"
                if not positions[sym]["long"] and not positions[sym]["short"]:
                    msgtxt += f"{sym} 포지션 없음\n"
            send_telegram(msgtxt)
    return "ok"

# === 실행 ===
if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=5000)).start()
    threading.Thread(target=report_telegram, daemon=True).start()
    asyncio.run(ws_loop())


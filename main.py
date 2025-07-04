import asyncio, json, websockets, numpy as np, requests, time
from datetime import datetime
from flask import Flask, request
import threading
import pandas as pd

# === 설정 ===
SYMBOLS = {
    "BTCUSDT": {"leverage": 10, "amount": 100, "stop": 0.992, "tp": 1.012, "trail": 0.996},
    "ETHUSDT": {"leverage": 7,  "amount": 80,  "stop": 0.99,  "tp": 1.017, "trail": 0.993},
    "SOLUSDT": {"leverage": 5,  "amount": 50,  "stop": 0.985, "tp": 1.025, "trail": 0.99},
}
STRATEGIES = {
    "A": "MTF_30m5m_EMA",       # 30m 골크/데크 → 5m 교차 (ADX 없음)
    "B": "MACD7-17-8+ADX5_15m", # 15m MACD+ADX
    "C": "CCI14_15m"            # 15m CCI
}
INIT_BALANCE = 756.0

positions = {stg: {s: {"long": None, "short": None} for s in SYMBOLS} for stg in STRATEGIES}
balances = {stg: INIT_BALANCE for stg in STRATEGIES}
trend_30m = {s: "none" for s in SYMBOLS}  # 전략A용
take_profit_count = {stg: 0 for stg in STRATEGIES}
stop_loss_count = {stg: 0 for stg in STRATEGIES}

running_flag = True
report_flag = True

TELEGRAM_TOKEN = "7776435078:AAFsM_jIDSx1Eij4YJyqJp-zEDtQVtKohnU"
TELEGRAM_CHAT_ID = "1797494660"

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": msg}
        requests.post(url, data=data)
    except Exception as e:
        print("텔레그램 에러:", e)

# === 지표 계산 ===
def calc_ema(arr, period):
    return pd.Series(arr).ewm(span=period).mean().values

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

def calc_cci(df, period=14):
    tp = (df[:,1] + df[:,2] + df[:,3]) / 3
    ma = np.convolve(tp, np.ones(period)/period, mode='valid')
    md = np.array([np.mean(np.abs(tp[i-period+1:i+1] - ma[i-period+1])) for i in range(period-1, len(tp))])
    cci = (tp[period-1:] - ma) / (0.015 * md)
    return np.concatenate([np.full(period-1, np.nan), cci])

# === 잔고 내에서만 진입 허용 ===
def total_position_amount(positions, stg):
    total = 0
    for sym in SYMBOLS:
        for side in ("long", "short"):
            pos = positions[stg][sym][side]
            if pos:
                total += SYMBOLS[sym]["amount"]
    return total

def can_open_position(positions, balances, stg, symbol):
    remain = balances[stg] - total_position_amount(positions, stg)
    return remain >= SYMBOLS[symbol]["amount"]

# === 진입 / 청산 시뮬레이션 (레버리지 실전 적용, 익절/손절 카운팅) ===
def close_position(stg, symbol, side, price, reason, pnl_force=None):
    global balances, positions, take_profit_count, stop_loss_count
    pos = positions[stg][symbol][side]
    if not pos: return
    entry = pos["entry_price"]
    pnl_pct = (price - entry) / entry
    if side == "short": pnl_pct *= -1
    leverage = SYMBOLS[symbol]["leverage"]
    profit = SYMBOLS[symbol]["amount"] * pnl_pct * leverage
    balances[stg] += profit
    positions[stg][symbol][side] = None
    # 손절/익절 카운트 (pnl_force가 있으면 강제)
    is_tp = pnl_force=="tp" or (pnl_force is None and pnl_pct > 0)
    is_sl = pnl_force=="sl" or (pnl_force is None and pnl_pct < 0)
    if is_tp:
        take_profit_count[stg] += 1
    if is_sl:
        stop_loss_count[stg] += 1
    send_telegram(
        f"[전략{stg}] {symbol} {side.upper()} 청산 @ {price}\n"
        f"수익률: {pnl_pct*100:.2f}% (레버리지 적용시 {pnl_pct*leverage*100:.2f}%)\n"
        f"실현손익: ${profit:.2f}\n"
        f"잔액: ${balances[stg]:.2f} / 사유: {reason}"
    )

def open_position(stg, symbol, side, entry_price):
    conf = SYMBOLS[symbol]
    qty = round(conf["amount"] / entry_price * conf["leverage"], 6)
    positions[stg][symbol][side] = {
        "side": side,
        "entry_price": entry_price,
        "qty": qty,
        "highest": entry_price if side == "long" else None,
        "lowest": entry_price if side == "short" else None,
        "trailing_active": False
    }
    send_telegram(f"[전략{stg}] 🚀 {symbol} {side.upper()} 진입 @ {entry_price}")

# === 캔들 관리 ===
candles_5m = {s: [] for s in SYMBOLS}
candles_15m = {s: [] for s in SYMBOLS}
candles_30m = {s: [] for s in SYMBOLS}

def on_msg_5m(symbol, d):
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
        analyze_A(symbol)

def on_msg_15m(symbol, d):
    ts = int(d['start'])
    o = float(d['open'])
    h = float(d['high'])
    l = float(d['low'])
    c = float(d['close'])
    v = float(d['volume'])
    arr = candles_15m[symbol]
    if arr and arr[-1][0] == ts:
        arr[-1] = [ts, o, h, l, c, v]
    else:
        arr.append([ts, o, h, l, c, v])
        if len(arr) > 200: arr.pop(0)
        analyze_B(symbol)
        analyze_C(symbol)

def on_msg_30m(symbol, d):
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

def analyze_trend_30m(symbol):
    arr = candles_30m[symbol]
    if len(arr) < 52: return
    close = np.array(arr)[:,4]
    ema20 = calc_ema(close, 20)
    ema50 = calc_ema(close, 50)
    if ema20[-2] < ema50[-2] and ema20[-1] > ema50[-1]:
        trend_30m[symbol] = "long"
        send_telegram(f"[전략A] {symbol} 30분봉 골든크로스!")
    elif ema20[-2] > ema50[-2] and ema20[-1] < ema50[-1]:
        trend_30m[symbol] = "short"
        send_telegram(f"[전략A] {symbol} 30분봉 데드크로스!")

# === 각 전략별 매매 ===
def analyze_A(symbol):
    if not running_flag: return
    arr = candles_5m[symbol]
    if len(arr) < 52: return
    close = np.array(arr)[:,4]
    ema20 = calc_ema(close, 20)
    ema50 = calc_ema(close, 50)
    # ADX 없이 5분봉 교차 신호만!
    cond_long = (trend_30m[symbol]=="long" and
                 ema20[-2]<ema50[-2] and ema20[-1]>ema50[-1])
    cond_short = (trend_30m[symbol]=="short" and
                  ema20[-2]>ema50[-2] and ema20[-1]<ema50[-1])
    price = close[-1]
    pos_long = positions["A"][symbol]["long"]
    pos_short = positions["A"][symbol]["short"]
    conf = SYMBOLS[symbol]
    # 롱
    if pos_long:
        if price <= pos_long["entry_price"] * conf["stop"]:
            close_position("A", symbol, "long", price, "손절", pnl_force="sl")
            return
        if not pos_long["trailing_active"] and price >= pos_long["entry_price"] * conf["tp"]:
            pos_long["trailing_active"] = True
            pos_long["highest"] = price
            send_telegram(f"[전략A] {symbol} 롱 트레일링 활성화(5m)")
        if pos_long["trailing_active"]:
            pos_long["highest"] = max(pos_long["highest"], price)
            if price <= pos_long["highest"] * conf["trail"]:
                close_position("A", symbol, "long", price, "익절 트레일링", pnl_force="tp")
                return
    elif cond_long and can_open_position(positions, balances, "A", symbol):
        open_position("A", symbol, "long", price)
    # 숏
    if pos_short:
        if price >= pos_short["entry_price"] * (2 - conf["stop"]):
            close_position("A", symbol, "short", price, "손절", pnl_force="sl")
            return
        if not pos_short["trailing_active"] and price <= pos_short["entry_price"] * (2 - conf["tp"]):
            pos_short["trailing_active"] = True
            pos_short["lowest"] = price
            send_telegram(f"[전략A] {symbol} 숏 트레일링 활성화(5m)")
        if pos_short["trailing_active"]:
            pos_short["lowest"] = min(pos_short["lowest"], price)
            if price >= pos_short["lowest"] * (2 - conf["trail"]):
                close_position("A", symbol, "short", price, "익절 트레일링", pnl_force="tp")
                return
    elif cond_short and can_open_position(positions, balances, "A", symbol):
        open_position("A", symbol, "short", price)

def analyze_B(symbol):
    if not running_flag: return
    arr = candles_15m[symbol]
    if len(arr) < 50: return
    close = np.array(arr)[:,4]
    macd_hist = calc_macd_hist(close)
    adx = calc_adx(np.array(arr))
    cond_long = macd_hist[-2] < 0 and macd_hist[-1] > 0 and adx[-1] > 25
    cond_short = macd_hist[-2] > 0 and macd_hist[-1] < 0 and adx[-1] > 25
    price = close[-1]
    pos_long = positions["B"][symbol]["long"]
    pos_short = positions["B"][symbol]["short"]
    conf = SYMBOLS[symbol]
    # 롱
    if pos_long:
        if price <= pos_long["entry_price"] * conf["stop"]:
            close_position("B", symbol, "long", price, "손절", pnl_force="sl")
            return
        if not pos_long["trailing_active"] and price >= pos_long["entry_price"] * conf["tp"]:
            pos_long["trailing_active"] = True
            pos_long["highest"] = price
            send_telegram(f"[전략B] {symbol} 롱 트레일링 활성화(15m)")
        if pos_long["trailing_active"]:
            pos_long["highest"] = max(pos_long["highest"], price)
            if price <= pos_long["highest"] * conf["trail"]:
                close_position("B", symbol, "long", price, "익절 트레일링", pnl_force="tp")
                return
    elif cond_long and can_open_position(positions, balances, "B", symbol):
        open_position("B", symbol, "long", price)
    # 숏
    if pos_short:
        if price >= pos_short["entry_price"] * (2 - conf["stop"]):
            close_position("B", symbol, "short", price, "손절", pnl_force="sl")
            return
        if not pos_short["trailing_active"] and price <= pos_short["entry_price"] * (2 - conf["tp"]):
            pos_short["trailing_active"] = True
            pos_short["lowest"] = price
            send_telegram(f"[전략B] {symbol} 숏 트레일링 활성화(15m)")
        if pos_short["trailing_active"]:
            pos_short["lowest"] = min(pos_short["lowest"], price)
            if price >= pos_short["lowest"] * (2 - conf["trail"]):
                close_position("B", symbol, "short", price, "익절 트레일링", pnl_force="tp")
                return
    elif cond_short and can_open_position(positions, balances, "B", symbol):
        open_position("B", symbol, "short", price)

def analyze_C(symbol):
    if not running_flag: return
    arr = candles_15m[symbol]
    if len(arr) < 20: return
    cci = calc_cci(np.array(arr), 14)
    price = np.array(arr)[:,4][-1]
    cond_long = cci[-1] < -150
    cond_short = cci[-1] > 150
    pos_long = positions["C"][symbol]["long"]
    pos_short = positions["C"][symbol]["short"]
    conf = SYMBOLS[symbol]
    # 롱
    if pos_long:
        if price <= pos_long["entry_price"] * conf["stop"]:
            close_position("C", symbol, "long", price, "손절", pnl_force="sl")
            return
        if not pos_long["trailing_active"] and price >= pos_long["entry_price"] * conf["tp"]:
            pos_long["trailing_active"] = True
            pos_long["highest"] = price
            send_telegram(f"[전략C] {symbol} 롱 트레일링 활성화(15m)")
        if pos_long["trailing_active"]:
            pos_long["highest"] = max(pos_long["highest"], price)
            if price <= pos_long["highest"] * conf["trail"]:
                close_position("C", symbol, "long", price, "익절 트레일링", pnl_force="tp")
                return
    elif cond_long and can_open_position(positions, balances, "C", symbol):
        open_position("C", symbol, "long", price)
    # 숏
    if pos_short:
        if price >= pos_short["entry_price"] * (2 - conf["stop"]):
            close_position("C", symbol, "short", price, "손절", pnl_force="sl")
            return
        if not pos_short["trailing_active"] and price <= pos_short["entry_price"] * (2 - conf["tp"]):
            pos_short["trailing_active"] = True
            pos_short["lowest"] = price
            send_telegram(f"[전략C] {symbol} 숏 트레일링 활성화(15m)")
        if pos_short["trailing_active"]:
            pos_short["lowest"] = min(pos_short["lowest"], price)
            if price >= pos_short["lowest"] * (2 - conf["trail"]):
                close_position("C", symbol, "short", price, "익절 트레일링", pnl_force="tp")
                return
    elif cond_short and can_open_position(positions, balances, "C", symbol):
        open_position("C", symbol, "short", price)

# === WebSocket 루프(바이비트, 5m/15m/30m 동시 구독) ===
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
                        [f"kline.15.{s}" for s in SYMBOLS] +
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
                    if topic.startswith("kline.15.") and msg.get("data"):
                        symbol = topic.split(".")[-1]
                        on_msg_15m(symbol, msg["data"][0])
                    if topic.startswith("kline.30.") and msg.get("data"):
                        symbol = topic.split(".")[-1]
                        on_msg_30m(symbol, msg["data"][0])
        except Exception as e:
            print(f"❌ WebSocket 오류: {e}")
            print("⏳ 3초 후 재연결 시도...")
            await asyncio.sleep(3)

# === 1시간 리포트 (전략별 잔고/익절/손절 카운트 포함) ===
def report_telegram():
    global report_flag
    while report_flag:
        msg = []
        for stg, desc in STRATEGIES.items():
            msg.append(f"전략{stg}({desc})")
            for sym in SYMBOLS:
                for side in ("long", "short"):
                    pos = positions[stg][sym][side]
                    if pos:
                        entry = pos['entry_price']
                        price_now = entry
                        # 5분/15분/30분봉 중 5,15 우선
                        arr = candles_5m.get(sym) if stg=="A" else candles_15m.get(sym)
                        if arr and len(arr)>0:
                            price_now = arr[-1][4]
                        pnl = (price_now - entry) / entry * 100
                        if side == "short": pnl *= -1
                        trail_state = "O" if pos.get("trailing_active") else "X"
                        msg.append(f"{sym} | {side.upper()} | 진입가: {entry} | 수익률: {pnl:.2f}% | 트레일링:{trail_state}")
                if not positions[stg][sym]["long"] and not positions[stg][sym]["short"]:
                    msg.append(f"{sym} | 포지션: - | 진입가: -")
            msg.append(f"현재 가상잔고: {balances[stg]:.2f}")
            msg.append(f"누적 익절: {take_profit_count[stg]}회 / 누적 손절: {stop_loss_count[stg]}회\n")
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
            for stg in STRATEGIES:
                for sym in SYMBOLS:
                    for side in ("long", "short"):
                        pos = positions[stg][sym][side]
                        if pos:
                            arr = candles_5m.get(sym) if stg=="A" else candles_15m.get(sym)
                            price_now = pos["entry_price"]
                            if arr and len(arr)>0:
                                price_now = arr[-1][4]
                            close_position(stg, sym, side, price_now, "자동매매 중지(전체 청산)")
            send_telegram("✅ 모든 포지션 정리 완료")
        elif text == "/상태":
            msgtxt = ""
            for stg, desc in STRATEGIES.items():
                msgtxt += f"전략{stg}({desc})\n"
                for sym in SYMBOLS:
                    for side in ("long", "short"):
                        pos = positions[stg][sym][side]
                        if pos:
                            entry = pos['entry_price']
                            arr = candles_5m.get(sym) if stg=="A" else candles_15m.get(sym)
                            price_now = entry
                            if arr and len(arr)>0:
                                price_now = arr[-1][4]
                            pnl = (price_now - entry) / entry * 100
                            if side == "short": pnl *= -1
                            trail_state = "O" if pos.get("trailing_active") else "X"
                            msgtxt += f"{sym} {side.upper()} @ {entry} | 수익률: {pnl:.2f}% | 트레일링:{trail_state}\n"
                    if not positions[stg][sym]["long"] and not positions[stg][sym]["short"]:
                        msgtxt += f"{sym} 포지션 없음\n"
                msgtxt += f"현재 가상잔고: {balances[stg]:.2f}\n"
                msgtxt += f"누적 익절: {take_profit_count[stg]}회 / 누적 손절: {stop_loss_count[stg]}회\n\n"
            send_telegram(msgtxt)
    return "ok"

# === 실행 ===
if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=5000)).start()
    threading.Thread(target=report_telegram, daemon=True).start()
    asyncio.run(ws_loop())


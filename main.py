import asyncio, json, websockets, requests, numpy as np, pandas as pd, time
from datetime import datetime
from flask import Flask, request
import threading

SYMBOLS = {
    "BTCUSDT": {"leverage": 10, "amount": 100},
    "ETHUSDT": {"leverage": 7,  "amount": 70},
    "SOLUSDT": {"leverage": 5,  "amount": 50},
}
STOP = 0.992   # -0.8%
TP   = 1.022   # +2.2%
TRAIL= 0.99    # 1.0% 트레일링
INIT_BALANCE = 756.0

STRATEGY_LABELS = {
    "A": "전략A (MACD+ADX)",
    "B": "전략B (MACD+임계치)",
    "C": "전략C (MACD+50일선)",
    "D": "전략D (MACD+ADX+임계치)"
}

positions = {k: {s: {'long': None, 'short': None} for s in SYMBOLS} for k in ['A','B','C','D']}
balance = {k: INIT_BALANCE for k in ['A','B','C','D']}
tp_count = {k: 0 for k in ['A','B','C','D']}
sl_count = {k: 0 for k in ['A','B','C','D']}

running_flag = True
report_flag = True

TELEGRAM_TOKEN = "7776435078:AAFsM_jIDSx1Eij4YJyqJp-zEDtQVtKohnU"
TELEGRAM_CHAT_ID = "1797494660"

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": msg}
        requests.post(url, data=data)
    except: pass

def fetch_bybit_candles(symbol, interval, limit=100):
    url = "https://api.bybit.com/v5/market/kline"
    params = {
        "category": "linear",
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        arr = []
        if resp.status_code == 200:
            js = resp.json()
            for d in js['result']['list'][::-1]:
                arr.append([
                    int(d[0]),        # timestamp
                    float(d[1]),      # open
                    float(d[2]),      # high
                    float(d[3]),      # low
                    float(d[4]),      # close
                    float(d[5]),      # volume
                ])
        return arr
    except Exception as e:
        print("캔들 fetch 실패:", e)
        return []

def calc_macd(close, fast=7, slow=17, signal=8):
    ema_fast = pd.Series(close).ewm(span=fast).mean()
    ema_slow = pd.Series(close).ewm(span=slow).mean()
    macd = ema_fast - ema_slow
    signal_line = macd.ewm(span=signal).mean()
    hist = macd - signal_line
    return macd.values, signal_line.values, hist.values

def calc_adx(df, period=5):
    high, low, close = df[:,2], df[:,3], df[:,4]
    plus_dm = np.where(high[1:] - high[:-1] > low[:-1] - low[1:], np.maximum(high[1:] - high[:-1], 0), 0)
    minus_dm = np.where(low[:-1] - low[1:] > high[1:] - high[:-1], np.maximum(low[:-1] - low[1:], 0), 0)
    tr = np.maximum.reduce([high[1:] - low[1:], np.abs(high[1:] - close[:-1]), np.abs(low[1:] - close[:-1])])
    atr = pd.Series(tr).rolling(period).mean().values
    plus_di = 100 * pd.Series(plus_dm).rolling(period).mean() / atr
    minus_di = 100 * pd.Series(minus_dm).rolling(period).mean() / atr
    dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = pd.Series(dx).rolling(period).mean().values
    pad = len(close) - len(adx)
    return np.concatenate([np.full(pad, np.nan), adx])

def calc_ma(close, period=50):
    return pd.Series(close).rolling(period).mean().values

candles = {s: fetch_bybit_candles(s, "15", limit=100) for s in SYMBOLS}

def open_position(strategy, symbol, side, entry):
    conf = SYMBOLS[symbol]
    qty = round(conf["amount"] / entry * conf["leverage"], 6)
    positions[strategy][symbol][side] = {
        "entry": entry, "qty": qty, "peak": entry, "active_trail": False
    }
    send_telegram(f"🚀 [{STRATEGY_LABELS[strategy]}] {symbol} {side.upper()} 진입 @ {entry}")

def close_position(strategy, symbol, side, price, reason, force=None):
    global positions, balance, tp_count, sl_count
    pos = positions[strategy][symbol][side]
    if not pos: return
    entry = pos["entry"]
    pnl_pct = (price - entry) / entry
    if side == "short": pnl_pct *= -1
    lev = SYMBOLS[symbol]["leverage"]
    real_pnl = pnl_pct * lev * 100
    net_real_pnl = real_pnl  # 수수료 없음!
    profit = SYMBOLS[symbol]["amount"] * net_real_pnl / 100
    balance[strategy] += profit
    positions[strategy][symbol][side] = None
    tp_flag = force=="tp" or (force is None and net_real_pnl > 0)
    sl_flag = force=="sl" or (force is None and net_real_pnl < 0)
    if tp_flag: tp_count[strategy] += 1
    if sl_flag: sl_count[strategy] += 1
    send_telegram(
        f"💸 [{STRATEGY_LABELS[strategy]}] {symbol} {side.upper()} 청산 @ {price}\n"
        f"순수익률: {net_real_pnl:.2f}% (수수료 없음)\n"
        f"잔고: ${balance[strategy]:.2f} / 사유: {reason}"
    )

def analyze_A(symbol):
    arr = np.array(candles[symbol])
    if len(arr) < 20: return
    close = arr[:,4]
    _, _, hist = calc_macd(close)
    adx = calc_adx(arr, 5)
    price = close[-1]
    if positions["A"][symbol]['long'] is None:
        if hist[-2] < 0 and hist[-1] > 0 and adx[-1] > 25:
            open_position("A", symbol, "long", price)
    if positions["A"][symbol]['short'] is None:
        if hist[-2] > 0 and hist[-1] < 0 and adx[-1] > 25:
            open_position("A", symbol, "short", price)
    for side in ['long', 'short']:
        pos = positions["A"][symbol][side]
        if not pos: continue
        entry = pos["entry"]
        pnl = (price - entry) / entry
        if side == "short": pnl *= -1
        lev = SYMBOLS[symbol]["leverage"]
        real_pnl = pnl * lev * 100
        net_real_pnl = real_pnl  # 수수료 없음
        if net_real_pnl <= -(1-STOP)*100:
            close_position("A", symbol, side, price, "손절", force="sl")
            continue
        if not pos["active_trail"] and net_real_pnl >= (TP-1)*100:
            pos["active_trail"] = True
            pos["peak"] = price
            send_telegram(f"[{STRATEGY_LABELS['A']}] {symbol} {side.upper()} 트레일링 활성화")
        if pos["active_trail"]:
            if side == "long":
                pos["peak"] = max(pos["peak"], price)
                if price <= pos["peak"] * TRAIL:
                    close_position("A", symbol, side, price, "익절(트레일링)", force="tp")
            else:
                pos["peak"] = min(pos["peak"], price)
                if price >= pos["peak"] / TRAIL:
                    close_position("A", symbol, side, price, "익절(트레일링)", force="tp")

def analyze_B(symbol):
    arr = np.array(candles[symbol])
    if len(arr) < 20: return
    close = arr[:,4]
    _, _, hist = calc_macd(close)
    price = close[-1]
    if positions["B"][symbol]['long'] is None:
        if hist[-2] < 0 and hist[-1] > 0 and abs(hist[-1]) > 0.003:
            open_position("B", symbol, "long", price)
    if positions["B"][symbol]['short'] is None:
        if hist[-2] > 0 and hist[-1] < 0 and abs(hist[-1]) > 0.003:
            open_position("B", symbol, "short", price)
    for side in ['long', 'short']:
        pos = positions["B"][symbol][side]
        if not pos: continue
        entry = pos["entry"]
        pnl = (price - entry) / entry
        if side == "short": pnl *= -1
        lev = SYMBOLS[symbol]["leverage"]
        real_pnl = pnl * lev * 100
        net_real_pnl = real_pnl  # 수수료 없음
        if net_real_pnl <= -(1-STOP)*100:
            close_position("B", symbol, side, price, "손절", force="sl")
            continue
        if not pos["active_trail"] and net_real_pnl >= (TP-1)*100:
            pos["active_trail"] = True
            pos["peak"] = price
            send_telegram(f"[{STRATEGY_LABELS['B']}] {symbol} {side.upper()} 트레일링 활성화")
        if pos["active_trail"]:
            if side == "long":
                pos["peak"] = max(pos["peak"], price)
                if price <= pos["peak"] * TRAIL:
                    close_position("B", symbol, side, price, "익절(트레일링)", force="tp")
            else:
                pos["peak"] = min(pos["peak"], price)
                if price >= pos["peak"] / TRAIL:
                    close_position("B", symbol, side, price, "익절(트레일링)", force="tp")

def analyze_C(symbol):
    arr = np.array(candles[symbol])
    if len(arr) < 51: return
    close = arr[:,4]
    _, _, hist = calc_macd(close)
    ma50 = calc_ma(close, 50)
    price = close[-1]
    if positions["C"][symbol]['long'] is None:
        if hist[-2] < 0 and hist[-1] > 0 and price > ma50[-1]:
            open_position("C", symbol, "long", price)
    if positions["C"][symbol]['short'] is None:
        if hist[-2] > 0 and hist[-1] < 0 and price < ma50[-1]:
            open_position("C", symbol, "short", price)
    for side in ['long', 'short']:
        pos = positions["C"][symbol][side]
        if not pos: continue
        entry = pos["entry"]
        pnl = (price - entry) / entry
        if side == "short": pnl *= -1
        lev = SYMBOLS[symbol]["leverage"]
        real_pnl = pnl * lev * 100
        net_real_pnl = real_pnl  # 수수료 없음
        if net_real_pnl <= -(1-STOP)*100:
            close_position("C", symbol, side, price, "손절", force="sl")
            continue
        if not pos["active_trail"] and net_real_pnl >= (TP-1)*100:
            pos["active_trail"] = True
            pos["peak"] = price
            send_telegram(f"[{STRATEGY_LABELS['C']}] {symbol} {side.upper()} 트레일링 활성화")
        if pos["active_trail"]:
            if side == "long":
                pos["peak"] = max(pos["peak"], price)
                if price <= pos["peak"] * TRAIL:
                    close_position("C", symbol, side, price, "익절(트레일링)", force="tp")
            else:
                pos["peak"] = min(pos["peak"], price)
                if price >= pos["peak"] / TRAIL:
                    close_position("C", symbol, side, price, "익절(트레일링)", force="tp")

def analyze_D(symbol):
    arr = np.array(candles[symbol])
    if len(arr) < 20: return
    close = arr[:,4]
    _, _, hist = calc_macd(close)
    adx = calc_adx(arr, 5)
    price = close[-1]
    if positions["D"][symbol]['long'] is None:
        if hist[-2] < 0 and hist[-1] > 0 and adx[-1] > 25 and abs(hist[-1]) > 0.003:
            open_position("D", symbol, "long", price)
    if positions["D"][symbol]['short'] is None:
        if hist[-2] > 0 and hist[-1] < 0 and adx[-1] > 25 and abs(hist[-1]) > 0.003:
            open_position("D", symbol, "short", price)
    for side in ['long', 'short']:
        pos = positions["D"][symbol][side]
        if not pos: continue
        entry = pos["entry"]
        pnl = (price - entry) / entry
        if side == "short": pnl *= -1
        lev = SYMBOLS[symbol]["leverage"]
        real_pnl = pnl * lev * 100
        net_real_pnl = real_pnl  # 수수료 없음
        if net_real_pnl <= -(1-STOP)*100:
            close_position("D", symbol, side, price, "손절", force="sl")
            continue
        if not pos["active_trail"] and net_real_pnl >= (TP-1)*100:
            pos["active_trail"] = True
            pos["peak"] = price
            send_telegram(f"[{STRATEGY_LABELS['D']}] {symbol} {side.upper()} 트레일링 활성화")
        if pos["active_trail"]:
            if side == "long":
                pos["peak"] = max(pos["peak"], price)
                if price <= pos["peak"] * TRAIL:
                    close_position("D", symbol, side, price, "익절(트레일링)", force="tp")
            else:
                pos["peak"] = min(pos["peak"], price)
                if price >= pos["peak"] / TRAIL:
                    close_position("D", symbol, side, price, "익절(트레일링)", force="tp")

async def ws_loop():
    uri = "wss://stream.bybit.com/v5/public/linear"
    subscribe = {
        "op": "subscribe",
        "args": [f"kline.15.{s}" for s in SYMBOLS]
    }
    while True:
        try:
            async with websockets.connect(uri, ping_interval=None, ping_timeout=None) as ws:
                await ws.send(json.dumps(subscribe))
                print("✅ WebSocket 연결됨 (Bybit 15m)")
                last_ping = time.time()
                while True:
                    if time.time() - last_ping > 30:
                        try:
                            await ws.ping()
                            last_ping = time.time()
                        except: break
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=35)
                        msg = json.loads(msg)
                        if msg.get("topic", "").startswith("kline.15."):
                            s = msg["topic"].split(".")[2]
                            d = msg["data"][0]
                            ts = int(d['start'])
                            o = float(d['open'])
                            h = float(d['high'])
                            l = float(d['low'])
                            c = float(d['close'])
                            v = float(d['volume'])
                            arr = candles[s]
                            if arr and arr[-1][0] == ts:
                                arr[-1] = [ts,o,h,l,c,v]
                            else:
                                arr.append([ts,o,h,l,c,v])
                                if len(arr) > 200: arr.pop(0)
                                analyze_A(s)
                                analyze_B(s)
                                analyze_C(s)
                                analyze_D(s)
                    except asyncio.TimeoutError:
                        try:
                            await ws.ping()
                            last_ping = time.time()
                        except: break
        except Exception as e:
            print(f"❌ WebSocket 오류: {e}")
            print("⏳ 3초 후 재연결 시도...")
            await asyncio.sleep(3)

def report_telegram():
    while report_flag:
        msg = []
        for k in ['A','B','C','D']:
            msg.append(STRATEGY_LABELS[k])
            for s in SYMBOLS:
                for side in ['long','short']:
                    pos = positions[k][s][side]
                    if pos:
                        entry = pos['entry']
                        arr = candles.get(s)
                        price_now = entry
                        if arr and len(arr)>0:
                            price_now = arr[-1][4]
                        pnl = (price_now-entry)/entry*100
                        if side=="short": pnl *= -1
                        lev = SYMBOLS[s]["leverage"]
                        real_pnl = pnl * lev * 100
                        net_real_pnl = real_pnl  # 수수료 없음
                        trail = "O" if pos.get("active_trail") else "X"
                        msg.append(f"{s} {side}: 진입가 {entry} | 순수익률 {net_real_pnl:.2f}% | 트레일:{trail}")
                    else:
                        msg.append(f"{s} {side}: 포지션 없음")
            msg.append(f"현재 가상잔고: {balance[k]:.2f}")
            msg.append(f"누적 익절: {tp_count[k]}회 / 누적 손절: {sl_count[k]}회\n")
        send_telegram('\n'.join(msg))
        for _ in range(3600):
            if not report_flag: break
            time.sleep(1)

# Flask webhook (/상태, /중지 등)
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
            running_flag = True; report_flag = True
            send_telegram("✅ 자동매매 시작")
        elif text == "/중지":
            running_flag = False; report_flag = False
            # === 모든 포지션 강제 청산 ===
            for k in ['A','B','C','D']:
                for s in SYMBOLS:
                    for side in ['long', 'short']:
                        pos = positions[k][s][side]
                        if pos:
                            price_now = pos['entry']
                            arr = candles.get(s)
                            if arr and len(arr) > 0:
                                price_now = arr[-1][4]
                            close_position(k, s, side, price_now, "중지명령", force="sl")
            send_telegram("⛔ 자동매매 중지 및 전 포지션 청산")
        elif text == "/상태":
            msgtxt = []
            for k in ['A','B','C','D']:
                msgtxt.append(STRATEGY_LABELS[k])
                for s in SYMBOLS:
                    for side in ['long','short']:
                        pos = positions[k][s][side]
                        if pos:
                            entry = pos['entry']
                            arr = candles.get(s)
                            price_now = entry
                            if arr and len(arr)>0:
                                price_now = arr[-1][4]
                            pnl = (price_now-entry)/entry*100
                            if side=="short": pnl *= -1
                            lev = SYMBOLS[s]["leverage"]
                            real_pnl = pnl * lev * 100
                            net_real_pnl = real_pnl  # 수수료 없음
                            trail = "O" if pos.get("active_trail") else "X"
                            msgtxt.append(f"{s} {side}: 진입가 {entry} | 순수익률 {net_real_pnl:.2f}% | 트레일:{trail}")
                        else:
                            msgtxt.append(f"{s} {side}: 포지션 없음")
                msgtxt.append(f"현재 가상잔고: {balance[k]:.2f}")
                msgtxt.append(f"누적 익절: {tp_count[k]}회 / 누적 손절: {sl_count[k]}회\n")
            send_telegram('\n'.join(msgtxt))
    return "ok"

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=5000)).start()
    threading.Thread(target=report_telegram, daemon=True).start()
    asyncio.run(ws_loop())

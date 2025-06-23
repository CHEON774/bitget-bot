import asyncio, json, websockets, numpy as np, requests, time
from datetime import datetime, timedelta
from flask import Flask, request
import threading
import pandas as pd

# === 설정 ===
SYMBOLS = {
    "BTCUSDT": {"leverage": 10, "amount": 150},
    "ETHUSDT": {"leverage": 7, "amount": 120},
    "SOLUSDT": {"leverage": 5, "amount": 100},
}
BALANCE = 756.0
positions = {s: None for s in SYMBOLS}
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
def calc_cci(df, period=14):
    tp = (df[:,1] + df[:,2] + df[:,3]) / 3
    if len(tp) < period: return np.full(len(tp), np.nan)
    ma = np.convolve(tp, np.ones(period)/period, mode='valid')
    md = np.array([np.mean(np.abs(tp[i-period+1:i+1] - ma[i-period+1])) for i in range(period-1, len(tp))])
    cci = (tp[period-1:] - ma) / (0.015 * md)
    return np.concatenate([np.full(period-1, np.nan), cci])

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
    if len(close) < 26:
        return np.full(len(close), np.nan)
    ema12 = pd.Series(close).ewm(span=12).mean()
    ema26 = pd.Series(close).ewm(span=26).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9).mean()
    hist = macd - signal
    return hist.values

# === 진입 / 청산 시뮬레이션 ===
def open_position(symbol, side, entry_price):
    conf = SYMBOLS[symbol]
    qty = round(conf["amount"] / entry_price, 6)
    positions[symbol] = {
        "side": side, "entry_price": entry_price, "qty": qty,
        "highest": entry_price, "lowest": entry_price
    }
    send_telegram(f"🚀 {symbol} {side.upper()} 진입 @ {entry_price}")

def close_position(symbol, price, reason):
    global BALANCE
    pos = positions[symbol]
    if not pos: return
    side = pos["side"]
    pnl_pct = (price - pos["entry_price"]) / pos["entry_price"]
    if side == "short": pnl_pct *= -1
    profit = SYMBOLS[symbol]["amount"] * pnl_pct
    BALANCE += profit
    positions[symbol] = None
    send_telegram(f"💸 {symbol} 포지션 청산 @ {price}\n수익률: {pnl_pct*100:.2f}% / 잔액: ${BALANCE:.2f} / 사유: {reason}")

# === WebSocket & 전략 (자동 재연결 포함, 15분/30분 동시 수집) ===
candles_15m = {s: [] for s in SYMBOLS}
candles_30m = {s: [] for s in SYMBOLS}

def on_msg(symbol, d, tf):
    ts = int(d[0])
    o, h, l, c, v = map(float, d[1:6])
    now = datetime.fromtimestamp(ts/1000) + timedelta(hours=9)
    arr = candles_15m[symbol] if tf=="15m" else candles_30m[symbol]
    if arr and arr[-1][0] == ts:
        arr[-1] = [ts, o, h, l, c, v]
    else:
        arr.append([ts, o, h, l, c, v])
        if len(arr) > 150: arr.pop(0)
    if tf == "15m": analyze(symbol)  # 15분봉 완성 때마다 분석

def analyze(symbol):
    if not running_flag or not trade_enabled[symbol]: return
    df15 = np.array(candles_15m[symbol])
    df30 = np.array(candles_30m[symbol])
    if len(df15) < 50 or len(df30) < 50: return
    close15 = df15[:,4]
    close30 = df30[:,4]
    # 15분, 30분봉 각각 퀀트 신호 계산
    cci15 = calc_cci(df15)
    adx15 = calc_adx(df15)
    macd15 = calc_macd_hist(close15)
    cci30 = calc_cci(df30)
    adx30 = calc_adx(df30)
    macd30 = calc_macd_hist(close30)
    # 15분 신호
    cond_long_15 = cci15[-1] < -100 and adx15[-1] > 25 and macd15[-1] > macd15[-2]
    cond_short_15 = cci15[-1] > 100 and adx15[-1] > 25 and macd15[-1] < macd15[-2]
    # 30분 신호
    cond_long_30 = cci30[-1] < -100 and adx30[-1] > 25 and macd30[-1] > macd30[-2]
    cond_short_30 = cci30[-1] > 100 and adx30[-1] > 25 and macd30[-1] < macd30[-2]

    price = close15[-1]
    pos = positions[symbol]
    # 진입조건: 15,30분봉 동시 같은방향 신호만 진입!
    if pos:
        if pos["side"] == "long":
            pos["highest"] = max(pos["highest"], price)
            if price <= pos["entry_price"] * 0.98:
                close_position(symbol, price, "손절 -2%")
            elif price >= pos["entry_price"] * 1.03 and price <= pos["highest"] * 0.995:
                close_position(symbol, price, "익절 후 트레일링 스탑")
        elif pos["side"] == "short":
            pos["lowest"] = min(pos["lowest"], price)
            if price >= pos["entry_price"] * 1.02:
                close_position(symbol, price, "손절 -2%")
            elif price <= pos["entry_price"] * 0.97 and price >= pos["lowest"] * 1.005:
                close_position(symbol, price, "익절 후 트레일링 스탑")
    else:
        if cond_long_15 and cond_long_30:
            open_position(symbol, "long", price)
        elif cond_short_15 and cond_short_30:
            open_position(symbol, "short", price)

# === WebSocket 루프 (15, 30분봉 동시구독 & 자동 재연결) ===
async def ws_loop():
    uri = "wss://ws.bitget.com/v2/ws/public"
    while True:
        try:
            async with websockets.connect(uri, ping_interval=20) as ws:
                sub = {"op": "subscribe", "args": []}
                for sym in SYMBOLS:
                    sub["args"].append({"instType": "USDT-FUTURES", "channel": "candle15m", "instId": sym})
                    sub["args"].append({"instType": "USDT-FUTURES", "channel": "candle30m", "instId": sym})
                await ws.send(json.dumps(sub))
                print("✅ WebSocket 연결됨")
                while True:
                    msg = json.loads(await ws.recv())
                    if "data" in msg:
                        symbol = msg["arg"]["instId"]
                        channel = msg["arg"]["channel"]
                        tf = "15m" if channel == "candle15m" else "30m"
                        on_msg(symbol, msg["data"][0], tf)
        except Exception as e:
            print("WebSocket 오류:", e)
            print("10초 후 재연결 시도...")
            await asyncio.sleep(10)

# === 1시간 리포트 ===
def report_telegram():
    while True:
        msg = []
        for sym in SYMBOLS:
            pos = positions[sym]
            if pos:
                msg.append(f"{sym} | 포지션: {pos['side']} | 진입가: {pos['entry_price']}")
            else:
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
                pos = positions[sym]
                if pos:
                    msg += f"{sym} {pos['side']} @ {pos['entry_price']}\n"
                else:
                    msg += f"{sym} 포지션 없음\n"
            send_telegram(msg)
    return "ok"

# === 실행 ===
if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=5000)).start()
    threading.Thread(target=report_telegram, daemon=True).start()
    asyncio.run(ws_loop())


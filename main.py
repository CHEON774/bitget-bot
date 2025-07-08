import asyncio, json, websockets, numpy as np, requests, time
from datetime import datetime
from flask import Flask, request
import threading
import pandas as pd

# === 설정 ===
SYMBOLS = {
    "BTCUSDT": {"leverage": 10, "amount": 150, "stop": 0.99,  "tp": 1.015, "trail": 0.995},
    "ETHUSDT": {"leverage": 7,  "amount": 100, "stop": 0.988, "tp": 1.02,  "trail": 0.992},
    "SOLUSDT": {"leverage": 5,  "amount": 70,  "stop": 0.98,  "tp": 1.03,  "trail": 0.99},
}
INIT_BALANCE = 756.0

positions = {s: None for s in SYMBOLS}
balance = INIT_BALANCE
take_profit_count = 0
stop_loss_count = 0

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

# === 비트겟 과거 캔들 불러오기 ===
def fetch_bitget_candles(symbol, interval, limit=100):
    url = "https://api.bitget.com/api/v2/market/history-candles"
    params = {
        "instId": symbol,
        "bar": interval,  # '15m'
        "limit": limit
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        arr = []
        if resp.status_code == 200:
            js = resp.json()
            if js.get("code") == "00000":
                for d in reversed(js["data"]):
                    arr.append([
                        int(d[0]),           # timestamp
                        float(d[1]),         # open
                        float(d[2]),         # high
                        float(d[3]),         # low
                        float(d[4]),         # close
                        float(d[5]),         # volume
                    ])
        return arr
    except Exception as e:
        print("과거캔들 fetch 실패:", e)
        return []

# === 잔고 내에서만 진입 허용 ===
def total_position_amount():
    total = 0
    for sym in SYMBOLS:
        if positions[sym]:
            total += SYMBOLS[sym]["amount"]
    return total

def can_open_position(symbol):
    remain = balance - total_position_amount()
    return remain >= SYMBOLS[symbol]["amount"]

# === 진입 / 청산 시뮬레이션 (레버리지 실전 적용, 익절/손절 카운팅) ===
def close_position(symbol, side, price, reason, pnl_force=None):
    global balance, positions, take_profit_count, stop_loss_count
    pos = positions[symbol]
    if not pos: return
    entry = pos["entry_price"]
    pnl_pct = (price - entry) / entry
    if side == "short": pnl_pct *= -1
    leverage = SYMBOLS[symbol]["leverage"]
    profit = SYMBOLS[symbol]["amount"] * pnl_pct * leverage
    balance += profit
    positions[symbol] = None
    is_tp = pnl_force=="tp" or (pnl_force is None and pnl_pct > 0)
    is_sl = pnl_force=="sl" or (pnl_force is None and pnl_pct < 0)
    if is_tp: take_profit_count += 1
    if is_sl: stop_loss_count += 1
    send_telegram(
        f"{symbol} {side.upper()} 청산 @ {price}\n"
        f"수익률: {pnl_pct*100:.2f}% (레버리지 적용시 {pnl_pct*leverage*100:.2f}%)\n"
        f"실현손익: ${profit:.2f}\n"
        f"잔액: ${balance:.2f} / 사유: {reason}"
    )

def open_position(symbol, side, entry_price):
    conf = SYMBOLS[symbol]
    qty = round(conf["amount"] / entry_price * conf["leverage"], 6)
    positions[symbol] = {
        "side": side,
        "entry_price": entry_price,
        "qty": qty,
        "highest": entry_price if side == "long" else None,
        "lowest": entry_price if side == "short" else None,
        "trailing_active": False
    }
    send_telegram(f"🚀 {symbol} {side.upper()} 진입 @ {entry_price}")

# === 캔들 관리 ===
candles_15m = {s: [] for s in SYMBOLS}

# === 초기캔들 불러오기 (서버 켤 때 1회) ===
for s in SYMBOLS:
    candles_15m[s] = fetch_bitget_candles(s, "15m", limit=50)

def on_msg_15m(symbol, d):
    ts = int(d[0])
    o, h, l, c, v = map(float, d[1:6])
    arr = candles_15m[symbol]
    if arr and arr[-1][0] == ts:
        arr[-1] = [ts, o, h, l, c, v]
    else:
        arr.append([ts, o, h, l, c, v])
        if len(arr) > 200: arr.pop(0)
        analyze_B(symbol)

def analyze_B(symbol):
    if not running_flag: return
    arr = np.array(candles_15m[symbol])
    if len(arr) < 30: return
    close = arr[:,4]
    macd_hist = calc_macd_hist(close)
    adx = calc_adx(arr)
    cond_long = macd_hist[-2] < 0 and macd_hist[-1] > 0 and adx[-1] > 25
    cond_short = macd_hist[-2] > 0 and macd_hist[-1] < 0 and adx[-1] > 25
    price = close[-1]
    pos = positions[symbol]
    conf = SYMBOLS[symbol]
    # 롱
    if pos and pos["side"] == "long":
        if price <= pos["entry_price"] * conf["stop"]:
            close_position(symbol, "long", price, "손절", pnl_force="sl")
            return
        if not pos["trailing_active"] and price >= pos["entry_price"] * conf["tp"]:
            pos["trailing_active"] = True
            pos["highest"] = price
            send_telegram(f"{symbol} 롱 트레일링 활성화(15m)")
        if pos["trailing_active"]:
            pos["highest"] = max(pos["highest"], price)
            if price <= pos["highest"] * conf["trail"]:
                close_position(symbol, "long", price, "익절 트레일링", pnl_force="tp")
                return
    # 숏
    if pos and pos["side"] == "short":
        if price >= pos["entry_price"] * (2 - conf["stop"]):
            close_position(symbol, "short", price, "손절", pnl_force="sl")
            return
        if not pos["trailing_active"] and price <= pos["entry_price"] * (2 - conf["tp"]):
            pos["trailing_active"] = True
            pos["lowest"] = price
            send_telegram(f"{symbol} 숏 트레일링 활성화(15m)")
        if pos["trailing_active"]:
            pos["lowest"] = min(pos["lowest"], price)
            if price >= pos["lowest"] * (2 - conf["trail"]):
                close_position(symbol, "short", price, "익절 트레일링", pnl_force="tp")
                return
    # 진입
    if pos is None:
        if cond_long and can_open_position(symbol):
            open_position(symbol, "long", price)
        elif cond_short and can_open_position(symbol):
            open_position(symbol, "short", price)

# === WebSocket 루프 (Bitget 15m, 수동 ping/pong 포함, 자동재연결/에러방지) ===
async def ws_loop():
    uri = "wss://ws.bitget.com/v2/ws/public"
    while True:
        try:
            async with websockets.connect(uri, ping_interval=None, ping_timeout=None) as ws:
                sub = {
                    "op": "subscribe",
                    "args": [
                        {"instType": "USDT-FUTURES", "channel": "candle15m", "instId": s}
                        for s in SYMBOLS
                    ]
                }
                await ws.send(json.dumps(sub))
                print("✅ WebSocket 연결됨 (Bitget 15m)")
                last_ping = time.time()
                while True:
                    # 30초마다 수동 ping
                    if time.time() - last_ping > 30:
                        try:
                            await ws.ping()
                            last_ping = time.time()
                        except Exception as e:
                            print("ping 실패:", e)
                            break
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=35)
                        if "data" in msg:
                            msg = json.loads(msg)
                        if "data" in msg and msg["data"]:
                            symbol = msg["arg"]["instId"]
                            on_msg_15m(symbol, msg["data"][0])
                    except asyncio.TimeoutError:
                        try:
                            await ws.ping()
                            last_ping = time.time()
                        except Exception as e:
                            print("ping timeout 실패:", e)
                            break
        except Exception as e:
            print(f"❌ WebSocket 오류: {e}")
            print("⏳ 3초 후 재연결 시도...")
            await asyncio.sleep(3)

# === 1시간 리포트 (전략B만) ===
def report_telegram():
    global report_flag
    while report_flag:
        msg = []
        msg.append("1억 가즈아")
        for sym in SYMBOLS:
            pos = positions[sym]
            if pos:
                entry = pos['entry_price']
                arr = candles_15m.get(sym)
                price_now = entry
                if arr and len(arr)>0:
                    price_now = arr[-1][4]
                pnl = (price_now - entry) / entry * 100
                if pos["side"] == "short": pnl *= -1
                trail_state = "O" if pos.get("trailing_active") else "X"
                msg.append(f"{sym} | {pos['side'].upper()} | 진입가: {entry} | 수익률: {pnl:.2f}% | 트레일링:{trail_state}")
            else:
                msg.append(f"{sym} | 포지션: - | 진입가: -")
        msg.append(f"현재 가상잔고: {balance:.2f}")
        msg.append(f"누적 익절: {take_profit_count}회 / 누적 손절: {stop_loss_count}회\n")
        send_telegram("\n".join(msg))
        for _ in range(3600):
            if not report_flag:
                break
            time.sleep(1)

# === Flask 텔레그램 명령어 제어 (/시작 /중지 /상태) ===
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
                pos = positions[sym]
                if pos:
                    arr = candles_15m.get(sym)
                    price_now = pos["entry_price"]
                    if arr and len(arr)>0:
                        price_now = arr[-1][4]
                    close_position(sym, pos["side"], price_now, "자동매매 중지(전체 청산)")
            send_telegram("✅ 모든 포지션 정리 완료")
        elif text == "/상태":
            msgtxt = "전략B(MACD7-17-8+ADX5, 15m)\n"
            for sym in SYMBOLS:
                pos = positions[sym]
                if pos:
                    entry = pos['entry_price']
                    arr = candles_15m.get(sym)
                    price_now = entry
                    if arr and len(arr)>0:
                        price_now = arr[-1][4]
                    pnl = (price_now - entry) / entry * 100
                    if pos["side"] == "short": pnl *= -1
                    trail_state = "O" if pos.get("trailing_active") else "X"
                    msgtxt += f"{sym} {pos['side'].upper()} @ {entry} | 수익률: {pnl:.2f}% | 트레일링:{trail_state}\n"
                else:
                    msgtxt += f"{sym} 포지션 없음\n"
            msgtxt += f"현재 가상잔고: {balance:.2f}\n"
            msgtxt += f"누적 익절: {take_profit_count}회 / 누적 손절: {stop_loss_count}회\n\n"
            send_telegram(msgtxt)
    return "ok"

# === 실행 ===
if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=5000)).start()
    threading.Thread(target=report_telegram, daemon=True).start()
    asyncio.run(ws_loop())

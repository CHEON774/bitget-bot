import asyncio, json, websockets, time
from datetime import datetime
import numpy as np
import threading
import requests

TELEGRAM_TOKEN = '7776435078:AAFsM_jIDSx1Eij4YJyqJp-zEDtQVtKohnU'
TELEGRAM_CHAT_ID = '1797494660'

SYMBOLS = {
    "BTCUSDT": {"leverage": 10, "amount": 150},
    "ETHUSDT": {"leverage": 7, "amount": 120}
}
VIRTUAL_BALANCE = 756.0  # 시작 잔고 (가상잔고)
virtual_balance = VIRTUAL_BALANCE
positions = {sym: None for sym in SYMBOLS}  # None, "long", "short"
entry_prices = {sym: None for sym in SYMBOLS}
trailing_highs = {sym: None for sym in SYMBOLS}
trailing_lows = {sym: None for sym in SYMBOLS}

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"})

def calc_cci(candles, period=14):
    cci = []
    for i in range(len(candles)):
        if i < period-1:
            cci.append(np.nan)
            continue
        slice = candles[i-period+1:i+1]
        tp = [(float(x[1])+float(x[2])+float(x[3]))/3 for x in slice]
        ma = np.mean(tp)
        md = np.mean([abs(x-ma) for x in tp])
        if md == 0: cci.append(0)
        else: cci.append((tp[-1] - ma) / (0.015 * md))
    return cci

def calc_adx(candles, period=5):
    highs = np.array([float(x[2]) for x in candles])
    lows = np.array([float(x[3]) for x in candles])
    closes = np.array([float(x[4]) for x in candles])
    tr = np.maximum(highs[1:] - lows[1:], np.abs(highs[1:] - closes[:-1]), np.abs(lows[1:] - closes[:-1]))
    plus_dm = np.where((highs[1:] - highs[:-1]) > (lows[:-1] - lows[1:]), highs[1:] - highs[:-1], 0)
    minus_dm = np.where((lows[:-1] - lows[1:]) > (highs[1:] - highs[:-1]), lows[:-1] - lows[1:], 0)
    tr_sum = np.convolve(tr, np.ones(period), 'valid')
    plus_di = 100 * np.convolve(plus_dm, np.ones(period), 'valid') / tr_sum
    minus_di = 100 * np.convolve(minus_dm, np.ones(period), 'valid') / tr_sum
    dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = np.convolve(dx, np.ones(period), 'valid') / period
    result = [np.nan]*(2*period-2) + list(adx)
    return result

MAX_CANDLES = 150
candles_data = {sym: [] for sym in SYMBOLS}

# --- 가상매매 핵심: 수익/손실 계산 및 잔고 변동 ---
def calc_pnl(symbol, entry, exit, side, amount):
    # 실매매 레버리지 포함 X, 단순 퍼센트만 계산 (실제 잔고 관리)
    diff = (exit - entry) if side == "long" else (entry - exit)
    rate = diff / entry
    profit = amount * rate
    return profit, rate * 100

async def process_signal(symbol, cci_val, adx_val, close):
    global virtual_balance
    # 이미 포지션 있으면 청산 조건만 감시
    if positions[symbol]:
        # 트레일링 스탑
        if positions[symbol] == "long":
            if trailing_highs[symbol] is None or close > trailing_highs[symbol]:
                trailing_highs[symbol] = close
            # +3% 넘으면 최고가-0.5% 이탈시 청산
            if close >= entry_prices[symbol] * 1.03:
                stop_price = trailing_highs[symbol] * 0.995
                if close <= stop_price:
                    profit, rate = calc_pnl(symbol, entry_prices[symbol], close, "long", SYMBOLS[symbol]['amount'])
                    virtual_balance += profit
                    send_telegram(f"🔔 [롱 트레일링스탑] {symbol} 청산: {close:.2f}\n수익률: {rate:.2f}%\n가상잔고: {virtual_balance:.2f}")
                    positions[symbol] = None
                    entry_prices[symbol] = None
                    trailing_highs[symbol] = None
                    return
            # -2% 손절
            if close <= entry_prices[symbol] * 0.98:
                profit, rate = calc_pnl(symbol, entry_prices[symbol], close, "long", SYMBOLS[symbol]['amount'])
                virtual_balance += profit
                send_telegram(f"❌ [롱 손절] {symbol} 청산: {close:.2f}\n수익률: {rate:.2f}%\n가상잔고: {virtual_balance:.2f}")
                positions[symbol] = None
                entry_prices[symbol] = None
                trailing_highs[symbol] = None
                return
        elif positions[symbol] == "short":
            if trailing_lows[symbol] is None or close < trailing_lows[symbol]:
                trailing_lows[symbol] = close
            # +3% 넘으면 최저가+0.5% 이탈시 청산
            if close <= entry_prices[symbol] * 0.97:
                stop_price = trailing_lows[symbol] * 1.005
                if close >= stop_price:
                    profit, rate = calc_pnl(symbol, entry_prices[symbol], close, "short", SYMBOLS[symbol]['amount'])
                    virtual_balance += profit
                    send_telegram(f"🔔 [숏 트레일링스탑] {symbol} 청산: {close:.2f}\n수익률: {rate:.2f}%\n가상잔고: {virtual_balance:.2f}")
                    positions[symbol] = None
                    entry_prices[symbol] = None
                    trailing_lows[symbol] = None
                    return
            # -2% 손절
            if close >= entry_prices[symbol] * 1.02:
                profit, rate = calc_pnl(symbol, entry_prices[symbol], close, "short", SYMBOLS[symbol]['amount'])
                virtual_balance += profit
                send_telegram(f"❌ [숏 손절] {symbol} 청산: {close:.2f}\n수익률: {rate:.2f}%\n가상잔고: {virtual_balance:.2f}")
                positions[symbol] = None
                entry_prices[symbol] = None
                trailing_lows[symbol] = None
                return
        return

    # 진입 신호
    if cci_val > 100 and adx_val > 25:
        positions[symbol] = "long"
        entry_prices[symbol] = close
        trailing_highs[symbol] = close
        send_telegram(f"🚀 [롱 진입] {symbol}\n진입가: {close:.2f}\nCCI:{cci_val:.1f}, ADX:{adx_val:.1f}\n가상잔고: {virtual_balance:.2f}")
    elif cci_val < -100 and adx_val > 25:
        positions[symbol] = "short"
        entry_prices[symbol] = close
        trailing_lows[symbol] = close
        send_telegram(f"🔥 [숏 진입] {symbol}\n진입가: {close:.2f}\nCCI:{cci_val:.1f}, ADX:{adx_val:.1f}\n가상잔고: {virtual_balance:.2f}")

async def ws_loop(symbol):
    uri = "wss://ws.bitget.com/v2/ws/public"
    channel = "candle15m"
    async with websockets.connect(uri, ping_interval=20) as ws:
        await ws.send(json.dumps({
            "op": "subscribe",
            "args": [{
                "instType": "USDT-FUTURES",
                "channel": channel,
                "instId": symbol
            }]
        }))
        print(f"✅ {symbol} WebSocket 연결됨")
        while True:
            msg = json.loads(await ws.recv())
            if msg.get("event") == "error":
                print(f"❌ 에러: {msg}")
                continue
            if msg.get("action") in ["snapshot", "update"]:
                d = msg["data"][0]
                # [timestamp, open, high, low, close, vol]
                if len(candles_data[symbol]) > 0 and d[0] == candles_data[symbol][-1][0]:
                    candles_data[symbol][-1] = d
                else:
                    candles_data[symbol].append(d)
                if len(candles_data[symbol]) > MAX_CANDLES:
                    candles_data[symbol] = candles_data[symbol][-MAX_CANDLES:]
                if len(candles_data[symbol]) >= 20:
                    cci_vals = calc_cci(candles_data[symbol], 14)
                    adx_vals = calc_adx(candles_data[symbol], 5)
                    latest_cci = cci_vals[-1]
                    latest_adx = adx_vals[-1]
                    close = float(d[4])
                    await process_signal(symbol, latest_cci, latest_adx, close)

def periodic_report():
    global virtual_balance
    while True:
        msg = "[1시간마다 리포트]\n"
        for symbol in SYMBOLS:
            pos = positions[symbol]
            entry = entry_prices[symbol]
            msg += f"{symbol} | 포지션: {pos or '-'} | 진입가: {entry or '-'}\n"
        msg += f"현재 가상잔고: {virtual_balance:.2f}\n"
        send_telegram(msg)
        time.sleep(3600)

def start_all():
    send_telegram(f"✅ 가상매매 봇 시작!\n초기잔고: {virtual_balance}\n전략: 15분봉, CCI(14)+ADX(5)\n롱: CCI>100/ADX>25, 숏: CCI<-100/ADX>25\n익절+3%→트레일링스탑(-0.5%), 손절-2%")
    for symbol in SYMBOLS:
        threading.Thread(target=lambda: asyncio.run(ws_loop(symbol))).start()
    threading.Thread(target=periodic_report, daemon=True).start()

if __name__ == "__main__":
    start_all()


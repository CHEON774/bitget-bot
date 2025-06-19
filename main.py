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
VIRTUAL_BALANCE = 756.0  # 초기 가상잔고
virtual_balance = VIRTUAL_BALANCE
positions = {sym: None for sym in SYMBOLS}  # None, "long", "short"
entry_prices = {sym: None for sym in SYMBOLS}
trailing_highs = {sym: None for sym in SYMBOLS}
trailing_lows = {sym: None for sym in SYMBOLS}
MAX_CANDLES = 150
candles_data = {sym: [] for sym in SYMBOLS}

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except Exception as e:
        print("텔레그램 전송 오류:", e)

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

def calc_pnl(symbol, entry, exit, side, amount):
    leverage = SYMBOLS[symbol]['leverage']
    diff = (exit - entry) if side == "long" else (entry - exit)
    rate = diff / entry
    profit = amount * rate * leverage  # 레버리지 반영
    return profit, rate * leverage * 100

async def process_signal(symbol, cci_val, adx_val, close):
    global virtual_balance
    if positions[symbol]:
        # 롱
        if positions[symbol] == "long":
            if trailing_highs[symbol] is None or close > trailing_highs[symbol]:
                trailing_highs[symbol] = close
            # +3% 이상 트레일링스탑(최고가-0.5%)
            if close >= entry_prices[symbol] * 1.03:
                stop_price = trailing_highs[symbol] * 0.995
                if close <= stop_price:
                    profit, rate = calc_pnl(symbol, entry_prices[symbol], close, "long", SYMBOLS[symbol]['amount'])
                    virtual_balance += profit
                    send_telegram(f"🔔 [롱 트레일링스탑] {symbol} 청산: {close:.2f}\n레버리지 수익률: {rate:.2f}%\n수익: {profit:.2f} USDT\n가상잔고: {virtual_balance:.2f}")
                    positions[symbol] = None
                    entry_prices[symbol] = None
                    trailing_highs[symbol] = None
                    return
            # -2% 손절
            if close <= entry_prices[symbol] * 0.98:
                profit, rate = calc_pnl(symbol, entry_prices[symbol], close, "long", SYMBOLS[symbol]['amount'])
                virtual_balance += profit
                send_telegram(f"❌ [롱 손절] {symbol} 청산: {close:.2f}\n레버리지 수익률: {rate:.2f}%\n손익: {profit:.2f} USDT\n가상잔고: {virtual_balance:.2f}")
                positions[symbol] = None
                entry_prices[symbol] = None
                trailing_highs[symbol] = None
                return
        # 숏
        elif positions[symbol] == "short":
            if trailing_lows[symbol] is None or close < trailing_lows[symbol]:
                trailing_lows[symbol] = close
            # +3% 이상 트레일링스탑(최저가+0.5%)
            if close <= entry_prices[symbol] * 0.97:
                stop_price = trailing_lows[symbol] * 1.005
                if close >= stop_price:
                    profit, rate = calc_pnl(symbol, entry_prices[symbol], close, "short", SYMBOLS[symbol]['amount'])
                    virtual_balance += profit
                    send_telegram(f"🔔 [숏 트레일링스탑] {symbol} 청산: {close:.2f}\n레버리지 수익률: {rate:.2f}%\n수익: {profit:.2f} USDT\n가상잔고: {virtual_balance:.2f}")
                    positions[symbol] = None
                    entry_prices[symbol] = None
                    trailing_lows[symbol] = None
                    return
            # -2% 손절
            if close >= entry_prices[symbol] * 1.02:
                profit, rate = calc_pnl(symbol, entry_prices[symbol], close, "short", SYMBOLS[symbol]['amount'])
                virtual_balance += profit
                send_telegram(f"❌ [숏 손절] {symbol} 청산: {close:.2f}\n레버리지 수익률: {rate:.2f}%\n손익: {profit:.2f} USDT\n가상잔고: {virtual_balance:.2f}")
                positions[symbol] = None
                entry_prices[symbol] = None
                trailing_lows[symbol] = None
                return
        return

    # 진입 신호 (중복진입 방지)
    if cci_val > 100 and adx_val > 25 and positions[symbol] is None:
        positions[symbol] = "long"
        entry_prices[symbol] = close
        trailing_highs[symbol] = close
        send_telegram(f"🚀 [롱 진입] {symbol}\n진입가: {close:.2f}\nCCI:{cci_val:.1f}, ADX:{adx_val:.1f}\n가상잔고: {virtual_balance:.2f}")
    elif cci_val < -100 and adx_val > 25 and positions[symbol] is None:
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

async def main():
    tasks = [ws_loop(symbol) for symbol in SYMBOLS]
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    send_telegram(
        f"✅ 가상매매 봇 시작!\n초기잔고: {virtual_balance}\n전략: 15분봉, CCI(14)+ADX(5)\n"
        f"롱: CCI>100/ADX>25, 숏: CCI<-100/ADX>25\n"
        f"익절+3%→트레일링스탑(-0.5%), 손절-2%\n"
        f"BTC: 10배, ETH: 7배"
    )
    threading.Thread(target=periodic_report, daemon=True).start()
    asyncio.run(main())


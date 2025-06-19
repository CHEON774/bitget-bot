import asyncio, json, websockets, numpy as np, time
from datetime import datetime, timedelta
import requests

TELEGRAM_TOKEN = '7776435078:AAFsM_jIDSx1Eij4YJyqJp-zEDtQVtKohnU'
TELEGRAM_CHAT_ID = '1797494660'

SYMBOLS = {
    'BTCUSDT': {'amount': 150},
    'ETHUSDT': {'amount': 120}
}

CHANNEL = 'candle15m'
INST_TYPE = 'USDT-FUTURES'
MAX_CANDLES = 100

ENTRY_CCI = 100
STOP_LOSS = -0.02
TAKE_PROFIT = 0.03
TRAILING_GAP = 0.005

candles, positions = {s: [] for s in SYMBOLS}, {}
cci_values, adx_values, last_prices = {}, {}, {}
trail_highs = {}
mock_balance = 756
loss_count = {s: 0 for s in SYMBOLS}
auto_trading = {s: True for s in SYMBOLS}
last_balance_check = datetime.utcnow()

async def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={'chat_id': TELEGRAM_CHAT_ID, 'text': msg})
    except: pass

def calculate_cci(data):
    try:
        tp = [(float(o)+float(h)+float(l))/3 for o,h,l in zip(data[:,1], data[:,2], data[:,3])]
        ma = np.mean(tp)
        md = np.mean(np.abs(tp - ma))
        return (tp[-1] - ma) / (0.015 * md)
    except: return None

def calculate_adx(data):
    try:
        high, low, close = data[:,2].astype(float), data[:,3].astype(float), data[:,4].astype(float)
        tr = np.maximum(high[1:], close[:-1]) - np.minimum(low[1:], close[:-1])
        pdm = np.where((high[1:] - high[:-1]) > (low[:-1] - low[1:]), high[1:] - high[:-1], 0)
        mdm = np.where((low[:-1] - low[1:]) > (high[1:] - high[:-1]), low[:-1] - low[1:], 0)
        trn, pdin, mdin = np.mean(tr[-5:]), np.mean(pdm[-5:]), np.mean(mdm[-5:])
        pdi, mdi = 100 * pdin / trn, 100 * mdin / trn
        return 100 * abs(pdi - mdi) / (pdi + mdi)
    except: return None

def update_candle(symbol, c):
    candles[symbol].append(c)
    if len(candles[symbol]) > MAX_CANDLES:
        candles[symbol].pop(0)
    np_candles = np.array(candles[symbol])
    cci_values[symbol] = calculate_cci(np_candles[-15:])
    adx_values[symbol] = calculate_adx(np_candles[-6:])
    last_prices[symbol] = float(c[4])

def simulate_trade(symbol):
    global mock_balance
    if not auto_trading[symbol]:
        return

    price = last_prices.get(symbol)
    cci = cci_values.get(symbol)
    adx = adx_values.get(symbol)

    if symbol in positions:
        entry = positions[symbol]['entry']
        side = positions[symbol]['side']
        amt = SYMBOLS[symbol]['amount']
        size = amt / entry
        profit_ratio = (price - entry) / entry if side == 'long' else (entry - price) / entry

        if profit_ratio >= TAKE_PROFIT:
            trail_highs[symbol] = max(trail_highs[symbol], price) if side == 'long' else min(trail_highs[symbol], price)

        if profit_ratio <= STOP_LOSS or \
          (symbol in trail_highs and (
            (side == 'long' and price < trail_highs[symbol]*(1 - TRAILING_GAP)) or 
            (side == 'short' and price > trail_highs[symbol]*(1 + TRAILING_GAP))
          )):
            pnl = profit_ratio * amt
            mock_balance += pnl
            result = "익절" if pnl > 0 else "손절"
            if pnl < 0:
                loss_count[symbol] += 1
                if loss_count[symbol] >= 3:
                    auto_trading[symbol] = False
                    asyncio.create_task(send_telegram(f"⛔ {symbol} 3회 손절로 자동매매 중단"))

            asyncio.create_task(send_telegram(f"💥 {symbol} {side.upper()} 청산 @ {price:.2f} | {result} | 잔액: {mock_balance:.2f}"))
            del positions[symbol]
            if symbol in trail_highs:
                del trail_highs[symbol]
        return

    if cci is None or adx is None or adx < 25:
        return

    amt = SYMBOLS[symbol]['amount']
    size = amt / price
    if cci > ENTRY_CCI:
        positions[symbol] = {'entry': price, 'side': 'long'}
        trail_highs[symbol] = price
        asyncio.create_task(send_telegram(f"🟢 롱 진입: {symbol} @ {price:.2f}"))
    elif cci < -ENTRY_CCI:
        positions[symbol] = {'entry': price, 'side': 'short'}
        trail_highs[symbol] = price
        asyncio.create_task(send_telegram(f"🔴 숏 진입: {symbol} @ {price:.2f}"))

def on_msg(msg):
    try:
        if 'data' in msg and isinstance(msg['data'], list):
            arg = msg.get('arg', {})
            symbol = arg.get('instId')
            c = msg['data'][0]
            if symbol and c:
                update_candle(symbol, c)
                simulate_trade(symbol)
    except Exception as e:
        print(f"❌ 메시지 오류: {e}")

async def periodic_alert():
    global last_balance_check
    while True:
        await asyncio.sleep(60)
        if datetime.utcnow() - last_balance_check > timedelta(hours=1):
            last_balance_check = datetime.utcnow()
            msg = f"⏰ 1시간마다 잔액 알림\n💰 현재 모의 잔액: {mock_balance:.2f}\n"
            for sym in SYMBOLS:
                pos = positions.get(sym)
                if pos:
                    msg += f"{sym}: {pos['side']} 진입 @ {pos['entry']:.2f}\n"
            await send_telegram(msg)

async def ws_loop():
    uri = "wss://ws.bitget.com/v2/ws/public"
    async with websockets.connect(uri, ping_interval=20) as ws:
        sub = {
            "op": "subscribe",
            "args": [{"instType": INST_TYPE, "channel": CHANNEL, "instId": s} for s in SYMBOLS]
        }
        await ws.send(json.dumps(sub))
        print("✅ WebSocket 연결됨")
        await send_telegram("🤖 모의 매매 시작\n15분봉 기준 CCI(14), ADX(5) 전략 실행 중")
        while True:
            try:
                msg = json.loads(await ws.recv())
                if msg.get("action") in ["snapshot", "update"]:
                    on_msg(msg)
            except Exception as e:
                print(f"🔌 WS 오류: {e}")
                await asyncio.sleep(5)

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(ws_loop())
    loop.create_task(periodic_alert())
    loop.run_forever()


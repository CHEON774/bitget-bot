import asyncio, websockets, json, numpy as np, requests
from datetime import datetime, timedelta, timezone

# === 기본 설정 ===
TELEGRAM_TOKEN = '7776435078:AAFsM_jIDSx1Eij4YJyqJp-zEDtQVtKohnU'
TELEGRAM_CHAT_ID = '1797494660'

SYMBOLS = {
    "BTCUSDT": {"amount": 150},
    "ETHUSDT": {"amount": 120},
}
CHANNEL = "candle15m"
INST_TYPE = "USDT-FUTURES"
MAX_CANDLES = 100

CCI_PERIOD = 14
ADX_PERIOD = 5
ENTRY_CCI = 100
ADX_THRESHOLD = 25
TAKE_PROFIT = 0.03
STOP_LOSS = -0.02
TRAILING_GAP = 0.005

candles = {s: [] for s in SYMBOLS}
positions = {}
trail_highs = {}
mock_balance = 756.0
loss_count = {s: 0 for s in SYMBOLS}
auto_trading = {s: True for s in SYMBOLS}
last_balance_check = datetime.now(timezone.utc)

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={'chat_id': TELEGRAM_CHAT_ID, 'text': msg})
    except Exception as e:
        print(f"❌ 텔레그램 오류: {e}")

def calculate_cci(data):
    if len(data) < CCI_PERIOD: return None
    try:
        tp = (data[:,1].astype(float) + data[:,2].astype(float) + data[:,3].astype(float)) / 3
        ma = np.mean(tp)
        md = np.mean(np.abs(tp - ma))
        if md == 0: return None
        return (tp[-1] - ma) / (0.015 * md)
    except: return None

def calculate_adx(data):
    if len(data) < ADX_PERIOD + 1: return None
    try:
        highs, lows, closes = data[:,2].astype(float), data[:,3].astype(float), data[:,4].astype(float)
        tr = np.maximum(highs[1:], closes[:-1]) - np.minimum(lows[1:], closes[:-1])
        plus_dm = np.where((highs[1:] - highs[:-1]) > (lows[:-1] - lows[1:]), highs[1:] - highs[:-1], 0)
        minus_dm = np.where((lows[:-1] - lows[1:]) > (highs[1:] - highs[:-1]), lows[:-1] - lows[1:], 0)
        tr_avg = np.mean(tr[-ADX_PERIOD:])
        if tr_avg == 0: return None
        pdi = 100 * np.mean(plus_dm[-ADX_PERIOD:]) / tr_avg
        mdi = 100 * np.mean(minus_dm[-ADX_PERIOD:]) / tr_avg
        if pdi + mdi == 0: return None
        return 100 * abs(pdi - mdi) / (pdi + mdi)
    except: return None

def update_candle(symbol, candle):
    candles[symbol].append(candle)
    if len(candles[symbol]) > MAX_CANDLES:
        candles[symbol].pop(0)

def simulate_trade(symbol):
    global mock_balance
    if not auto_trading[symbol]:
        return

    np_data = np.array(candles[symbol])
    if len(np_data) < CCI_PERIOD or len(np_data) < ADX_PERIOD + 1: return

    cci = calculate_cci(np_data[-CCI_PERIOD:])
    adx = calculate_adx(np_data[-ADX_PERIOD-1:])
    price = float(np_data[-1][4])

    # === 포지션 청산/관리 ===
    if symbol in positions:
        entry = positions[symbol]['entry']
        side = positions[symbol]['side']
        amt = SYMBOLS[symbol]['amount']
        qty = amt / entry
        pnl_ratio = (price - entry) / entry if side == 'long' else (entry - price) / entry

        # 트레일링 스탑 관리
        if side == 'long':
            trail_highs[symbol] = max(trail_highs[symbol], price)
            stop_out = price < trail_highs[symbol] * (1 - TRAILING_GAP)
        else:
            trail_highs[symbol] = min(trail_highs[symbol], price)
            stop_out = price > trail_highs[symbol] * (1 + TRAILING_GAP)

        if pnl_ratio >= TAKE_PROFIT or pnl_ratio <= STOP_LOSS or stop_out:
            pnl = pnl_ratio * amt
            mock_balance += pnl
            result = "익절" if pnl > 0 else "손절"
            if pnl < 0:
                loss_count[symbol] += 1
                if loss_count[symbol] >= 3:
                    auto_trading[symbol] = False
                    send_telegram(f"⛔ {symbol} 3회 손절로 자동매매 중단")
            send_telegram(f"💥 {symbol} {side.upper()} 청산 @ {price:.2f} | {result} | 손익: {pnl:.2f} | 잔액: {mock_balance:.2f}")
            del positions[symbol]
            if symbol in trail_highs:
                del trail_highs[symbol]
        return

    # === 신규 진입 ===
    if cci is None or adx is None or adx < ADX_THRESHOLD:
        return
    amt = SYMBOLS[symbol]['amount']
    qty = amt / price
    if cci > ENTRY_CCI:
        positions[symbol] = {'entry': price, 'side': 'long'}
        trail_highs[symbol] = price
        send_telegram(f"🟢 롱 진입: {symbol} @ {price:.2f}")
    elif cci < -ENTRY_CCI:
        positions[symbol] = {'entry': price, 'side': 'short'}
        trail_highs[symbol] = price
        send_telegram(f"🔴 숏 진입: {symbol} @ {price:.2f}")

async def periodic_alert():
    global last_balance_check
    while True:
        await asyncio.sleep(60)
        now = datetime.now(timezone.utc)
        if now - last_balance_check > timedelta(hours=1):
            last_balance_check = now
            msg = f"⏰ 1시간 잔액 리포트\n💰 잔액: {mock_balance:.2f} USDT\n"
            for sym in SYMBOLS:
                pos = positions.get(sym)
                if pos:
                    msg += f"{sym}: {pos['side']} 진입 @ {pos['entry']:.2f}\n"
            send_telegram(msg)

async def ws_loop():
    uri = "wss://ws.bitget.com/v2/ws/public"
    while True:
        try:
            async with websockets.connect(uri, ping_interval=20) as ws:
                sub = {
                    "op": "subscribe",
                    "args": [{"instType": INST_TYPE, "channel": CHANNEL, "instId": s} for s in SYMBOLS]
                }
                await ws.send(json.dumps(sub))
                send_telegram(f"🤖 모의매매 시작\n현재 잔액: {mock_balance:.2f} USDT\n15분봉 기준 CCI(14), ADX(5) 전략 실행 중")
                print("✅ WebSocket 연결됨")
                while True:
                    try:
                        msg = json.loads(await ws.recv())
                        if msg.get("action") in ["snapshot", "update"]:
                            symbol = msg['arg']['instId']
                            candle = msg['data'][0]
                            update_candle(symbol, candle)
                            simulate_trade(symbol)
                    except Exception as e:
                        print(f"❌ 메시지 오류: {e}")
                        break  # 내부 루프 탈출, 아래에서 재연결 대기
        except Exception as e:
            print(f"🔌 WebSocket 연결 오류: {e}")
        # 연결 실패·오류시 잠깐 대기 후 재연결 시도
        await asyncio.sleep(5)


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(ws_loop())
    loop.create_task(periodic_alert())
    loop.run_forever()


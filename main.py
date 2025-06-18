# ✅ Bitget 자동매매 최종 완성 코드 (명령어 제어 제외 / 모든 함수 포함)
# 실행 전 반드시 API_KEY, SECRET, PASSPHRASE, TELEGRAM 정보 입력 필요

import asyncio, json, websockets, requests, hmac, hashlib, time
from datetime import datetime
import numpy as np
import threading
from flask import Flask

app = Flask(__name__)

API_KEY = 'bg_a9c07aa3168e846bfaa713fe9af79d14'
API_SECRET = '5be628fd41dce5eff78a607f31d096a4911d4e2156b6d66a14be20f027068043'
API_PASSPHRASE = '1q2w3e4r'
TELEGRAM_TOKEN = '7776435078:AAFsM_jIDSx1Eij4YJyqJp-zEDtQVtKohnU'
TELEGRAM_CHAT_ID = '1797494660'

SYMBOLS = {
    'BTCUSDT': {'leverage': 10, 'amount': 150},
    'ETHUSDT': {'leverage': 7, 'amount': 120},
}
INST_TYPE = 'USDT-FUTURES'
CHANNEL = 'candle15m'
MAX_CANDLES = 100
ENTRY_CCI = 100
STOP_LOSS = -0.02
TAKE_PROFIT = 0.03
TRAILING_GAP = 0.005

candles = {sym: [] for sym in SYMBOLS}
cci_values, adx_values, last_prices = {}, {}, {}
positions, trail_highs, stop_counts = {}, {}, {sym: 0 for sym in SYMBOLS}
connected_once = False

async def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
    try:
        headers = {'Content-Type': 'application/json'}
        requests.post(url, data=json.dumps(data, ensure_ascii=False), headers=headers)
    except Exception as e:
        print(f"❌ Telegram Error: {e}")

def get_server_timestamp():
    return str(int(time.time() * 1000))

def sign_request(timestamp, method, path, body=''):
    pre_hash = f"{timestamp}{method}{path}{body}"
    return hmac.new(API_SECRET.encode(), pre_hash.encode(), hashlib.sha256).hexdigest()

def get_balance():
    url_path = "/api/mix/v1/account/account?marginCoin=USDT"
    timestamp = get_server_timestamp()
    sign = sign_request(timestamp, "GET", url_path)
    headers = {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": API_PASSPHRASE
    }
    try:
        res = requests.get(f"https://api.bitget.com{url_path}", headers=headers).json()
        return float(res['data']['available']) if res['code'] == '00000' else None
    except Exception as e:
        print(f"❌ 잔액 조회 오류: {e}")
        return None

def place_market_order(symbol, side, size):
    url_path = "/api/mix/v1/order/place"
    timestamp = get_server_timestamp()
    body = json.dumps({
        "symbol": symbol,
        "marginCoin": "USDT",
        "size": str(size),
        "side": side,
        "orderType": "market",
        "tradeSide": side,
        "productType": "umcbl",
    })
    sign = sign_request(timestamp, "POST", url_path, body)
    headers = {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": API_PASSPHRASE,
        "Content-Type": "application/json"
    }
    try:
        res = requests.post(f"https://api.bitget.com{url_path}", headers=headers, data=body).json()
        return res
    except Exception as e:
        print(f"❌ 주문 오류: {e}")
        return None

async def notify_start():
    balance = get_balance()
    msg = "📥 자동매매 시작됨\n"
    for sym, conf in SYMBOLS.items():
        msg += f"[{sym}] 금액: ${conf['amount']} | 레버리지: {conf['leverage']}배\n"
    msg += f"\n💰 잔액: {balance} USDT" if balance else "\n💰 잔액 조회 실패"
    await send_telegram_message(msg)

def calculate_cci(data):
    try:
        tps = [(float(o)+float(h)+float(l))/3 for o,h,l in zip(data[:,1], data[:,2], data[:,3])]
        ma, md = np.mean(tps), np.mean(np.abs(tps - np.mean(tps)))
        return (tps[-1] - ma) / (0.015 * md)
    except: return None

def calculate_adx(data):
    try:
        highs, lows, closes = data[:,2].astype(float), data[:,3].astype(float), data[:,4].astype(float)
        tr = np.maximum(highs[1:], closes[:-1]) - np.minimum(lows[1:], closes[:-1])
        plus_dm = np.where((highs[1:] - highs[:-1]) > (lows[:-1] - lows[1:]), highs[1:] - highs[:-1], 0)
        minus_dm = np.where((lows[:-1] - lows[1:]) > (highs[1:] - highs[:-1]), lows[:-1] - lows[1:], 0)
        tr_avg = np.mean(tr[-5:])
        plus_di = 100 * (np.mean(plus_dm[-5:]) / tr_avg)
        minus_di = 100 * (np.mean(minus_dm[-5:]) / tr_avg)
        return 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    except: return None

def handle_new_candle(symbol, candle):
    try:
        candles[symbol].append(candle)
        if len(candles[symbol]) > MAX_CANDLES:
            candles[symbol].pop(0)
        np_data = np.array(candles[symbol])
        cci_values[symbol] = calculate_cci(np_data[-15:])
        adx_values[symbol] = calculate_adx(np_data[-6:])
        last_prices[symbol] = float(candle[4])
    except Exception as e:
        print(f"❌ 캔들 처리 오류({symbol}): {e}")

async def periodic_alert():
    await asyncio.sleep(10)
    while True:
        try:
            msg = "⏰ 1시간마다 지표 알림\n"
            for symbol in SYMBOLS:
                price = last_prices.get(symbol, 'N/A')
                cci = cci_values.get(symbol, 'N/A')
                adx = adx_values.get(symbol, 'N/A')
                cci_str = f"{cci:.2f}" if isinstance(cci, (int, float)) else str(cci)
                adx_str = f"{adx:.2f}" if isinstance(adx, (int, float)) else str(adx)
                msg += f"[{symbol}] 가격: {price}\nCCI: {cci_str} | ADX: {adx_str}\n"
            await send_telegram_message(msg)
        except Exception as e:
            print(f"❌ 지표 알림 오류: {e}")
        await asyncio.sleep(3600)

def check_and_trade(symbol):
    if symbol in positions:
        entry = positions[symbol]['entry']
        size = positions[symbol]['size']
        side = positions[symbol]['side']
        price = last_prices[symbol]
        if side == 'open_long':
            profit = (price - entry) / entry
            if profit >= TAKE_PROFIT:
                trail_highs[symbol] = max(trail_highs[symbol], price)
            if profit <= STOP_LOSS or (symbol in trail_highs and price < trail_highs[symbol] * (1 - TRAILING_GAP)):
                place_market_order(symbol, 'close_long', size)
                del positions[symbol], trail_highs[symbol]
                asyncio.create_task(send_telegram_message(f"🔻 {symbol} 롱 청산 @ {price:.2f}"))
        elif side == 'open_short':
            profit = (entry - price) / entry
            if profit >= TAKE_PROFIT:
                trail_highs[symbol] = min(trail_highs[symbol], price)
            if profit <= STOP_LOSS or (symbol in trail_highs and price > trail_highs[symbol] * (1 + TRAILING_GAP)):
                place_market_order(symbol, 'close_short', size)
                del positions[symbol], trail_highs[symbol]
                asyncio.create_task(send_telegram_message(f"🔺 {symbol} 숏 청산 @ {price:.2f}"))
    else:
        cci, adx = cci_values.get(symbol), adx_values.get(symbol)
        price = last_prices.get(symbol)
        if cci is None or adx is None or adx < 25:
            return
        conf = SYMBOLS[symbol]
        size = round(conf['amount'] * conf['leverage'] / price, 4)
        if cci > ENTRY_CCI:
            place_market_order(symbol, 'open_long', size)
            positions[symbol] = {'entry': price, 'size': size, 'side': 'open_long'}
            trail_highs[symbol] = price
            asyncio.create_task(send_telegram_message(f"🟢 {symbol} 롱 진입 @ {price:.2f}"))
        elif cci < -ENTRY_CCI:
            place_market_order(symbol, 'open_short', size)
            positions[symbol] = {'entry': price, 'size': size, 'side': 'open_short'}
            trail_highs[symbol] = price
            asyncio.create_task(send_telegram_message(f"🔴 {symbol} 숏 진입 @ {price:.2f}"))

def on_msg(msg):
    if isinstance(msg.get("data"), list):
        try:
            d = msg['data'][0]
            symbol = d['instId']
            candle = d['candle']
            handle_new_candle(symbol, candle)
            check_and_trade(symbol)
        except Exception as e:
            print(f"❌ 메시지 처리 오류: {e}")

async def ws_loop():
    global connected_once
    uri = "wss://ws.bitget.com/v2/ws/public"
    while True:
        try:
            async with websockets.connect(uri, ping_interval=20) as ws:
                sub = {"op": "subscribe", "args": [{"instType": INST_TYPE, "channel": CHANNEL, "instId": s} for s in SYMBOLS]}
                await ws.send(json.dumps(sub))
                print("✅ WS 연결됨")
                if not connected_once:
                    await notify_start()
                    connected_once = True
                while True:
                    msg = json.loads(await ws.recv())
                    if msg.get("action") in ("snapshot", "update"):
                        on_msg(msg)
        except Exception as e:
            print(f"🔌 WebSocket 오류: {e}")
            await asyncio.sleep(10)

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.create_task(ws_loop())
    loop.create_task(periodic_alert())
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=3000)).start()
    loop.run_forever()

import asyncio, json, websockets, requests, hmac, hashlib, time, base64
from datetime import datetime
import numpy as np
from websockets.exceptions import ConnectionClosedError
from flask import Flask, request
import threading

app = Flask(__name__)

API_KEY = 'bg_a9c07aa3168e846bfaa713fe9af79d14'
API_SECRET = '5be628fd41dce5eff78a607f31d096a4911d4e2156b6d66a14be20f027068043'
API_PASSPHRASE = '1q2w3e4r'
TELEGRAM_TOKEN = '7776435078:AAFsM_jIDSx1Eij4YJyqJp-zEDtQVtKohnU'
TELEGRAM_CHAT_ID = '1797494660'

SYMBOLS = {
    "BTCUSDT": {"leverage": 10, "amount": 150},
    "ETHUSDT": {"leverage": 7, "amount": 120}
}
INST_TYPE = "USDT-FUTURES"
CHANNEL = "candle15m"
MAX_CANDLES = 100
candles = {symbol: [] for symbol in SYMBOLS}

cci_values = {}
adx_values = {}
last_prices = {}

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

def sign_request(timestamp, method, path):
    pre_hash = f"{timestamp}{method}{path}"
    sign = hmac.new(API_SECRET.encode(), pre_hash.encode(), hashlib.sha256).hexdigest()
    return sign

def get_balance():
    url_path = "/api/mix/v1/account/account?marginCoin=USDT"
    method = "GET"
    timestamp = get_server_timestamp()
    sign = sign_request(timestamp, method, url_path)
    headers = {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": API_PASSPHRASE
    }
    url = f"https://api.bitget.com{url_path}"
    try:
        response = requests.get(url, headers=headers).json()
        return float(response['data']['available'])
    except:
        return None

async def notify_startup():
    balance = get_balance()
    msg = "📥 그리고 자동매매 시작!\n"
    for sym, conf in SYMBOLS.items():
        msg += f"[{sym}] 금액: ${conf['amount']} | 레버리지: {conf['leverage']}번\n"
    msg += f"\n💰 USDT 잔액: {balance} USDT" if balance is not None else "\n💰 USDT 잔액 확인 오류"
    await send_telegram_message(msg)

def calculate_cci(data):
    try:
        typical_prices = [(float(o)+float(h)+float(l))/3 for o,h,l in zip(data[:,1], data[:,2], data[:,3])]
        ma = np.mean(typical_prices)
        md = np.mean(np.abs(typical_prices - ma))
        return (typical_prices[-1] - ma) / (0.015 * md)
    except:
        return None

def calculate_adx(data):
    try:
        highs = data[:,2].astype(float)
        lows = data[:,3].astype(float)
        closes = data[:,4].astype(float)
        tr = np.maximum(highs[1:], closes[:-1]) - np.minimum(lows[1:], closes[:-1])
        plus_dm = np.where((highs[1:] - highs[:-1]) > (lows[:-1] - lows[1:]), highs[1:] - highs[:-1], 0)
        minus_dm = np.where((lows[:-1] - lows[1:]) > (highs[1:] - highs[:-1]), lows[:-1] - lows[1:], 0)
        tr_smooth = np.mean(tr[-5:])
        plus_di = 100 * (np.mean(plus_dm[-5:]) / tr_smooth)
        minus_di = 100 * (np.mean(minus_dm[-5:]) / tr_smooth)
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        return dx
    except:
        return None

def handle_new_candle(symbol, candle):
    ts, o, h, l, c, v = candle
    candles[symbol].append([ts, o, h, l, c, v])
    if len(candles[symbol]) > MAX_CANDLES:
        candles[symbol].pop(0)
    np_data = np.array(candles[symbol])
    cci_values[symbol] = calculate_cci(np_data[-15:])
    adx_values[symbol] = calculate_adx(np_data[-6:])
    last_prices[symbol] = float(c)

async def periodic_telegram_alert():
    await asyncio.sleep(10)
    while True:
        try:
            msg = "⏰ 1시간마다 자동 알림\n"
            for symbol in SYMBOLS:
                price = last_prices.get(symbol, 'N/A')
                cci = cci_values.get(symbol, 'N/A')
                adx = adx_values.get(symbol, 'N/A')
                msg += f"[{symbol}]\n가격: {price}\nCCI(14): {cci:.2f}\nADX(5): {adx:.2f}\n\n"
            await send_telegram_message(msg)
        except Exception as e:
            print(f"❌ 주기 알림 오류: {e}")
        await asyncio.sleep(3600)

def on_msg(msg):
    if isinstance(msg.get("data"), list):
        d = msg["data"][0]
        symbol = d.get("instId")
        candle = d.get("candle")
        if symbol and candle:
            handle_new_candle(symbol, candle)
            ts = int(candle[0])
            print(f"🕒 {symbol} | {datetime.fromtimestamp(ts/1000):%Y-%m-%d %H:%M:%S} | O:{candle[1]} H:{candle[2]} L:{candle[3]} C:{candle[4]} V:{candle[5]}")
    else:
        print("⚠️ WebSocket 메시지 형식 이상:", msg)

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
                print("✅ WS 연결됨 / candle15m 구독 시도")
                await notify_startup()
                while True:
                    msg = json.loads(await ws.recv())
                    if msg.get("action") in ("snapshot", "update"):
                        on_msg(msg)
        except Exception as e:
            print(f"🔌 WebSocket 연결 오류: {e} / 5초 후 재연결 시도")
            await asyncio.sleep(5)

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(ws_loop())
    loop.create_task(periodic_telegram_alert())
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=3000)).start()
    loop.run_forever()
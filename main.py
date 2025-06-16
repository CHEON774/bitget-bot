import asyncio, json, hmac, hashlib, time, requests, websockets
from datetime import datetime
import numpy as np

# === 사용자 설정 ===
API_KEY = 'bg_534f4dcd8acb22273de01247d163845e'
API_SECRET = 'df5f0c3a596070ab8f940a8faeb2ebac2fdba90b8e1e096a05bb2e01ad13cf9d'
API_PASSPHRASE = '1q2w3e4r'
BASE_URL = "https://api.bitget.com"
BOT_TOKEN = "7787612607:AAEHWXld8OqmK3OeGmo2nJdmx-Bg03h85UQ"
CHAT_ID = "1797494660"


SYMBOLS = ["BTCUSDT", "ETHUSDT"]
INST_TYPE = "USDT-FUTURES"
CANDLE_CHANNEL = "candle15m"
TICKER_CHANNEL = "ticker"
MAX_CANDLES = 150
ENTRY_CONFIG = {
    "BTCUSDT": {"amount": 150, "leverage": 10},
    "ETHUSDT": {"amount": 120, "leverage": 7}
}

# --- 상태 ---
candles = {s: [] for s in SYMBOLS}
last_ts = {s: None for s in SYMBOLS}
position = {s: None for s in SYMBOLS}

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except Exception as e:
        print(f"⚠️ 텔레그램 전송 실패: {e}")

def place_order(symbol, side, price):
    cfg = ENTRY_CONFIG[symbol]
    qty = round(cfg["amount"] * cfg["leverage"] / price, 4)
    ts = str(int(time.time() * 1000))
    path = "/api/mix/v1/order/place"
    body = {
        "symbol": symbol,
        "marginCoin": "USDT",
        "side": side,
        "orderType": "market",
        "size": str(qty),
        "productType": "umcbl"
    }
    msg = ts + "POST" + path + json.dumps(body)
    sign = hmac.new(API_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()
    headers = {
        "ACCESS-KEY": API_KEY, "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": ts, "ACCESS-PASSPHRASE": API_PASSPHRASE,
        "Content-Type": "application/json"
    }
    res = requests.post(BASE_URL + path, headers=headers, json=body)
    print(f"\n📤 주문 전송 ({side}) {symbol}: {res.status_code}")
    send_telegram(f"📤 주문: {side} {symbol}\n수량: {qty}\n응답: {res.status_code}")

def calculate_cci(c, per=14):
    if len(c) < per: return None
    tp = np.array([(float(x[2])+float(x[3])+float(x[4]))/3 for x in c[-per:]])
    ma, md = np.mean(tp), np.mean(np.abs(tp - np.mean(tp)))
    return 0 if md==0 else (tp[-1]-ma)/(0.015*md)

def calculate_adx(c, per=5):
    if len(c) < per+1: return None
    high = np.array([float(x[2]) for x in c])
    low = np.array([float(x[3]) for x in c])
    close = np.array([float(x[4]) for x in c])
    tr = np.maximum(high[1:], close[:-1]) - np.minimum(low[1:], close[:-1])
    pd = np.where((high[1:]-high[:-1])>(low[:-1]-low[1:]), np.maximum(high[1:]-high[:-1],0),0)
    md = np.where((low[:-1]-low[1:])>(high[1:]-high[:-1]), np.maximum(low[:-1]-low[1:],0),0)
    atr = np.mean(tr[-per:]); pdi = 100*(np.mean(pd[-per:])/atr) if atr else 0
    mdi = 100*(np.mean(md[-per:])/atr) if atr else 0
    return abs(pdi-mdi)/(pdi+mdi)*100 if (pdi+mdi)!=0 else 0

def handle_candle(symbol, d):
    ts = int(d[0]); c = candles[symbol]
    bar = [ts, d[1], d[2], d[3], d[4], d[5]]
    if c and c[-1][0]==ts: c[-1]=bar
    else:
        c.append(bar); 
        if len(c)>MAX_CANDLES: c.pop(0)
        if len(c)>=20:
            prev = c[-2]
            if last_ts[symbol]==prev[0]: return
            last_ts[symbol]=prev[0]
            cci, adx = calculate_cci(c[:-1]), calculate_adx(c[:-1])
            print(f"\n✅ {symbol} 15m완성 CCI:{cci:.2f} ADX:{adx:.2f}")
            send_telegram(f"✅ {symbol} 변동 알림\nCCI(14): {cci:.2f}\nADX(5): {adx:.2f}")
            if cci and adx and cci>100 and adx>25 and position[symbol] is None:
                entry = float(prev[4])
                position[symbol] = {"entry":entry, "trail_active":False, "max_price":entry}
                place_order(symbol, "open_long", entry)
                send_telegram(f"🚀 {symbol} 진입 @ {entry:.2f}")

def handle_ticker(symbol, d):
    data = d[0] if isinstance(d,list) else d
    if 'lastPr' not in data: return
    current = float(data['lastPr'])
    pos = position[symbol]
    if not pos: return
    entry = pos["entry"]
    if not pos["trail_active"]:
        if current >= entry * 1.02:
            pos["trail_active"] = True
            pos["max_price"]=current
            pos["trail_stop"]=current*0.997
            send_telegram(f"🎯 트레일링 시작 {symbol}\n+2% 도달 @ {current:.2f}\n스탑: {pos['trail_stop']:.2f}")
    else:
        pos["max_price"] = max(pos["max_price"], current)
        pos["trail_stop"] = pos["max_price"]*0.997
        if current <= pos["trail_stop"]:
            place_order(symbol, "close_long", current)
            profit = (current - entry) / entry * 100
            send_telegram(f"📤 {symbol} 청산 @ {current:.2f}\n수익률: {profit:.2f}%")
            position[symbol] = None

async def ws_loop():
    uri="wss://ws.bitget.com/v2/ws/public"
    while True:
        try:
            async with websockets.connect(uri, ping_interval=20, ping_timeout=30) as ws:
                subs = [{"instType":INST_TYPE,"channel":CANDLE_CHANNEL,"instId":s} for s in SYMBOLS] + \
                       [{"instType":INST_TYPE,"channel":TICKER_CHANNEL,"instId":s} for s in SYMBOLS]
                await ws.send(json.dumps({"op":"subscribe","args":subs}))
                print("✅ WebSocket 연결 및 구독 완료")
                while True:
                    try:
                        raw = await ws.recv()
                        msg = json.loads(raw)
                        if 'data' not in msg: continue
                        sym = msg['arg']['instId']
                        ch = msg['arg']['channel']
                        if ch==CANDLE_CHANNEL: handle_candle(sym, msg['data'][0])
                        elif ch==TICKER_CHANNEL: handle_ticker(sym, msg['data'])
                    except Exception as e:
                        print("⚠️ 메시지 처리 오류:", e)
                        break
        except Exception as e:
            print("❌ WS 연결 오류:", e)
        print("🔁 5초 후 재연결 시도...")
        await asyncio.sleep(5)

if __name__=="__main__":
    asyncio.run(ws_loop())

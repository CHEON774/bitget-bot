import time, hmac, hashlib, base64, json, requests

# API 인증 정보
API_KEY = "bg_534f4dcd8acb22273de01247d163845e"
API_SECRET = "df5f0c3a596070ab8f940a8faeb2ebac2fdba90b8e1e096a05bb2e01ad13cf9d"
API_PASSPHRASE = "1q2w3e4r"

# 텔레그램 설정
TELEGRAM_TOKEN = "7787612607:AAEHWXld8OqmK3OeGmo2nJdmx-Bg03h85UQ"
TELEGRAM_CHAT_ID = "1797494660"

import asyncio, websockets

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg})

def get_headers(method, path, query_string="", body=""):
    timestamp = str(int(time.time() * 1000))
    full_path = path + (f"?{query_string}" if query_string else "")
    pre_hash = timestamp + method.upper() + full_path + body
    sig = base64.b64encode(hmac.new(API_SECRET.encode(), pre_hash.encode(), hashlib.sha256).digest()).decode()
    return {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sig,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": API_PASSPHRASE,
        "Content-Type": "application/json"
    }

def check_balance():
    marginCoin = "USDT"
    path = "/api/mix/v1/account/account"
    query = f"marginCoin={marginCoin}"
    url = f"https://api.bitget.com{path}?{query}"
    headers = get_headers("GET", path, query_string=query)
    res = requests.get(url, headers=headers)
    if res.status_code == 200:
        d = res.json().get("data", {})
        msg = f"✅ 연동성공 자산: {d.get('equity')} USDT, 사용가능: {d.get('available')} USDT"
    else:
        msg = f"❌ 연동실패 코드:{res.status_code} 본문:{res.text}"
    print(msg)
    send_telegram(msg)

async def ws_loop():
    uri = "wss://ws.bitget.com/v2/ws/public"
    while True:
        try:
            async with websockets.connect(uri, ping_interval=30, ping_timeout=10) as ws:
                await ws.send(json.dumps({"op":"subscribe","args":[{"instType":"UMCBL","channel":"ticker","instId":"BTCUSDT"}]}))
                while True:
                    msg = await ws.recv()
        except Exception as e:
            print("WS 오류:", e)
            await asyncio.sleep(5)

if __name__ == "__main__":
    check_balance()
    asyncio.run(ws_loop())


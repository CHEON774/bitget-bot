import time, hmac, hashlib, base64, json, requests

# ✅ Bitget API 인증
API_KEY = "bg_534f4dcd8acb22273de01247d163845e"
API_SECRET = "df5f0c3a596070ab8f940a8faeb2ebac2fdba90b8e1e096a05bb2e01ad13cf9d"
API_PASSPHRASE = "1q2w3e4r"

# ✅ 텔레그램 정보
TELEGRAM_TOKEN = "7787612607:AAEHWXld8OqmK3OeGmo2nJdmx-Bg03h85UQ"
TELEGRAM_CHAT_ID = "1797494660"

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
    except Exception as e:
        print("텔레그램 전송 실패:", e)

def get_headers(method, path, query_string="", body=""):
    timestamp = str(int(time.time() * 1000))
    pre_hash = timestamp + method.upper() + path + (f"?{query_string}" if query_string else "") + body
    signature = base64.b64encode(hmac.new(API_SECRET.encode(), pre_hash.encode(), hashlib.sha256).digest()).decode()
    return {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": signature,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": API_PASSPHRASE,
        "Content-Type": "application/json"
    }

def check_balance():
    symbol = "BTCUSDT"
    marginCoin = "USDT"
    query = f"symbol={symbol}&marginCoin={marginCoin}"
    path = "/api/mix/v1/account/account"
    url = f"https://api.bitget.com{path}?{query}"
    headers = get_headers("GET", path, query_string=query)

    res = requests.get(url, headers=headers)
    if res.status_code == 200:
        data = res.json().get("data", {})
        msg = (
            "✅ Bitget API 연동 성공\n"
            f"📊 잔고 정보 – 총 자산: {data.get('equity','N/A')} USDT, "
            f"사용 가능: {data.get('available','N/A')} USDT"
        )
        print(msg)
        send_telegram(msg)
    else:
        err = f"❌ API 연동 실패: 코드 {res.status_code}, 본문: {res.text}"
        print(err)
        send_telegram(err)

if __name__ == "__main__":
    check_balance()


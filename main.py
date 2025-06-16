
import time, hmac, hashlib, json, requests

# 🔐 Bitget API 정보 (직접 입력)
API_KEY = 'bg_534f4dcd8acb22273de01247d163845e'
API_SECRET = 'df5f0c3a596070ab8f940a8faeb2ebac2fdba90b8e1e096a05bb2e01ad13cf9d'
API_PASSPHRASE = '1q2w3e4r'

# 📩 텔레그램 정보 (직접 입력)
BOT_TOKEN = "7787612607:AAEHWXld8OqmK3OeGmo2nJdmx-Bg03h85UQ"
CHAT_ID = "1797494660"

# 텔레그램 전송 함수
def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
    except Exception as e:
        print("텔레그램 전송 실패:", e)

# Bitget API 헤더 만들기
def get_headers(method, path, body=''):
    timestamp = str(int(time.time() * 1000))
    message = f"{timestamp}{method}{path}{body}"
    sign = hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
    return {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": API_PASSPHRASE,
        "Content-Type": "application/json"
    }

# 잔고 조회 + 텔레그램 전송
def check_balance():
    symbol = "BTCUSDT"
    marginCoin = "USDT"
    path = f"/api/mix/v1/account/account?symbol={symbol}&marginCoin={marginCoin}"
    url = f"https://api.bitget.com{path}"
    headers = get_headers("GET", path)

    res = requests.get(url, headers=headers)
    if res.status_code == 200:
        data = res.json().get("data", {})
        equity = data.get("equity", "N/A")
        available = data.get("available", "N/A")
        margin = data.get("margin", "N/A")
        msg = (
            f"✅ Bitget API 연동 성공\n"
            f"📊 BTCUSDT 잔고 조회 결과\n"
            f"- 총 자산: {equity} USDT\n"
            f"- 사용 가능: {available} USDT\n"
            f"- 유지 증거금: {margin} USDT"
        )
        print(msg)
        send_telegram(msg)
    else:
        err = f"❌ Bitget API 연동 실패\n응답 코드: {res.status_code}\n본문: {res.text}"
        print(err)
        send_telegram(err)

if __name__ == "__main__":
    check_balance()

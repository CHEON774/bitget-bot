import time
import hmac
import hashlib
import base64
import requests
import json

# ✅ 사용자 설정값
API_KEY = "bg_a9c07aa3168e846bfaa713fe9af79d14"
API_SECRET = "5be628fd41dce5eff78a607f31d096a4911d4e2156b6d66a14be20f027068043"
API_PASSPHRASE = "1q2w3e4r"
TELEGRAM_TOKEN = "7776435078:AAFsM_jIDSx1Eij4YJyqJp-zEDtQVtKohnU"
TELEGRAM_CHAT_ID = "1797494660"
BASE_URL = "https://api.bitget.com"

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
    except Exception as e:
        print(f"⚠️ 텔레그램 전송 실패: {e}")

def get_headers(method, path, query_string="", body=""):
    timestamp = str(int(time.time() * 1000))
    request_path = path + (f"?{query_string}" if query_string else "")
    pre_hash = f"{timestamp}{method.upper()}{request_path}{body}"
    print("\n🔍 get_headers 호출함")
    print(f"📄 pre-hash 문자열: {pre_hash}")
    sign = base64.b64encode(
        hmac.new(API_SECRET.encode(), pre_hash.encode(), hashlib.sha256).digest()
    ).decode()

    return {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": API_PASSPHRASE,
        "Content-Type": "application/json"
    }

def check_balance():
    method = "GET"
    path = "/api/mix/v1/account/account"
    query_string = "marginCoin=USDT"
    url = f"{BASE_URL}{path}?{query_string}"
    headers = get_headers(method, path, query_string)

    response = requests.get(url, headers=headers)
    print("\n📡 API 요청 전송됨")
    print(f"🔗 URL: {url}")
    print(f"📬 응답 코드: {response.status_code}")
    print(f"📦 응답 본문: {response.text}")

    if response.status_code == 200:
        try:
            data = response.json()
            msg = f"✅ Bitget API 연동 성공!\n\n📊 USDT 잔고: {data['data']['available'][:8]} USDT"
        except Exception as e:
            msg = f"⚠️ JSON 파싱 실패: {e}"
    else:
        msg = f"❌ API 연동 실패\n\n코드: {response.status_code}\n본문: {response.text}"

    send_telegram(msg)

if __name__ == "__main__":
    check_balance()


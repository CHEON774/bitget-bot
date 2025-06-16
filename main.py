import time
import hmac
import hashlib
import base64
import requests

# ✅ 사용자 인증 정보 (반드시 본인 값으로 대체)
API_KEY = "bg_a9c07aa3168e846bfaa713fe9af79d14"
API_SECRET = "5be628fd41dce5eff78a607f31d096a4911d4e2156b6d66a14be20f027068043"
API_PASSPHRASE = "1q2w3e4r"
TELEGRAM_TOKEN = "7776435078:AAFsM_jIDSx1Eij4YJyqJp-zEDtQVtKohnU"
TELEGRAM_CHAT_ID = "1797494660"

# ✅ 텔레그램 알림 함수
def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
    except Exception as e:
        print("❌ 텔레그램 전송 오류:", e)

# ✅ 서명 및 헤더 생성 함수
def get_headers(method, path, query_string="", body=""):
    timestamp = str(int(time.time() * 1000))
    request_path = path + (f"?{query_string}" if query_string else "")
    pre_hash = f"{timestamp}{method.upper()}{request_path}{body}"
    print("🔍 get_headers 호출됨")
    print("📄 pre-hash 문자열:", pre_hash)

    try:
        sign = base64.b64encode(
            hmac.new(API_SECRET.encode(), pre_hash.encode(), hashlib.sha256).digest()
        ).decode()
    except Exception as e:
        print("❌ 서명 생성 오류:", e)
        send_telegram("❌ 서명 생성 오류 발생")
        raise

    return {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": API_PASSPHRASE,
        "Content-Type": "application/json"
    }

# ✅ 잔고 조회 함수
def check_balance():
    method = "GET"
    path = "/api/mix/v1/account/account"
    query_string = "marginCoin=USDT"
    url = f"https://api.bitget.com{path}?{query_string}"
    headers = get_headers(method, path, query_string)

    print("📡 API 요청 전송됨")
    print("🔗 URL:", url)
    try:
        response = requests.get(url, headers=headers)
        print("📬 응답 코드:", response.status_code)
        print("📦 응답 본문:", response.text)
        if response.status_code == 200:
            send_telegram("✅ API 연동 성공\n\n" + response.text)
        else:
            send_telegram(f"❌ API 연동 실패\n\n코드: {response.status_code}\n본문: {response.text}")
    except Exception as e:
        print("❌ API 호출 오류:", e)
        send_telegram("❌ API 호출 중 오류 발생")

# ✅ 실행
if __name__ == "__main__":
    check_balance()



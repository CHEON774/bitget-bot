import time
import hmac
import hashlib
import base64
import requests

API_KEY = "bg_a9c07aa3168e846bfaa713fe9af79d14"
API_SECRET = "5be628fd41dce5eff78a607f31d096a4911d4e2156b6d66a14be20f027068043"
API_PASSPHRASE = "1q2w3e4r"
TELEGRAM_TOKEN = "7776435078:AAFsM_jIDSx1Eij4YJyqJp-zEDtQVtKohnU"
TELEGRAM_CHAT_ID = "1797494660"

# ✅ 텔레그램 전송 함수
def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
    except Exception as e:
        print(f"⚠️ 텔레그램 전송 실패: {e}")

# ✅ Bitget 서명 및 헤더 생성 함수
def get_headers(method, path, query_string="", body=""):
    timestamp = str(int(time.time() * 1000))
    request_path = path + (f"?{query_string}" if query_string else "")
    pre_hash = f"{timestamp}{method.upper()}{request_path}{body}"

    print("🔍 get_headers 호출됨")
    print(f"📄 pre-hash 문자열: {pre_hash}")  # 디버깅 핵심

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

# ✅ 잔고 확인 함수 (디버깅용)
def check_balance():
    try:
        path = "/api/mix/v1/account/account"
        method = "GET"
        query_string = "marginCoin=USDT"
        url = f"https://api.bitget.com{path}?{query_string}"

        headers = get_headers(method, path, query_string=query_string)
        res = requests.get(url, headers=headers)

        if res.status_code == 200:
            data = res.json()
            send_telegram(f"✅ 잔고 정보: {data}")
        else:
            err = f"❌ API 연동 실패\n코드: {res.status_code}\n본문: {res.text}"
            print(err)
            send_telegram(err)
    except Exception as e:
        err = f"❌ 예외 발생: {e}"
        print(err)
        send_telegram(err)

# 실행
check_balance()
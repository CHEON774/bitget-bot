import time
import hmac
import hashlib
import base64
import requests

# ✅ 사용자 설정 (반드시 자신의 정보로 대체)
API_KEY = "bg_a9c07aa3168e846bfaa713fe9af79d14"
API_SECRET = "5be628fd41dce5eff78a607f31d096a4911d4e2156b6d66a14be20f027068043"
API_PASSPHRASE = "1q2w3e4r"

# ✅ 서버 시간 동기화 함수 (Bitget 권장)
def get_server_timestamp():
    try:
        res = requests.get("https://api.bitget.com/api/spot/v1/public/time")
        if res.status_code == 200:
            return str(res.json()["data"])
        else:
            return str(int(time.time() * 1000))
    except:
        return str(int(time.time() * 1000))

# ✅ HMAC 서명 생성 함수
def get_headers(method, path, query_string="", body=""):
    timestamp = get_server_timestamp()
    request_path = f"{path}?{query_string}" if query_string else path
    pre_hash = f"{timestamp}{method.upper()}{request_path}{body}"
    print("📄 pre-hash:", pre_hash)
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

# ✅ Bitget 선물 계정 잔고 조회 함수
def check_futures_balance():
    method = "GET"
    path = "/api/mix/v1/account/account"
    query_string = "marginCoin=USDT"
    url = f"https://api.bitget.com{path}?{query_string}"
    headers = get_headers(method, path, query_string)

    print("\n📡 요청 URL:", url)
    res = requests.get(url, headers=headers)
    print("📬 상태 코드:", res.status_code)
    print("📦 응답:", res.text)

if __name__ == "__main__":
    check_futures_balance()



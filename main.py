import time
import hmac
import base64
import requests

# ✅ [1] API 정보 입력 (이름 통일)
API_KEY = "bg_a9c07aa3168e846bfaa713fe9af79d14"
API_SECRET = "5be628fd41dce5eff78a607f31d096a4911d4e2156b6d66a14be20f027068043"
API_PASSPHRASE = "1q2w3e4r"
BASE_URL = "https://api.bitget.com"

# ✅ [2] 타임스탬프 생성 함수
def get_timestamp():
    return int(time.time() * 1000)

# ✅ [3] 서명 생성 함수
def sign_message(message, secret_key):
    mac = hmac.new(bytes(secret_key, encoding='utf8'),
                   bytes(message, encoding='utf-8'),
                   digestmod='sha256')
    return base64.b64encode(mac.digest()).decode()

# ✅ [4] 파라미터 → 쿼리 문자열 변환
def parse_params_to_str(params):
    if not params:
        return ''
    params = [(key, val) for key, val in params.items()]
    params.sort(key=lambda x: x[0])
    return '?' + '&'.join([f"{k}={v}" for k, v in params])

# ✅ [5] 메인 요청
if __name__ == '__main__':
    method = "GET"
    endpoint = "/api/v2/account/all-account-balance"
    params = {}  # 이 API는 별도 파라미터 없음
    query_string = parse_params_to_str(params)
    request_path = endpoint + query_string
    body = ""

    timestamp = get_timestamp()
    pre_hash = f"{timestamp}{method.upper()}{request_path}{body}"
    signature = sign_message(pre_hash, API_SECRET)

    # ✅ 변수명 통일 (PASSPHRASE → API_PASSPHRASE)
    headers = {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": signature,
        "ACCESS-TIMESTAMP": str(timestamp),
        "ACCESS-PASSPHRASE": API_PASSPHRASE,
        "locale": "en-US"
    }

    url = BASE_URL + request_path
    response = requests.get(url, headers=headers)

    # ✅ 결과 출력
    print("📡 요청 URL:", url)
    print("📄 Pre-hash:", pre_hash)
    print("📬 상태 코드:", response.status_code)
    print("📦 응답:", response.text)



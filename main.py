import time
import hmac
import hashlib
import base64
import requests

# 👉 여기에 너의 API 키 정보 입력
api_key = "너의_API_KEY"
api_secret = "너의_API_SECRET"
passphrase = "너의_API_PASSPHRASE"

# 요청 관련 변수
timestamp = str(int(time.time() * 1000))  # 밀리초 단위 타임스탬프
method = "GET"
request_path = "/api/mix/v1/account/account"
query_string = "marginCoin=USDT"
full_path = f"{request_path}?{query_string}"

# pre-hash 조합 (GET 방식은 ?query 포함)
pre_hash = f"{timestamp}{method}{full_path}"

# 서명 생성
signature = base64.b64encode(
    hmac.new(api_secret.encode(), pre_hash.encode(), hashlib.sha256).digest()
).decode()

# 헤더 구성
headers = {
    "ACCESS-KEY": api_key,
    "ACCESS-SIGN": signature,
    "ACCESS-TIMESTAMP": timestamp,
    "ACCESS-PASSPHRASE": passphrase,
    "Content-Type": "application/json"
}

# 요청 전송
url = f"https://api.bitget.com{full_path}"
response = requests.get(url, headers=headers)

# 결과 출력
print("📡 요청 URL:", url)
print("📄 Pre-hash:", pre_hash)
print("📬 상태 코드:", response.status_code)
print("📦 응답:", response.text)



import requests
import time
import hmac
import hashlib
import base64

# Bitget API 정보 (임시로 비워둠 – .env로 관리 가능)
API_KEY = 'your_api_key_here'
API_SECRET = 'your_api_secret_here'
API_PASSPHRASE = 'your_passphrase_here'

def get_timestamp():
    return str(int(time.time() * 1000))

def sign(message, secret_key):
    mac = hmac.new(
        bytes(secret_key, encoding='utf8'),
        bytes(message, encoding='utf-8'),
        digestmod='sha256'
    )
    return base64.b64encode(mac.digest()).decode()

def get_server_time():
    url = "https://api.bitget.com/api/v2/public/time"
    try:
        res = requests.get(url)
        res.raise_for_status()
        data = res.json()
        print("🕒 Bitget 서버 시간:", data.get("data", {}))
    except Exception as e:
        print("❌ 서버 시간 조회 실패:", e)

if __name__ == "__main__":
    print("✅ Bitget 자동매매 봇 실행 시작")
    get_server_time()

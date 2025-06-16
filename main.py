import time
import hmac
import base64
import requests
import hashlib

API_KEY = 'bg_a9c07aa3168e846bfaa713fe9af79d14'
API_SECRET = '5be628fd41dce5eff78a607f31d096a4911d4e2156b6d66a14be20f027068043'
API_PASSPHRASE = '1q2w3e4r'
BASE_URL = "https://api.bitget.com"

def get_timestamp():
    return str(int(time.time() * 1000))

def sign(message, secret_key):
    mac = hmac.new(bytes(secret_key, encoding='utf8'),
                   bytes(message, encoding='utf-8'),
                   digestmod='sha256')
    return base64.b64encode(mac.digest()).decode()

def get_all_balance():
    timestamp = get_timestamp()
    method = "GET"
    request_path = "/api/v2/account/all-account-balance"
    body = ""

    pre_hash = timestamp + method + request_path + body
    signature = sign(pre_hash, API_SECRET)

    headers = {
        'ACCESS-KEY': API_KEY,
        'ACCESS-SIGN': signature,
        'ACCESS-TIMESTAMP': timestamp,
        'ACCESS-PASSPHRASE': API_PASSPHRASE,
        'locale': 'en-US'
    }

    url = BASE_URL + request_path
    print("🧪 pre_hash:", pre_hash)
    print("🧪 SIGN:", signature)
    print("🧪 URL:", url)
    print("🧪 HEADERS:", headers)

    try:
        res = requests.get(url, headers=headers)
        res.raise_for_status()
        print("✅ 잔액 조회 성공:", res.json())
    except requests.exceptions.RequestException as e:
        print("❌ 잔액 조회 실패:", e)

if __name__ == "__main__":
    get_all_balance()


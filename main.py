import time, hmac, hashlib, base64, json, requests

# ✅ API 인증 정보 입력
API_KEY = "bg_a9c07aa3168e846bfaa713fe9af79d14"
API_SECRET = "5be628fd41dce5eff78a607f31d096a4911d4e2156b6d66a14be20f027068043"
API_PASSPHRASE = "1q2w3e4r"

# ✅ 텔레그램 봇 정보 입력
TELEGRAM_TOKEN = "Y7776435078:AAFsM_jIDSx1Eij4YJyqJp-zEDtQVtKohnU"
TELEGRAM_CHAT_ID = "1797494660"

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
    except Exception as e:
        print(f"❌ 텔레그램 전송 실패: {e}")

# ✅ Bitget 전용 서명 생성 함수
def get_headers(method, path, query_string="", body=""):
    timestamp = str(int(time.time() * 1000))
    request_path = path
    if query_string:
        request_path += "?" + query_string
    pre_hash = timestamp + method.upper() + request_path + body
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

# ✅ 잔고 조회 요청
def check_balance():
    marginCoin = "USDT"
    path = "/api/mix/v1/account/account"
    query = f"marginCoin={marginCoin}"
    url = f"https://api.bitget.com{path}?{query}"
    headers = get_headers("GET", path, query_string=query, body="")

    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        data = response.json().get("data", {})
        msg = (
            f"✅ 연동 성공!\n"
            f"총 자산: {data.get('equity')} USDT\n"
            f"사용 가능: {data.get('available')} USDT"
        )
    else:
        msg = f"❌ 연동실패\n코드: {response.status_code}\n본문: {response.text}"

    print(msg)
    send_telegram(msg)

if __name__ == "__main__":
    check_balance()


import time, hmac, hashlib, base64, requests

# ✅ API 인증 정보 입력
API_KEY = "bg_a9c07aa3168e846bfaa713fe9af79d14"
API_SECRET = "5be628fd41dce5eff78a607f31d096a4911d4e2156b6d66a14be20f027068043"
API_PASSPHRASE = "1q2w3e4r"

# ✅ 텔레그램 봇 정보 입력
TELEGRAM_TOKEN = "7776435078:AAFsM_jIDSx1Eij4YJyqJp-zEDtQVtKohnU"
TELEGRAM_CHAT_ID = "1797494660"

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
    except Exception as e:
        print(f"❌ 텔레그램 전송 실패: {e}")

# ✅ Bitget 서명 생성 함수
def get_headers(method, path, query_string="", body=""):
    timestamp = str(int(time.time() * 1000))
    request_path = path + (f"?{query_string}" if query_string else "")
    pre_hash = f"{timestamp}{method.upper()}{request_path}{body}"
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

# ✅ 잔고 조회 + 알림
def check_balance():
    method = "GET"
    path = "/api/mix/v1/account/account"
    query = "marginCoin=USDT"
    url = f"https://api.bitget.com{path}?{query}"
    headers = get_headers(method, path, query, "")

    res = requests.get(url, headers=headers)
    if res.status_code == 200:
        data = res.json().get("data", {})
        equity = data.get("equity", "N/A")
        available = data.get("available", "N/A")
        msg = (
            f"✅ Bitget API 연동 성공\n"
            f"총 자산: {equity} USDT\n"
            f"사용 가능: {available} USDT"
        )
    else:
        msg = f"❌ API 연동 실패\n코드: {res.status_code}\n본문: {res.text}"

    print(msg)
    send_telegram(msg)

if __name__ == "__main__":
    check_balance()


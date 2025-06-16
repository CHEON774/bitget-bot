import time, hmac, hashlib, base64, requests

API_KEY = "bg_a9c07aa3168e846bfaa713fe9af79d14"
API_SECRET = "5be628fd41dce5eff78a607f31d096a4911d4e2156b6d66a14be20f027068043"
API_PASSPHRASE = "1q2w3e4r"
TELEGRAM_TOKEN = "7776435078:AAFsM_jIDSx1Eij4YJyqJp-zEDtQVtKohnU"
TELEGRAM_CHAT_ID = "1797494660"

# ✨ 텔레그램 메시지 전송 함수
def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
    except Exception as e:
        print(f"⚠️ Telegram send error: {e}")

# ✅ Bitget API 서명 기능 (GET에서 query_string 제외하고 pre_hash생성)
def get_headers(method, path, query_string="", body=""):
    timestamp = str(int(time.time() * 1000))
    pre_hash = f"{timestamp}{method.upper()}{path}{body}"

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

# ✅ 잔고 조회 함수 (GET)
def check_balance():
    method = "GET"
    path = "/api/mix/v1/account/account"
    query_string = "marginCoin=USDT"
    url = f"https://api.bitget.com{path}?{query_string}"
    headers = get_headers(method, path)

    res = requests.get(url, headers=headers)
    if res.status_code == 200:
        send_telegram(f"🌟 잔고 조회 성공: {res.text}")
    else:
        err = f"\n❌ API 연동 실패\n\n코드: {res.status_code}\n본문: {res.text}"
        print(err)
        send_telegram(err)

if __name__ == "__main__":
    check_balance()

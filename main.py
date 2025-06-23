from flask import Flask, request
import requests

TELEGRAM_TOKEN = "7776435078:AAFsM_jIDSx1Eij4YJyqJp-zEDtQVtKohnU"
TELEGRAM_CHAT_ID = "1797494660"
app = Flask(__name__)

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": msg}
    requests.post(url, data=data)

@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def hook():
    msg = request.get_json()
    if "message" in msg:
        chat_id = msg["message"]["chat"]["id"]
        text = msg["message"].get("text", "")
        if str(chat_id) != str(TELEGRAM_CHAT_ID): return "no"
        # 여기서 원하는 명령어 처리
        if text == "/시작":
            send_telegram("✅ 자동매매 시작")
        elif text == "/중지":
            send_telegram("⛔ 자동매매 중지")
        elif text == "/상태":
            send_telegram("📊 상태 메시지 예시!")
    return "ok"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)


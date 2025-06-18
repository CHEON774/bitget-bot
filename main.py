import os, json
from flask import Flask, request
import requests

app = Flask(__name__)

TELEGRAM_TOKEN = '7776435078:AAFsM_jIDSx1Eij4YJyqJp-zEDtQVtKohnU'
TELEGRAM_CHAT_ID = '1797494660'

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message.encode("utf-8")})
    except Exception as e:
        print("❌ 텔레그램 전송 실패:", e)

@app.route("/텔레그램", methods=["POST"])
def telegram_webhook():
    try:
        data = request.json
        print("✅ 받은 데이터:", data)

        msg = data.get("message", {})
        text = msg.get("text", "")
        if not text:
            return "no message", 200

        if "시작" in text:
            send_telegram("✅ 자동매매 시작합니다!")
        elif "중지" in text:
            send_telegram("🛑 자동매매 중단합니다!")
        elif "상태" in text:
            send_telegram("📈 매매 상태는 정상입니다.")
        elif "포지션" in text:
            send_telegram("📌 포지션 없음 (디버그용 응답)")
        elif "수익률" in text:
            send_telegram("💰 수익률 계산 기능은 추후 적용 예정")
        return "ok", 200
    except Exception as e:
        print("❌ 웹훅 처리 중 오류:", e)
        return "error", 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"🚀 Flask 서버 실행 중... 포트: {port}")
    app.run(host="0.0.0.0", port=port)


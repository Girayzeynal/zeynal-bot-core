import os
from flask import Flask, request, jsonify
import requests
from faz17_market_fetcher import fetch_market_data  # Veri çekme fonksiyonunu içe aktar

# Ortam değişkenlerinden bot tokenını al (Fly.io secret olarak ayarlanmalı)
TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN ortam değişkeni tanımlı değil. Lütfen Fly.io secrets ile ayarlayın.")

app = Flask(__name__)

# Telegram webhook endpoint - token'ı URL path içine ekleyerek tanımlıyoruz
@app.route(f"/{TOKEN}", methods=["POST"])
def telegram_webhook():
    # Telegram'dan gelen JSON güncellemesini al
    update = request.get_json(force=True)
    # Varsayılan bir cevap oluştur (Telegram'a iletilecek OK)
    response = {"status": "ok"}

    if not update:
        return jsonify(response)

    # Sadece mesaj içeren güncellemeleri ele alalım
    if "message" in update:
        chat_id = update["message"]["chat"]["id"]
        text = update["message"].get("text", "")

        # Basit komut kontrolü
        if text.startswith("/start"):
            reply_text = "Bot başarıyla çalışıyor."
        elif text.strip().lower() == "market":
            # "market" anahtar kelimesi gelirse, piyasa verisini çek
            data = fetch_market_data()
            # Veri tipine göre cevap metnini hazırla (örn: sözlük ise formatla)
            reply_text = f"Piyasa verisi: {data}"
        else:
            reply_text = "Anlaşılamayan komut."

        # Hazırlanan cevabı Telegram API'ını kullanarak gönder
        send_message_url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        payload = {"chat_id": chat_id, "text": reply_text}
        requests.post(send_message_url, json=payload)

    return jsonify(response)

if __name__ == "__main__":
    # Fly.io 'PORT' değişkenini kullan (tanımlı değilse 8080)
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port) 

import os
import logging
from flask import Flask, request
import requests

# Engine modüllerini paket yapısı ile içe aktar
from faz13_engine.faz13_orchestrator import run_match_analysis
from faz17_engine.faz17_market_fetcher import fetch_market_data
from faz22_engine.faz22_meta_engine import faz22_meta_engine

# Genel logger ayarı
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("zeynal-bot-core")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    log.warning("BOT_TOKEN boş. Fly secrets üzerinden BOT_TOKEN ayarlayın.")

TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

def tg_send(chat_id: str, text: str) -> None:
    """
    Telegram’a mesaj gönderen yardımcı fonksiyon.
    """
    if not BOT_TOKEN:
        return
    try:
        requests.post(
            f"{TG_API}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": True,
            },
            timeout=12,
        )
    except Exception as e:
        log.warning(f"Mesaj gönderimi hatası: {e}")

def parse_mac(text: str):
    """
    /mac komutundan ligi, tarihi, ev sahibi ve deplasman takımını ayrıştırır.
    Örnek: /mac NBA | 2025-12-24 | Lakers - Warriors
    """
    import re
    MAC_RE = re.compile(
        r"^/mac\s+([A-Za-z0-9_]+)\s+\|\s*([0-9\-]+)\s+\|\s*(.+?)\s*-\s*(.+)\s*$"
    )
    m = MAC_RE.match(text.strip())
    if not m:
        return None
    league = m.group(1).upper()
    date_str = m.group(2).strip()
    home = m.group(3).strip()
    away = m.group(4).strip()
    return league, date_str, home, away

def create_app() -> Flask:
    """
    Flask uygulamasını oluşturan ve konfigüre eden fonksiyon.
    """
    app = Flask(__name__)

    @app.route("/", methods=["GET"])
    def health():
        return {"ok": True}, 200

    @app.route("/webhook", methods=["POST"])
    def webhook():
        data = request.get_json(force=True, silent=True) or {}
        msg = data.get("message") or data.get("edited_message") or {}
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        text = (msg.get("text") or "").strip()

        # Chat ID yoksa HTTP 200 döndür
        if not chat_id:
            return {"ok": True}

        # /start komutu
        if text.startswith("/start"):
            tg_send(chat_id, "Bot ayakta. Format: /mac LIG | YYYY-MM-DD | EvTakım - Deplasman")
            return {"ok": True}

        # /mac komutu
        if text.startswith("/mac"):
            parsed = parse_mac(text)
            if not parsed:
                tg_send(chat_id, "Hatalı format. Örnek: /mac NBA | 2025-12-24 | Lakers - Warriors")
                return {"ok": True}

            league, date_str, home, away = parsed
            tg_send(chat_id, f"Analiz başlıyor: {league} | {date_str} | {home} - {away}")

            # Piyasa verisini çek
            market = None
            try:
                market = fetch_market_data(league=league, date_str=date_str, home=home, away=away)
            except Exception as e:
                log.warning(f"FAZ-17 market fetch hatası: {e}")

            # Maç analizi
            analysis_result = None
            try:
                analysis_result = run_match_analysis(
                    league=league,
                    date_str=date_str,
                    home=home,
                    away=away,
                    market=market,
                )
            except Exception as e:
                log.warning(f"FAZ-13 orchestrator hatası: {e}")
                tg_send(chat_id, f"FAZ-13 orchestrator hatası: {e}")
                return {"ok": True}

            # Sonucu kullanıcıya ilet
            tg_send(chat_id, f"Analiz sonucu: {analysis_result}")
            return {"ok": True}

        # Diğer durumlar için OK döndür
        return {"ok": True}

    return app

if __name__ == "__main__":
    app = create_app()
    port = int(os.environ.get("PORT", 8080))
    # Fly.io üzerinde 0.0.0.0:PORT adresini dinler
    app.run(host="0.0.0.0", port=port) 

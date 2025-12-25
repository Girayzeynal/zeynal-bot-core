import os
import logging
from flask import Flask, request
import requests

# Orkestratör ve veri çekme fonksiyonları
from faz13_engine.faz13_orchestrator import run_match_analysis
from faz17_engine.faz17_market_fetcher import fetch_market_data
from faz17_engine.providers import fetch_sports_data
from faz22_engine.faz22_meta_engine import faz22_meta_engine  # Flask konfigürasyonu için

# Genel log ayarları
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("zeynal-bot-core")

# Telegram bot token'ı Fly.io secrets ile gelmeli
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    log.warning("BOT_TOKEN tanımsız. Lütfen Fly.io secrets ile BOT_TOKEN ayarlayın.")

TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

def tg_send(chat_id: str, text: str) -> None:
    """Telegram'a mesaj gönderir."""
    if not BOT_TOKEN:
        return
    try:
        requests.post(
            f"{TG_API}/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            timeout=12,
        )
    except Exception as e:
        log.warning(f"Mesaj gönderim hatası: {e}")

def parse_mac(text: str):
    """
    /mac komutunu ayrıştırır. Format:
    /mac LIG | YYYY-MM-DD | EvTakım - Deplasman
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
    """Flask uygulamasını oluşturur ve webhook'u tanımlar."""
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

        if not chat_id:
            return {"ok": True}

        # Başlangıç komutu
        if text.startswith("/start"):
            tg_send(chat_id, "Bot ayakta. Komut formatı: /mac LIG | YYYY-MM-DD | EvTakım - Deplasman")
            return {"ok": True}

        # Maç analiz komutu
        if text.startswith("/mac"):
            parsed = parse_mac(text)
            if not parsed:
                tg_send(chat_id, "Hatalı format. Örnek: /mac NBA | 2025-12-24 | Lakers - Warriors")
                return {"ok": True}

            league, date_str, home, away = parsed
            tg_send(chat_id, f"Analiz başlıyor: {league} | {date_str} | {home} - {away}")

            # 1) Odds API'den piyasa verilerini al
            try:
                market_data = fetch_market_data(league=league, date_str=date_str, home=home, away=away)
            except Exception as e:
                log.warning(f"FAZ-17 market fetch hatası: {e}")
                market_data = None

            # 2) API‑Sports üzerinden takım ve maç istatistiklerini al
            try:
                sports_data = fetch_sports_data(league=league, date_str=date_str, home=home, away=away)
            except Exception as e:
                log.warning(f"Sports API fetch hatası: {e}")
                sports_data = None

            # 3) Verileri birleştirip analiz motoruna gönder
            combined = {"odds": market_data, "sports": sports_data}
            try:
                analysis_result = run_match_analysis(
                    league=league,
                    date_str=date_str,
                    home=home,
                    away=away,
                    market=combined,
                )
            except Exception as e:
                log.warning(f"FAZ-13 orchestrator hatası: {e}")
                tg_send(chat_id, f"FAZ-13 orchestrator hatası: {e}")
                return {"ok": True}

            # 4) Sonucu kullanıcıya ilet
            tg_send(chat_id, f"Analiz sonucu: {analysis_result}")
            return {"ok": True}

        return {"ok": True}

    return app

if __name__ == "__main__":
    app = create_app()
    port = int(os.getenv("PORT", 8080))
    # Fly.io üzerinde her zaman 0.0.0.0:PORT dinlenir
    app.run(host="0.0.0.0", port=port) 

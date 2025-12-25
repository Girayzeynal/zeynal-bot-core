import os
import logging
from flask import Flask, request
import requests

# Odds API ve spor istatistikleri için çekme fonksiyonları
from faz17_engine.faz17_market_fetcher import fetch_market_data
from faz17_engine.providers import fetch_sports_data
from faz13_engine.barem_fetcher import fetch_market_total
from faz13_engine.league_autodetect import guess_league

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("zeynal-bot-core")

# Telegram bot token'ı Fly.io secrets üzerinden alınır
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    log.warning("BOT_TOKEN tanımsız. Fly.io secrets ile BOT_TOKEN ayarlayın.")

TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

def tg_send(chat_id: str, text: str) -> None:
    """Telegram'a mesaj gönderen yardımcı fonksiyon."""
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
    /mac komutunu ayrıştırır. Format: /mac LIG | YYYY-MM-DD | EvTakım - Deplasman
    """
    import re
    mac_re = re.compile(r"^/mac\s+([A-Za-z0-9_]+)\s+\|\s*([0-9\-]+)\s+\|\s*(.+?)\s*-\s*(.+)\s*$")
    m = mac_re.match(text.strip())
    if not m:
        return None
    league = m.group(1).upper()
    date_str = m.group(2).strip()
    home = m.group(3).strip()
    away = m.group(4).strip()
    return league, date_str, home, away

def create_app() -> Flask:
    """
    Flask uygulamasını oluşturur ve webhook endpointini tanımlar.
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

        if not chat_id:
            return {"ok": True}

        # /start komutu
        if text.startswith("/start"):
            tg_send(chat_id, "Bot ayakta. Kullanım: /mac LIG | YYYY-MM-DD | EvTakım - Deplasman")
            return {"ok": True}

        # /mac komutu → maç analizi
        if text.startswith("/mac"):
            parsed = parse_mac(text)
            if not parsed:
                tg_send(chat_id, "Hatalı format. Örnek: /mac NBA | 2025-12-24 | Lakers - Warriors")
                return {"ok": True}

            league, date_str, home, away = parsed
            tg_send(chat_id, f"Analiz başlıyor: {league} | {date_str} | {home} - {away}")

            # 1) Odds API'den market verilerini çek
            try:
                odds_data = fetch_market_data(league=league, date_str=date_str, home=home, away=away)
            except Exception as e:
                log.warning(f"Market verisi çekim hatası: {e}")
                odds_data = None

            # 2) API‑Sports üzerinden takım bilgisi/istatistik verilerini çek
            try:
                sports_data = fetch_sports_data(league=league, date_str=date_str, home=home, away=away)
            except Exception as e:
                log.warning(f"Sports API verisi çekim hatası: {e}")
                sports_data = None

            # 3) Barem hesapla: FAZ‑13 barem_fetcher ile tahmini total (Base) hesaplanır
            league_family, _ = guess_league(home, away, league)
            barem = fetch_market_total(home=home, away=away, league_family=league_family)
            base = barem.get("market_total")
            band = [base - 10, base + 10] if base is not None else None

            # Örnek confidence ve risk (kullanıcı ihtiyacına göre geliştirilebilir)
            confidence = "0.50"
            risk = "-"

            # Market bilgisi – Odds API sonucundan ilk bookmaker verisi özetlenir
            market_line = None
            provider_name = None
            if odds_data and isinstance(odds_data, list) and len(odds_data) > 0:
                first_event = odds_data[0]
                if "bookmakers" in first_event and first_event["bookmakers"]:
                    bm = first_event["bookmakers"][0]
                    provider_name = bm.get("title") or bm.get("key")
                    # 'markets' alanından first outcome için line kullanılabilir
                    try:
                        outcomes = bm["markets"][0]["outcomes"]
                        if outcomes and len(outcomes) >= 2:
                            market_line = f"{outcomes[0]['name']} @ {outcomes[0]['price']}, {outcomes[1]['name']} @ {outcomes[1]['price']}"
                    except Exception:
                        pass

            # Mesajı oluştur
            response_lines = [
                f"🏀 {home} — {away}",
                f"{league} | {date_str}",
                "",
                f"🧠 Base: {base}" if base is not None else "🧠 Base: -",
                f"📦 Band: [{band[0]}, {band[1]}]" if band else "📦 Band: -",
                f"✅ Confidence: {confidence}",
                f"⚠️ Risk: {risk}",
                f"📈 Market: line={market_line}, provider={provider_name}" if provider_name else "📈 Market: -",
                "",
                "📊 Periyot Tahminleri:",
                "• 1Q: None",
                "• 2Q: None",
                "• 3Q: None",
                "• 4Q: None",
            ]
            tg_send(chat_id, "\n".join(response_lines))
            return {"ok": True}

        # Tanınmayan komutlar
        return {"ok": True}

    return app

if __name__ == "__main__":
    app = create_app()
    port = int(os.getenv("PORT", 8080))
    # Fly.io üzerinde 0.0.0.0:PORT adresi dinlenir
    app.run(host="0.0.0.0", port=port)

# main.py
import os
import re
import json
import time
import logging
from typing import Optional, Dict, Any, Tuple

from flask import Flask, request

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("zeynal-bot-core")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    log.warning("BOT_TOKEN is empty. Set it in Fly secrets: fly secrets set BOT_TOKEN=...")

# --- Safe imports (bot çökmesin diye) ---
def safe_import(path: str, name: str):
    try:
        module = __import__(path, fromlist=[name])
        return getattr(module, name)
    except Exception as e:
        log.warning(f"[IMPORT FAIL] {path}.{name} -> {e}")
        return None

# FAZ engines
run_match_analysis = safe_import("faz13_engine.faz13_orchestrator", "run_match_analysis")  # önerilen fonksiyon adı
fetch_market_data  = safe_import("faz17_engine.faz17_market_fetcher", "fetch_market_data")
faz22_meta_engine  = safe_import("faz22_engine.faz22_meta_engine", "faz22_meta_engine")   # senin isim tercihin
faz23_max          = safe_import("faz23_engine.faz23_max", "faz23_max")                   # örnek

# --- Telegram HTTP ---
import requests

TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

def tg_send(chat_id: int, text: str):
    if not BOT_TOKEN:
        return
    try:
        requests.post(f"{TG_API}/sendMessage", json={
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True
        }, timeout=12)
    except Exception as e:
        log.warning(f"sendMessage failed: {e}")

# --- Realtime Providers (stub -> senin live_providers ile bağlanacak) ---
def fetch_realtime_game_data(league: str, date_str: str, home: str, away: str) -> Dict[str, Any]:
    """
    Burayı 'live_providers' klasöründeki gerçek sağlayıcılarına bağlayacağız.
    ÇIKTI: FAZ-13'ün anlayacağı normalize edilmiş tek dict.
    """
    return {
        "league": league,
        "date": date_str,
        "home": home,
        "away": away,
        "mode": "PREMATCH",  # LIVE ise: "LIVE"
        "live": None,        # LIVE payload burada olur
        "prematch": None,    # prematch stats burada olur
        "source": "stub"
    }

# --- Parser ---
MAC_RE = re.compile(r"^/mac\s+([A-Za-z0-9_ ]+)\s*\|\s*([0-9\-]+)\s*\|\s*(.+?)\s*-\s*(.+?)\s*$")

def parse_mac(text: str) -> Optional[Tuple[str,str,str,str]]:
    m = MAC_RE.match(text.strip())
    if not m:
        return None
    league = m.group(1).strip().upper()
    date_str = m.group(2).strip()
    home = m.group(3).strip()
    away = m.group(4).strip()
    return league, date_str, home, away

# --- Flask app (Fly için) ---
app = Flask(__name__)

@app.get("/health")
def health():
    return {"ok": True, "ts": int(time.time())}

@app.post("/webhook")
def webhook():
    data = request.get_json(force=True, silent=True) or {}
    msg = data.get("message") or data.get("edited_message") or {}
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    text = (msg.get("text") or "").strip()

    if not chat_id:
        return {"ok": True}

    if text.startswith("/start"):
        tg_send(chat_id, "✅ Bot ayakta. /mac LIG | YYYY-MM-DD | Home - Away")
        return {"ok": True}

    if text.startswith("/mac"):
        parsed = parse_mac(text)
        if not parsed:
            tg_send(chat_id, "⚠️ Format: /mac NBA | 2025-12-24 | Lakers - Warriors")
            return {"ok": True}

        league, date_str, home, away = parsed
        tg_send(chat_id, f"⏳ Analiz başlıyor: {league} | {date_str} | {home} - {away}")

        # 1) realtime data
        rt = fetch_realtime_game_data(league, date_str, home, away)

        # 2) market data (opsiyonel)
        market = None
        if fetch_market_data:
            try:
                market = fetch_market_data(league=league, date_str=date_str, home=home, away=away)
            except Exception as e:
                log.warning(f"FAZ-17 market fetch failed: {e}")

        # 3) FAZ-13 analysis
        if not run_match_analysis:
            tg_send(chat_id, "❌ FAZ-13 orchestrator import edilemedi. (Package/import sorunu var)")
            return {"ok": True}

        try:
            result = run_match_analysis(
                league=league,
                date_str=date_str,
                home=home,
                away=away,
                realtime=rt,
                market=market
            )
        except TypeError:
            # Eğer senin run_match_analysis imzası farklıysa fallback:
            result = run_match_analysis(league=league, date_str=date_str, home=home, away=away)

        except Exception as e:
            tg_send(chat_id, f"❌ Analiz hatası: {e}")
            return {"ok": True}

        # 4) Format output (None temizliği)
        text_out = format_result(league, date_str, home, away, result)
        tg_send(chat_id, text_out)
        return {"ok": True}

    return {"ok": True}

def format_result(league: str, date_str: str, home: str, away: str, result: Any) -> str:
    # result dict beklenir; değilse stringe çevir
    if not isinstance(result, dict):
        return f"🏀 {home} - {away}\n{league} | {date_str}\n\n{result}"

    base = result.get("base")
    band = result.get("band")
    conf = result.get("confidence")
    risk = result.get("risk", "-")
    market = result.get("market")

    periods = result.get("periods") or {}

    def clean(v):
        return "-" if v is None else v

    lines = []
    lines.append(f"🏀 {home} - {away}")
    lines.append(f"{league} | {date_str}")
    lines.append("")
    lines.append(f"🧠 Base: {clean(base)}")
    lines.append(f"📦 Band: {clean(band)}")
    lines.append(f"✅ Confidence: {clean(conf)}")
    lines.append(f"⚠️ Risk: {clean(risk)}")
    lines.append(f"📈 Market: {clean(market)}")
    lines.append("")
    lines.append("📊 Periyot Tahminleri:")
    lines.append(f"• 1Q: {clean(periods.get('1Q'))}")
    lines.append(f"• 2Q: {clean(periods.get('2Q'))} (İY: {clean(periods.get('HT'))})")
    lines.append(f"• 3Q: {clean(periods.get('3Q'))}")
    lines.append(f"• 4Q: {clean(periods.get('4Q'))} (MS: {clean(periods.get('FT'))})")

    return "\n".join(lines)

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port) 

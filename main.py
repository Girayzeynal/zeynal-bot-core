# -*- coding: utf-8 -*-
"""
Zeynal Core AI — FINAL MAIN (Fly.io + Telegram)

- /mac LIG | YYYY-MM-DD | Home - Away
- FAZ-17 market fetch (safe)
- FAZ-13 çağrısı: SADECE team-first base + market_data (market_meta YOK)
- Webhook + polling fallback
"""

from __future__ import annotations

import os
import json
import time
import logging
import inspect
from typing import Any, Dict, Optional, Tuple, List

import telebot
from flask import Flask, request


# ================================================================
# LOGGING
# ================================================================
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("zeynal-core")


# ================================================================
# ENV
# ================================================================
BOT_TOKEN = (os.getenv("BOT_TOKEN", "") or "").strip()
WEBHOOK_URL = (os.getenv("WEBHOOK_URL", "") or "").strip()
WEBHOOK_SECRET = (os.getenv("WEBHOOK_SECRET", "") or "").strip()
PORT = int((os.getenv("PORT", "8080") or "8080").strip())
AUTO_WEBHOOK = (os.getenv("AUTO_WEBHOOK", "0") or "0").strip() in ("1", "true", "TRUE", "yes")
TG_LIMIT = int((os.getenv("TG_LIMIT", "3900") or "3900").strip())

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN missing (Fly Secrets -> BOT_TOKEN)")


# ================================================================
# BOT + FLASK
# ================================================================
bot = telebot.TeleBot(BOT_TOKEN, threaded=True)
app = Flask(__name__)


# ================================================================
# OPTIONAL IMPORTS / SAFE SURFACE
# ================================================================
def _safe_import(path: str, name: str) -> Optional[Any]:
    try:
        mod = __import__(path, fromlist=[name])
        return getattr(mod, name)
    except Exception as e:
        log.warning(f"[IMPORT] optional import failed: {path}.{name} -> {e}")
        return None


# Normalize league input (opsiyonel)
def _noop_normalize_league(x: str) -> str:
    return (x or "").strip()


_normalize_league_input = _safe_import("core.elite_league_registry", "normalize_league_input") or _noop_normalize_league

# FAZ-13
run_faz13_auto_pipeline = _safe_import("faz13_engine.faz13_orchestrator", "run_faz13_auto_pipeline")

# FAZ-17
fetch_market = _safe_import("faz17_engine.faz17_market_fetcher", "fetch_market")


# ================================================================
# JSON / UTIL
# ================================================================
def _safe_json_chunks(obj: Any) -> List[str]:
    try:
        s = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    except Exception:
        s = str(obj)
    chunks: List[str] = []
    while len(s) > TG_LIMIT:
        chunks.append(s[:TG_LIMIT])
        s = s[TG_LIMIT:]
    chunks.append(s)
    return chunks


# ================================================================
# PARSER
# ================================================================
def parse_mac_command(text: str) -> Tuple[str, str, str, str]:
    """
    /mac LIG | YYYY-MM-DD | Home - Away
    """
    raw = (text or "").replace("/mac", "", 1).strip()
    parts = [p.strip() for p in raw.split("|")]
    if len(parts) < 3:
        raise ValueError("Format: /mac LIG | YYYY-MM-DD | Home - Away")
    league_raw, date_str, teams = parts[0], parts[1], parts[2]
    if "-" not in teams:
        raise ValueError("Takım ayırıcı '-' eksik. Örn: Home - Away")
    home, away = [t.strip() for t in teams.split("-", 1)]
    if not league_raw or not date_str or not home or not away:
        raise ValueError("Eksik alan.")
    league = _normalize_league_input(league_raw)
    return league, date_str.strip(), home, away


# ================================================================
# MARKET NORMALIZE (FAZ-13 tarafı için)
# ================================================================
def _normalize_market_for_faz13(market_out: Any) -> Optional[Dict[str, Any]]:
    """
    fetch_market → Optional[dict] veya (market, meta) dönebilir.
    FAZ-13 için dict türünde market_data döndürürüz.
    """
    if not market_out:
        return None

    if isinstance(market_out, tuple) and len(market_out) == 2:
        market_data, meta = market_out
    else:
        market_data, meta = market_out, {}

    if not isinstance(market_data, dict):
        return None

    # farklı anahtarları tek tip hale getir
    line = None
    for key in ("totals_line", "total_line", "line", "totals"):
        if key in market_data and market_data.get(key) is not None:
            try:
                line = float(market_data.get(key))
                break
            except Exception:
                line = None

    norm: Dict[str, Any] = {}
    norm["totals_line"] = line
    if "provider" in market_data:
        norm["provider"] = market_data.get("provider")
    elif isinstance(meta, dict) and "provider" in meta:
        norm["provider"] = meta.get("provider")

    # kullanılabilirlik bayrağı
    norm["used"] = bool(line is not None)
    return norm


# ================================================================
# PIPELINE
# ================================================================
def run_pipeline(league: str, date_str: str, home: str, away: str) -> Dict[str, Any]:
    """
    - FAZ-17 market (opsiyonel, safe)
    - FAZ-13 team-first base (market sadece market_data olarak gider)
    """
    # --- FAZ-17 (safe) ---
    market_out = None
    if fetch_market:
        try:
            market_out = fetch_market(league, date_str, home, away)  # Optional[dict] veya (market, meta)
        except Exception as e:
            log.warning(f"[FAZ17] fetch error: {e}")

    market_data_norm = _normalize_market_for_faz13(market_out)

    # --- FAZ-13 çağrısı ---
    if not run_faz13_auto_pipeline:
        log.warning("[FAZ13] orchestrator yok; fallback üretilecek")
        return {
            "engine": "FALLBACK_CORE",
            "match": {"league": league, "date": date_str, "home": home, "away": away},
            "market": market_data_norm or {},
            "prediction": {"total": None, "band": None, "confidence": 0.0},
            "note": "FAZ-13 bulunamadı (fallback).",
        }

    # her zaman tanımlı extra_inputs (NameError biter)
    extra_inputs: Dict[str, Any] = {
        "team_stats": {},        # ileride API-SPORTS ile doldurulacak
        "injuries": {"count": 0}
    }

    # FAZ-13 imzasına göre argüman filtreleme (market_meta asla gönderilmeyecek)
    try:
        sig = inspect.signature(run_faz13_auto_pipeline)  # type: ignore
        kwargs = {
            "league": league,
            "home": home,
            "away": away,
            "date_str": date_str,
            "market_data": market_data_norm,
            "extra_inputs": extra_inputs,
        }
        filtered = {k: v for k, v in kwargs.items() if k in sig.parameters}
        out = run_faz13_auto_pipeline(**filtered)  # type: ignore
    except Exception as e:
        log.exception(f"[FAZ13] pipeline crash: {e}")
        return {
            "engine": "FALLBACK_CORE",
            "match": {"league": league, "date": date_str, "home": home, "away": away},
            "market": market_data_norm or {},
            "prediction": {"total": None, "band": None, "confidence": 0.0},
            "note": f"FAZ-13 crash: {e}",
        }

    if not isinstance(out, dict):
        return {
            "engine": "FALLBACK_CORE",
            "match": {"league": league, "date": date_str, "home": home, "away": away},
            "market": market_data_norm or {},
            "prediction": {"total": None, "band": None, "confidence": 0.0},
            "note": "FAZ-13 çıktı dict değil.",
        }

    out.setdefault("meta", {})
    out["meta"].update({"league": league, "date": date_str, "home": home, "away": away})
    return out


# ================================================================
# TELEGRAM HANDLERS
# ================================================================
@bot.message_handler(commands=["mac"])
def handle_mac(message):
    try:
        league, date_str, home, away = parse_mac_command(message.text or "")
    except Exception as e:
        bot.reply_to(message, f"❌ {e}")
        return

    out = run_pipeline(league, date_str, home, away)

    # insan-okur yanıt
    if "engine" in out and out["engine"] == "FALLBACK_CORE":
        chunks = _safe_json_chunks(out)
        for c in chunks:
            bot.reply_to(message, c)
        return

    league = out.get("league")
    base = out.get("base_pred")
    band = out.get("band")
    conf = out.get("confidence")
    risk = out.get("risk", "-")
    market = out.get("market", {})

    reply_lines = [
        f"🏀 {home} — {away}",
        f"🗓️ {league} | {date_str}",
        "",
        f"🧠 Base: {base}",
        f"📦 Band: {band}",
        f"✅ Confidence: {conf}",
        f"⚠️ Risk: {risk}",
        f"📈 Market: {{'line': {market.get('totals_line') or market.get('line')}, 'provider': {market.get('provider')}, 'used': {market.get('used')}}}",
        "",
        "📊 Periyot Tahminleri:",
        "• 1Q: None",
        "• 2Q: None (İY: None)",
        "• 3Q: None",
        "• 4Q: None (2Y: None)",
    ]
    bot.reply_to(message, "\n".join(reply_lines))


@bot.message_handler(commands=["status"])
def handle_status(message):
    st = {
        "BOT_TOKEN": bool(BOT_TOKEN),
        "WEBHOOK_URL": bool(WEBHOOK_URL),
        "FAZ_13": bool(run_faz13_auto_pipeline),
        "FAZ_17": bool(fetch_market),
    }
    bot.reply_to(message, f"🤖 Zeynal Core /status\n{json.dumps(st, ensure_ascii=False, indent=2)}")


# ================================================================
# WEBHOOK / HEALTH
# ================================================================
@app.route("/", methods=["GET"])
def health():
    return "OK", 200


@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def telegram_webhook():
    try:
        payload = request.get_json(force=True)
        update = telebot.types.Update.de_json(payload)  # IMPORTANT: no bot arg
        bot.process_new_updates([update])
        return "OK", 200
    except Exception as e:
        log.exception(f"webhook error: {e}")
        return "ERR", 200


# ================================================================
# MAIN
# ================================================================
if __name__ == "__main__":
    if AUTO_WEBHOOK and WEBHOOK_URL:
        try:
            bot.remove_webhook()
            time.sleep(0.2)
            bot.set_webhook(url=f"{WEBHOOK_URL.rstrip('/')}/{BOT_TOKEN}")
            log.info("[WEBHOOK] set")
        except Exception as e:
            log.warning(f"[WEBHOOK] set failed: {e}")
    app.run(host="0.0.0.0", port=PORT)

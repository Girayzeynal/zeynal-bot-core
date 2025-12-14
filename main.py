# -*- coding: utf-8 -*-
"""
Zeynal Core AI - FINAL MAIN (Fly.io + Telegram)
- Webhook + health endpoint
- /mac: /mac LIG | YYYY-MM-DD | Home - Away
- FAZ-17 market fetch (safe) + debug env logları
- Telegram JSON chunking
NOT: Gunicorn ile çalışırken __main__ çalışmaz; webhook bootstrap import-time yapılır.
"""

from __future__ import annotations

import os
import json
import time
import logging
import threading
from typing import Any, Dict, Tuple, List, Optional

import telebot
from flask import Flask, request

# ================================================================
# LOGGING
# ================================================================
LOG_LEVEL = (os.getenv("LOG_LEVEL", "INFO") or "INFO").upper()
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
AUTO_WEBHOOK = (os.getenv("AUTO_WEBHOOK", "1") or "1").strip() == "1"
PORT = int((os.getenv("PORT", "8080") or "8080").strip())

ODDS_API_KEY = (os.getenv("ODDS_API_KEY", "") or "").strip()
API_SPORT_KEY = (os.getenv("API_SPORT_KEY", "") or "").strip()

TG_LIMIT = int((os.getenv("TG_LIMIT", "3900") or "3900").strip())

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN missing (Fly Secrets -> BOT_TOKEN)")

# ================================================================
# BOT + FLASK
# ================================================================
bot = telebot.TeleBot(BOT_TOKEN, threaded=True)
app = Flask(__name__)

# ================================================================
# OPTIONAL IMPORTS
# ================================================================
def _noop_normalize_league(x: str) -> str:
    return (x or "").strip()

try:
    from core.elite_league_registry import normalize_league_input as _normalize_league_input  # type: ignore
except Exception as e:
    log.warning(f"[IMPORT] elite_league_registry yok: {e}")
    _normalize_league_input = _noop_normalize_league

run_faz13_auto_pipeline = None
try:
    from faz13_engine.faz13_orchestrator import run_faz13_auto_pipeline as _rf13  # type: ignore
    run_faz13_auto_pipeline = _rf13
except Exception as e:
    log.warning(f"[IMPORT] faz13_orchestrator yok/bozuk: {e}")

faz17_fetch_market_safe = None
try:
    # Artık provider_fetch_func uyumlu
    from faz17_engine import faz17_fetch_market_safe as _f17safe  # type: ignore
    faz17_fetch_market_safe = _f17safe
except Exception as e:
    log.warning(f"[IMPORT] faz17_engine yok/bozuk: {e}")

# ================================================================
# DEBUG HELPERS
# ================================================================
def _debug_env() -> None:
    log.warning(
        "[FAZ17 ENV] API_SPORT_KEY=%s ODDS_API_KEY=%s",
        bool(API_SPORT_KEY),
        bool(ODDS_API_KEY),
    )

# ================================================================
# JSON UTILS
# ================================================================
def _safe_json_chunks(obj: Any) -> List[str]:
    try:
        s = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    except Exception:
        s = str(obj)

    out: List[str] = []
    while len(s) > TG_LIMIT:
        out.append(s[:TG_LIMIT])
        s = s[TG_LIMIT:]
    out.append(s)
    return out

# ================================================================
# PARSER
# ================================================================
def parse_mac_command(text: str) -> Tuple[str, str, str, str]:
    raw = (text or "").replace("/mac", "", 1).strip()
    parts = [p.strip() for p in raw.split("|")]
    if len(parts) < 3:
        raise ValueError("Format hatası.\nÖrnek: /mac NBA | 2025-12-15 | Brooklyn Nets - Milwaukee Bucks")

    league_raw, date_str, teams = parts[0], parts[1], parts[2]
    if "-" not in teams:
        raise ValueError("Takım ayırıcı '-' yok.\nÖrnek: Home - Away")

    home, away = [t.strip() for t in teams.split("-", 1)]
    if not league_raw or not date_str or not home or not away:
        raise ValueError("Eksik alan var.\nÖrnek: /mac LIG | YYYY-MM-DD | Home - Away")

    league = _normalize_league_input(league_raw)
    return league, date_str.strip(), home, away

# ================================================================
# MARKET FETCH (FAZ-17)
# ================================================================
def fetch_market_bundle(league: str, date_str: str, home: str, away: str) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    _debug_env()
    log.warning("[FAZ17] fetch_market_safe CALLED")

    if not faz17_fetch_market_safe:
        return None, {"used": False, "reason": "faz17_fetch_market_safe_missing", "provider": None, "ts": int(time.time())}

    try:
        md, meta = faz17_fetch_market_safe(league=league, date_str=date_str, home=home, away=away)  # type: ignore
        if not isinstance(meta, dict):
            meta = {"used": False, "reason": "bad_meta_type", "provider": None, "ts": int(time.time())}
        return md, meta
    except Exception as e:
        return None, {"used": False, "reason": f"safe_fetch_exception: {e}", "provider": None, "ts": int(time.time())}

# ================================================================
# PIPELINE
# ================================================================
def run_pipeline(league: str, date_str: str, home: str, away: str) -> Dict[str, Any]:
    market_data, market_meta = fetch_market_bundle(league, date_str, home, away)

    if run_faz13_auto_pipeline:
        try:
            out = run_faz13_auto_pipeline(  # type: ignore
                league=league,
                home=home,
                away=away,
                date_str=date_str,
                market_data=market_data,
                market_meta=market_meta,
            )
            if isinstance(out, dict):
                out.setdefault("meta", {})
                out["meta"].update({"league": league, "date": date_str, "home": home, "away": away})
                return out
        except Exception as e:
            log.exception(f"[FAZ13] pipeline crash: {e}")

    # Fallback: asla boş dönme
    return {
        "engine": "FALLBACK_CORE",
        "match": {"league": league, "date": date_str, "home": home, "away": away},
        "market": {
            "used": bool(market_meta.get("used")),
            "reason": market_meta.get("reason"),
            "provider": market_meta.get("provider"),
            "ts": market_meta.get("ts"),
        },
        "prediction": {
            "total": None,
            "band": None,
            "confidence": 0.0,
            "note": "FAZ-13 yok/çalışmadı; fallback çıktı üretildi.",
        },
        "debug": {"market_meta": market_meta},
    }

# ================================================================
# TELEGRAM HANDLERS
# ================================================================
@bot.message_handler(commands=["start"])
def on_start(msg):
    bot.reply_to(
        msg,
        "Zeynal Core AI aktif.\n\n"
        "Komut:\n"
        "/mac LIG | YYYY-MM-DD | Home - Away\n\n"
        "/status\n"
        "/testkeys\n"
    )

@bot.message_handler(commands=["status"])
def on_status(msg):
    _debug_env()
    bot.reply_to(
        msg,
        "STATUS\n"
        f"- webhook_url: {'set' if bool(WEBHOOK_URL) else 'empty'}\n"
        f"- webhook_secret: {'set' if bool(WEBHOOK_SECRET) else 'empty'}\n"
        f"- ODDS_API_KEY: {bool(ODDS_API_KEY)}\n"
        f"- API_SPORT_KEY: {bool(API_SPORT_KEY)}\n"
        f"- faz13: {bool(run_faz13_auto_pipeline)}\n"
        f"- faz17_safe: {bool(faz17_fetch_market_safe)}\n"
    )

@bot.message_handler(commands=["testkeys"])
def on_testkeys(msg):
    lines = [
        "KEY TEST",
        f"- ODDS_API_KEY present: {bool(ODDS_API_KEY)}",
        f"- API_SPORT_KEY present: {bool(API_SPORT_KEY)}",
    ]
    if not ODDS_API_KEY:
        lines.append("! ODDS_API_KEY yok -> Fly Secrets'e ODDS_API_KEY ekle")
    if not API_SPORT_KEY:
        lines.append("! API_SPORT_KEY yok -> Fly Secrets'e API_SPORT_KEY ekle")
    bot.reply_to(msg, "\n".join(lines))

@bot.message_handler(commands=["mac"])
def on_mac(msg):
    try:
        league, date_str, home, away = parse_mac_command(msg.text or "")
    except Exception as e:
        bot.reply_to(msg, f"❌ {e}")
        return

    bot.reply_to(msg, f"⏳ Analiz ediliyor:\n{league} | {date_str}\n{home} - {away}")

    try:
        out = run_pipeline(league, date_str, home, away)
    except Exception as e:
        log.exception(f"[PIPELINE] hard crash: {e}")
        bot.reply_to(msg, f"❌ Pipeline crash: {e}")
        return

    for part in _safe_json_chunks(out):
        bot.reply_to(msg, f"```json\n{part}\n```", parse_mode="Markdown")

# ================================================================
# FLASK ROUTES (Webhook + Health)
# ================================================================
@app.get("/")
def health():
    return "OK", 200

@app.post("/webhook")
def telegram_webhook():
    token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if WEBHOOK_SECRET and token != WEBHOOK_SECRET:
        return "forbidden", 403
    try:
        data = request.get_data(as_text=True)
        upd = telebot.types.Update.de_json(data)
        bot.process_new_updates([upd])
    except Exception as e:
        log.exception(f"[WEBHOOK] parse/process error: {e}")
    return "OK", 200

# ================================================================
# WEBHOOK BOOTSTRAP (Gunicorn'da da çalışsın)
# ================================================================
_BOOT_LOCK = threading.Lock()
_BOOT_DONE = False

def _normalize_webhook_url(base: str) -> str:
    base = (base or "").rstrip("/")
    if not base:
        return ""
    if base.endswith("/webhook"):
        return base
    return base + "/webhook"

def _bootstrap_webhook_once() -> None:
    global _BOOT_DONE
    with _BOOT_LOCK:
        if _BOOT_DONE:
            return
        _BOOT_DONE = True

    if not (AUTO_WEBHOOK and WEBHOOK_URL):
        log.warning("[WEBHOOK] AUTO_WEBHOOK kapalı veya WEBHOOK_URL boş -> sadece webhook endpoint hazır")
        return

    hook = _normalize_webhook_url(WEBHOOK_URL)
    try:
        bot.remove_webhook()
        time.sleep(0.25)
        if WEBHOOK_SECRET:
            bot.set_webhook(url=hook, secret_token=WEBHOOK_SECRET)
        else:
            bot.set_webhook(url=hook)
        log.warning(f"[WEBHOOK] set -> {hook} (secret={'on' if bool(WEBHOOK_SECRET) else 'off'})")
    except Exception as e:
        log.exception(f"[WEBHOOK] set failed: {e}")

# Import-time bootstrap (gunicorn için kritik)
threading.Thread(target=_bootstrap_webhook_once, daemon=True).start()

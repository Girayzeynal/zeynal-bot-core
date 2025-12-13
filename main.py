# ============================================================
# Zeynal Core AI - FULL FINAL BUILD
# FAZ-7 / FAZ-10 / FAZ-11 / FAZ-12 / FAZ-13 / FAZ-17 / FAZ-22 / FAZ-23
# ENGINEERING / HIGH FOCUS / HATA AVCI MODE
# Fly.io 512MB uyumlu
# ============================================================

import os
import json
import time
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, Optional

import telebot
from flask import Flask, request

# ============================================================
# LOGGING
# ============================================================
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("zeynal-core")

# ============================================================
# ENV
# ============================================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
PORT = int(os.getenv("PORT", "8080"))

FAZ17_MARKET_ENABLED = os.getenv("FAZ17_MARKET_ENABLED", "1") == "1"
FAZ22_META_ENGINE = os.getenv("FAZ22_META_ENGINE", "1") == "1"
FAZ23_META_ENABLED = os.getenv("FAZ23_META_ENABLED", "1") == "1"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN missing")

# ============================================================
# TELEGRAM + FLASK
# ============================================================
bot = telebot.TeleBot(BOT_TOKEN, threaded=True, num_threads=2)
app = Flask(__name__)

# ============================================================
# OCR / VISUAL STATE (FAZ-7)
# ============================================================
LAST_OCR_TEXT: Optional[str] = None
LAST_OCR_META: Dict[str, Any] = {}

OCR_CACHE: Dict[str, Dict[str, Any]] = {}
OCR_CACHE_LOCK = threading.Lock()

OCR_MAX_WORKERS = int(os.getenv("OCR_MAX_WORKERS", "2"))
OCR_POOL = ThreadPoolExecutor(max_workers=max(1, OCR_MAX_WORKERS))

# ============================================================
# SAFE IMPORT
# ============================================================
def _safe_import(path: str, name: str):
    try:
        module = __import__(path, fromlist=[name])
        return getattr(module, name)
    except Exception as e:
        log.warning("Import fail %s.%s → %s", path, name, e)
        return None

# ============================================================
# FAZ IMPORTS
# ============================================================
faz10_stability_check = _safe_import(
    "faz10_engine.faz10_stability", "faz10_stability_check"
)

faz11_feedback = _safe_import(
    "faz11_engine.faz11_feedback", "faz11_feedback"
)
faz11_last_summary = _safe_import(
    "faz11_engine.faz11_feedback", "faz11_last_summary"
)

faz12_run_once = _safe_import(
    "faz12_engine.faz12_autoadjust", "faz12_run_once"
)
faz12_auto_profile = _safe_import(
    "faz12_engine.faz12_autoadjust", "faz12_auto_profile"
)

run_faz13_auto_pipeline = _safe_import(
    "faz13_engine.faz13_orchestrator", "run_faz13_auto_pipeline"
)

faz13_daily_coupon = _safe_import(
    "faz13_engine.faz13_orchestrator", "faz13_daily_coupon"
)

faz17_fetch_market = _safe_import(
    "faz17_engine.faz17_market_fetcher", "faz17_fetch_market"
)

faz23_meta_evaluate = _safe_import(
    "faz23_engine.faz23_meta", "faz23_meta_evaluate"
)

# ============================================================
# UTILS
# ============================================================
def normalize_league(league: str) -> str:
    l = league.strip().upper()
    if l in ("EL", "EUROLEAGUE"):
        return "EUROLEAGUE"
    return l

def parse_mac_command(text: str):
    """
    /mac LIG | YYYY-MM-DD | Ev - Dep
    """
    raw = text.replace("/mac", "").strip()
    parts = [p.strip() for p in raw.split("|")]
    if len(parts) != 3:
        raise ValueError("Format hatalı")
    league = normalize_league(parts[0])
    date_str = parts[1]
    home, away = [x.strip() for x in parts[2].split("-", 1)]
    return league, date_str, home, away

# ============================================================
# MARKET FETCH (FAZ-17)
# ============================================================
def get_market_data(league, date_str, home, away):
    if not FAZ17_MARKET_ENABLED or not faz17_fetch_market:
        return None
    try:
        return faz17_fetch_market(
            league=league,
            date_str=date_str,
            home=home,
            away=away,
            want_live=False,
        )
    except Exception as e:
        log.warning("FAZ-17 market error: %s", e)
        return None

# ============================================================
# CORE MATCH PIPELINE
# ============================================================
def run_match_pipeline(league, date_str, home, away):
    # FAZ-10
    if faz10_stability_check:
        faz10_stability_check(
            source_type="mac_command",
            meta={
                "league": league,
                "date": date_str,
                "home": home,
                "away": away,
            }
    )

    # FAZ-12
    if faz12_run_once:
        faz12_run_once()

    market_data = get_market_data(league, date_str, home, away)

    if not run_faz13_auto_pipeline:
        raise RuntimeError("FAZ-13 missing")

    result = run_faz13_auto_pipeline(
        league=league,
        date_str=date_str,
        home=home,
        away=away,
        market_data=market_data,
    )

    # FAZ-11 feedback
    if faz11_feedback:
        try:
            faz11_feedback(result)
        except Exception as e:
            log.warning("FAZ-11 feedback error: %s", e)

    # FAZ-23 meta
    if FAZ23_META_ENABLED and faz23_meta_evaluate:
        try:
            meta = faz23_meta_evaluate(
                league=league,
                date_str=date_str,
                home=home,
                away=away,
                faz13_result=result,
                market_data=market_data,
            )
            result.setdefault("meta23", {})
            result["meta23"]["faz23_ext"] = meta
        except Exception as e:
            log.warning("FAZ-23 meta error: %s", e)

    return result

# ============================================================
# TELEGRAM COMMANDS
# ============================================================
@bot.message_handler(commands=["start"])
def on_start(msg):
    bot.reply_to(
        msg,
        "Zeynal Core AI aktif.\n"
        "/mac LIG | YYYY-MM-DD | Ev - Dep",
    )

@bot.message_handler(func=lambda m: (m.text or "").startswith("/mac"))
def on_mac(msg):
    try:
        league, date_str, home, away = parse_mac_command(msg.text)
        bot.send_message(
            msg.chat.id,
            f"⏳ Analiz ediliyor:\n{league} | {date_str}\n{home} - {away}",
        )
        result = run_match_pipeline(league, date_str, home, away)
        bot.send_message(
            msg.chat.id,
            json.dumps(result, ensure_ascii=False, indent=2),
        )
    except Exception as e:
        log.exception("MAC error")
        bot.reply_to(msg, f"❌ Hata: {e}")

# ============================================================
# WEBHOOK
# ============================================================
@app.route("/", methods=["GET"])
def health():
    return "OK", 200

@app.route("/webhook", methods=["POST"])
def webhook():
    if WEBHOOK_SECRET:
        if request.headers.get("X-Webhook-Secret") != WEBHOOK_SECRET:
            return "FORBIDDEN", 403
    update = telebot.types.Update.de_json(
        request.stream.read().decode("utf-8")
    )
    bot.process_new_updates([update])
    return "OK", 200

# WEBHOOK AUTO-REGISTER (GUNICORN SAFE)
if WEBHOOK_URL:
    try:
        bot.remove_webhook()
        time.sleep(0.2)
        bot.set_webhook(url=WEBHOOK_URL)
        log.info("Webhook auto-registered (gunicorn)")
    except Exception as e:
        log.error("Webhook auto-register failed: %s", e)

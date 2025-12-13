# ============================================================
# Zeynal Core AI - FINAL BUILD (FAZ-7/10/11/12/13/17/22/23)
# ENGINEERING / HIGH FOCUS / HATA AVCI MODE
# Fly.io 512MB uyumlu, stabil, gözlemci log + sebep kodlu
# ============================================================

import os
import json
import time
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

import telebot
from flask import Flask, request

# -----------------------------
# LOGGING
# -----------------------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("zeynal-core")

# -----------------------------
# ENV
# -----------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()

OCR_MAX_WORKERS = int(os.getenv("OCR_MAX_WORKERS", "2"))
OCR_TIMEOUT_S = int(os.getenv("OCR_TIMEOUT_S", "12"))

FAZ17_MARKET_ENABLED = os.getenv("FAZ17_MARKET_ENABLED", "1").strip() == "1"
FAZ23_META_ENABLED = os.getenv("FAZ23_META_ENABLED", "1").strip() == "1"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN missing")

bot = telebot.TeleBot(BOT_TOKEN, threaded=True, num_threads=2)
app = Flask(__name__)

# ================================================================
# 🔍 FAZ-13 OCR DEBUG STATE + GLOBAL OCR CACHE
# ================================================================
LAST_OCR_TEXT = None
LAST_OCR_META = {}
OCR_CACHE = {}
OCR_CACHE_LOCK = threading.Lock()

OCR_POOL = ThreadPoolExecutor(max_workers=max(1, min(4, OCR_MAX_WORKERS)))

# ================================================================
# IMPORTS (fail-soft)
# ================================================================
def _safe_import(path, name):
    try:
        module = __import__(path, fromlist=[name])
        return getattr(module, name)
    except Exception as e:
        log.warning(f"Import fail: {path}.{name} -> {e}")
        return None

# FAZ-10/11/12/13
faz10_stability_check = _safe_import("faz10_engine.faz10_stability", "faz10_stability_check")
faz12_run_once = _safe_import("faz12_engine.faz12_autoadjust", "faz12_run_once")
run_faz13_auto_pipeline = _safe_import("faz13_engine.faz13_orchestrator", "run_faz13_auto_pipeline")

# ✅ KRİTİK: doğru market fetcher import’u
faz17_fetch_market = _safe_import("faz17_engine.faz17_market_fetcher", "faz17_fetch_market")

# opsiyonel faz23
faz23_meta_evaluate = _safe_import("faz23_engine.faz23_meta", "faz23_meta_evaluate")

# ================================================================
# UTILS
# ================================================================
def _clean_team(s: str) -> str:
    return (s or "").strip()

def _normalize_league_key(league: str) -> str:
    L = (league or "").strip().upper()
    if L in ("EUROLEAGUE", "EL", "EURL"):
        return "EUROLEAGUE"
    if L in ("NBA",):
        return "NBA"
    return L

def _parse_mac_command(text: str):
    """
    /mac LEAGUE | YYYY-MM-DD | Home - Away
    """
    raw = (text or "").strip()
    if not raw.startswith("/mac"):
        return None
    payload = raw[4:].strip()
    parts = [p.strip() for p in payload.split("|")]
    if len(parts) < 3:
        return None
    league = parts[0]
    date_str = parts[1]
    teams = parts[2]
    if "-" not in teams:
        return None
    home, away = [t.strip() for t in teams.split("-", 1)]
    return league, date_str, home, away

def _try_fetch_market_safe(league, date_str, home, away):
    """
    Returns: (market_data, market_flag, market_reason)
    """
    if not FAZ17_MARKET_ENABLED:
        return None, "MARKET_DISABLED", "FAZ17_MARKET_ENABLED=0"
    if not faz17_fetch_market:
        return None, "NO_MARKET_DATA", "faz17_fetch_market import missing"

    league_key = _normalize_league_key(league)

    # 1) direct
    try:
        md = faz17_fetch_market(
            league=league_key,
            date_str=date_str,
            home=home,
            away=away,
            want_live=False,
        )
        if md and isinstance(md, dict) and md.get("ok"):
            return md, "MARKET_OK", md.get("reason", "direct_ok")
        return md, "NO_MARKET_DATA", (md.get("reason") if isinstance(md, dict) else "empty_return")
    except Exception as e:
        log.warning(f"FAZ-17 market fetch failed (direct): {e}")

    # 2) normalized fallback (kaba)
    try:
        md = faz17_fetch_market(
            league=league_key,
            date_str=date_str,
            home=_clean_team(home),
            away=_clean_team(away),
            want_live=False,
        )
        if md and isinstance(md, dict) and md.get("ok"):
            return md, "MARKET_OK", md.get("reason", "normalized_ok")
        return md, "NO_MARKET_DATA", (md.get("reason") if isinstance(md, dict) else "empty_return_norm")
    except Exception as e:
        log.warning(f"FAZ-17 market fetch failed (normalized): {e}")

    return None, "NO_MARKET_DATA", "all attempts failed"

def _fmt_kv(title, v):
    return f"• {title}: {v}"

def _render_prediction_message(result: dict, league: str, home: str, away: str, market_flag: str, market_reason: str):
    lines = []
    lines.append("🏀 FAZ-13 Maç Tahmini (FINAL)")
    lines.append(f"Maç: {home} - {away}")
    lines.append(f"Lig: {league}")
    lines.append("—" * 28)
    lines.append("🧷 MARKET DURUMU")
    lines.append(_fmt_kv("flags", f"{market_flag} ({market_reason})"))

    if not isinstance(result, dict):
        lines.append("—" * 28)
        lines.append("⚠️ FAZ-13 pipeline dict dönmedi.")
        lines.append(str(result))
        return "\n".join(lines)

    total = result.get("total")
    band = result.get("band")
    vector = result.get("vector")
    meta23 = result.get("meta23") or {}

    lines.append("—" * 28)
    lines.append("📊 TOPLAM")
    if total is not None: lines.append(_fmt_kv("Total", total))
    if band is not None: lines.append(_fmt_kv("Band", band))
    if vector is not None: lines.append(_fmt_kv("Vector", vector))

    if meta23:
        lines.append("—" * 28)
        lines.append("🧠 FAZ-23 META")
        for k in ["primary_total", "model_over", "model_under", "drift", "wrong_line_suspicion", "flags"]:
            if k in meta23:
                lines.append(_fmt_kv(k, meta23[k]))

    return "\n".join(lines)

# ================================================================
# CORE PIPELINE
# ================================================================
def run_match_pipeline(league: str, date_str: str, home: str, away: str):
    league_key = _normalize_league_key(league)

    if faz10_stability_check:
        try:
            faz10_stability_check()
        except Exception as e:
            log.warning(f"FAZ-10 stability fail: {e}")

    if faz12_run_once:
        try:
            faz12_run_once()
        except Exception as e:
            log.warning(f"FAZ-12 run once fail: {e}")

    market_data, market_flag, market_reason = _try_fetch_market_safe(league_key, date_str, home, away)

    if not run_faz13_auto_pipeline:
        return {
            "total": None,
            "band": None,
            "vector": None,
            "meta23": {"flags": ["PIPELINE_IMPORT_MISSING"]},
        }, market_flag, market_reason

    try:
        result = run_faz13_auto_pipeline(
            league=league_key,
            date_str=date_str,
            home=home,
            away=away,
            market_data=market_data,
        )
    except Exception as e:
        log.exception(f"FAZ-13 pipeline crash: {e}")
        result = {"meta23": {"flags": ["FAZ13_CRASH"], "error": str(e)}}

    # opsiyonel meta evaluate (varsa)
    if FAZ23_META_ENABLED and faz23_meta_evaluate:
        try:
            meta = faz23_meta_evaluate(
                league=league_key,
                date_str=date_str,
                home=home,
                away=away,
                faz13_result=result,
                market_data=market_data,
            )
            if isinstance(result, dict):
                result.setdefault("meta23", {})
                result["meta23"]["faz23_ext"] = meta
        except Exception as e:
            log.warning(f"FAZ-23 meta eval fail: {e}")

    return result, market_flag, market_reason

# ================================================================
# TELEGRAM
# ================================================================
@bot.message_handler(commands=["start"])
def cmd_start(m):
    bot.reply_to(m, "Zeynal Core AI online.\n/mac LEAGUE | YYYY-MM-DD | Home - Away")

@bot.message_handler(func=lambda m: (m.text or "").strip().startswith("/mac"))
def cmd_mac(m):
    parsed = _parse_mac_command(m.text)
    if not parsed:
        bot.reply_to(m, "Format: /mac LEAGUE | YYYY-MM-DD | Home - Away")
        return

    league, date_str, home, away = parsed
    bot.send_message(m.chat.id, f"⏳ İşleniyor: {league} | {date_str} | {home} - {away}")

    result, market_flag, market_reason = run_match_pipeline(league, date_str, home, away)

    msg = _render_prediction_message(
        result=result,
        league=_normalize_league_key(league),
        home=home,
        away=away,
        market_flag=market_flag,
        market_reason=market_reason,
    )
    bot.send_message(m.chat.id, msg)

# ================================================================
# WEBHOOK
# ================================================================
@app.route("/", methods=["GET"])
def index():
    return "OK", 200

@app.route("/webhook", methods=["POST"])
def webhook():
    if WEBHOOK_SECRET:
        hdr = request.headers.get("X-Webhook-Secret", "")
        if hdr != WEBHOOK_SECRET:
            return "FORBIDDEN", 403

    try:
        update = telebot.types.Update.de_json(request.stream.read().decode("utf-8"))
        bot.process_new_updates([update])
    except Exception as e:
        log.exception(f"Webhook processing error: {e}")
    return "OK", 200

def _set_webhook():
    if not WEBHOOK_URL:
        log.warning("WEBHOOK_URL not set; polling mode for local dev.")
        return
    try:
        bot.remove_webhook()
        time.sleep(0.2)
        bot.set_webhook(url=WEBHOOK_URL)
        log.info(f"Webhook set: {WEBHOOK_URL}")
    except Exception as e:
        log.warning(f"Webhook set failed: {e}")

if __name__ == "__main__":
    _set_webhook()
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, threaded=False)

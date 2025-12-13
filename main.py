# ============================================================
# Zeynal Core AI - FINAL BUILD (FAZ-7/10/11/12/13/17/22/23)
# ENGINEERING / HIGH FOCUS / HATA AVCI MODE
# Fly.io 512MB uyumlu, stabil, gözlemci log + sebep kodlu
# ============================================================

import os
import json
import time
import logging
import hashlib
import threading
from datetime import datetime
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
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()  # opsiyonel

# OCR / concurrency
OCR_MAX_WORKERS = int(os.getenv("OCR_MAX_WORKERS", "2"))
OCR_TIMEOUT_S = int(os.getenv("OCR_TIMEOUT_S", "12"))

# MARKET / FAZ flags
FAZ17_MARKET_ENABLED = os.getenv("FAZ17_MARKET_ENABLED", "1").strip() == "1"
FAZ23_META_ENABLED = os.getenv("FAZ23_META_ENABLED", "1").strip() == "1"

# -----------------------------
# TELEGRAM + FLASK
# -----------------------------
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

# ================================================================
#  FAZ IMPORTS (fail-soft)
# ================================================================
def _safe_import(path, name):
    try:
        module = __import__(path, fromlist=[name])
        return getattr(module, name)
    except Exception as e:
        log.warning(f"Import fail: {path}.{name} -> {e}")
        return None

# FAZ-10 / 11 / 12 / 13
faz10_stability_check = _safe_import("faz10_engine.faz10_stability", "faz10_stability_check")

faz11_feedback = _safe_import("faz11_engine.faz11_feedback", "faz11_feedback")
faz11_last_summary = _safe_import("faz11_engine.faz11_feedback", "faz11_last_summary")

faz12_run_once = _safe_import("faz12_engine.faz12_autoadjust", "faz12_run_once")
faz12_auto_profile = _safe_import("faz12_engine.faz12_autoadjust", "faz12_auto_profile")

normalize_manual_text = _safe_import("faz13_engine.faz13_orchestrator", "normalize_manual_text")
normalize_api_data = _safe_import("faz13_engine.faz13_orchestrator", "normalize_api_data")
normalize_visual_meta = _safe_import("faz13_engine.faz13_orchestrator", "normalize_visual_meta")
run_faz13_auto_pipeline = _safe_import("faz13_engine.faz13_orchestrator", "run_faz13_auto_pipeline")
faz13_daily_coupon = _safe_import("faz13_engine.faz13_orchestrator", "faz13_daily_coupon")

# FAZ-17 market fetch (senin projende bu fonksiyonun adı neyse onu import et)
# Örnek: from faz17_engine.faz17_market import faz17_fetch_market
faz17_fetch_market = _safe_import("faz17_engine.faz17_market", "faz17_fetch_market")

# FAZ-23 meta engine (opsiyonel)
faz23_meta_evaluate = _safe_import("faz23_engine.faz23_meta", "faz23_meta_evaluate")

# ================================================================
# THREAD POOL (Fly.io 512MB friendly)
# ================================================================
OCR_POOL = ThreadPoolExecutor(max_workers=max(1, min(4, OCR_MAX_WORKERS)))

# ================================================================
# UTILS
# ================================================================
def _now_ts():
    return int(time.time())

def _clean_team(s: str) -> str:
    return (s or "").strip().lower().replace(".", "").replace("-", " ").replace("  ", " ")

def _normalize_league_key(league: str) -> str:
    L = (league or "").strip().upper()
    if L in ("EUROLEAGUE", "EL", "EURL"):
        return "EUROLEAGUE"
    if L in ("NBA",):
        return "NBA"
    # EUROCUP vb.
    return L

def _parse_mac_command(text: str):
    """
    Beklenen format:
    /mac LEAGUE | YYYY-MM-DD | Home - Away
    """
    raw = (text or "").strip()
    if not raw.startswith("/mac"):
        return None
    # '/mac ' sonrası
    payload = raw[4:].strip()
    parts = [p.strip() for p in payload.split("|")]
    if len(parts) < 3:
        return None
    league = parts[0]
    date_str = parts[1]
    teams = parts[2]
    if "-" in teams:
        home, away = [t.strip() for t in teams.split("-", 1)]
    else:
        return None
    return league, date_str, home, away

# ================================================================
# HATA AVCI: MARKET FETCH SAFE WRAPPER
# ================================================================
def _try_fetch_market_safe(faz17_fetch_market_fn, league, date_str, home, away):
    """
    Returns: (market_data, market_flag, market_reason)
    - market_data: dict|None
    - market_flag: "MARKET_OK" | "NO_MARKET_DATA" | "MARKET_DISABLED"
    - market_reason: kısa sebep kodu
    """
    if not FAZ17_MARKET_ENABLED:
        return None, "MARKET_DISABLED", "FAZ17_MARKET_ENABLED=0"

    if not faz17_fetch_market_fn:
        return None, "NO_MARKET_DATA", "faz17_fetch_market is None (import/wire missing)"

    league_key = _normalize_league_key(league)
    home0, away0 = _clean_team(home), _clean_team(away)

    # 1) direct
    try:
        md = faz17_fetch_market_fn(league=league_key, date_str=date_str, home=home, away=away)
        if md:
            return md, "MARKET_OK", "direct"
        log.warning("FAZ-17 market returned empty (direct)")
    except Exception as e:
        log.warning(f"FAZ-17 market failed (direct): {e}")

    # 2) normalized teams
    try:
        md = faz17_fetch_market_fn(league=league_key, date_str=date_str, home=home0, away=away0)
        if md:
            return md, "MARKET_OK", "normalized_teams"
        log.warning("FAZ-17 market returned empty (normalized_teams)")
    except Exception as e:
        log.warning(f"FAZ-17 market failed (normalized_teams): {e}")

    return None, "NO_MARKET_DATA", "all attempts failed/empty"

# ================================================================
# OUTPUT FORMATTERS
# ================================================================
def _fmt_kv(title, v):
    return f"• {title}: {v}"

def _safe_json(v):
    try:
        return json.dumps(v, ensure_ascii=False)
    except Exception:
        return str(v)

def _render_prediction_message(result: dict, league: str, home: str, away: str, market_flag: str, market_reason: str):
    """
    result beklenen: dict (faz13 pipeline çıktısı)
    """
    lines = []
    lines.append("🏀 FAZ-13 Maç Tahmini (Pro)")
    lines.append(f"Maç: {home} - {away}")
    lines.append(f"Lig: {league}")
    lines.append("—" * 30)

    # HATA AVCI: market sebebi
    lines.append("🧷 MARKET DURUMU")
    lines.append(_fmt_kv("flags", f"{market_flag} ({market_reason})"))

    # FAZ-13 output (fail-soft)
    if not isinstance(result, dict):
        lines.append("—" * 30)
        lines.append("⚠️ FAZ-13 pipeline dict dönmedi.")
        lines.append(str(result))
        return "\n".join(lines)

    # try common keys
    fusion_total = result.get("fusion_total") or result.get("total") or result.get("pred_total")
    band = result.get("band") or result.get("total_band")
    score_vector = result.get("score_vector") or result.get("vector")

    lines.append("—" * 30)
    lines.append("📊 TOPLAM TAHMİNİ")
    if fusion_total is not None:
        lines.append(_fmt_kv("Fusion Total", fusion_total))
    if band is not None:
        lines.append(_fmt_kv("Bant", band))
    if score_vector is not None:
        lines.append(_fmt_kv("Score Vector", score_vector))

    per = result.get("periods") or result.get("period_projection") or {}
    if isinstance(per, dict) and per:
        lines.append("—" * 30)
        lines.append("⏱️ PERİYOT PROJEKSİYONLARI")
        for k in ["Q1", "Q2", "Q3", "Q4", "H1", "H2", "FT"]:
            if k in per:
                lines.append(_fmt_kv(k, per[k]))

    team = result.get("team_scores") or result.get("teams") or {}
    if isinstance(team, dict) and team:
        lines.append("—" * 30)
        lines.append("🎯 TAKIM SKOR TAHMİNİ")
        # farklı anahtar isimlerini tolere et
        home_sc = team.get("home") or team.get(home) or team.get("ev") or team.get("Ev")
        away_sc = team.get("away") or team.get(away) or team.get("dep") or team.get("Deplasman")
        if home_sc is not None:
            lines.append(_fmt_kv("Ev Sahibi", home_sc))
        if away_sc is not None:
            lines.append(_fmt_kv("Deplasman", away_sc))

    notes = result.get("notes") or result.get("analysis") or result.get("meta") or {}
    if notes:
        lines.append("—" * 30)
        lines.append("🧾 ANALİZ / NOTLAR")
        if isinstance(notes, dict):
            for kk, vv in list(notes.items())[:20]:
                lines.append(_fmt_kv(kk, vv))
        else:
            lines.append(str(notes))

    return "\n".join(lines)

# ================================================================
# CORE: RUN MATCH PIPELINE
# ================================================================
def run_match_pipeline(league: str, date_str: str, home: str, away: str):
    """
    FAZ-10 -> FAZ-12 -> FAZ-17 market -> FAZ-13 orchestrator -> (opsiyonel) FAZ-23 meta
    """
    league_key = _normalize_league_key(league)

    # FAZ-10 stability
    if faz10_stability_check:
        try:
            faz10_stability_check()
        except Exception as e:
            log.warning(f"FAZ-10 stability fail: {e}")

    # FAZ-12 auto adjust
    if faz12_run_once:
        try:
            faz12_run_once()
        except Exception as e:
            log.warning(f"FAZ-12 run once fail: {e}")

    # MARKET FETCH (HATA AVCI)
    market_data, market_flag, market_reason = _try_fetch_market_safe(
        faz17_fetch_market_fn=faz17_fetch_market,
        league=league_key,
        date_str=date_str,
        home=home,
        away=away,
    )

    # FAZ-13 pipeline
    if not run_faz13_auto_pipeline:
        # Fail-soft: minimal output
        fallback = {
            "fusion_total": None,
            "band": None,
            "score_vector": None,
            "notes": {
                "error": "run_faz13_auto_pipeline import missing",
                "league": league_key,
                "date": date_str,
            },
        }
        return fallback, market_flag, market_reason

    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
    # KRİTİK FIX:
    # market_data'yı FAZ-13'e GERÇEKTEN geçiriyoruz.
    # (Senin ekrandaki NO_MARKET_DATA sorunu bunun yüzünden kalıcılaşıyor.)
    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
    try:
        result = run_faz13_auto_pipeline(
            league=league_key,
            date_str=date_str,
            home=home,
            away=away,
            market_data=market_data,  # <<< FIX
            mode="PREMATCH",
        )
    except TypeError:
        # Orchestrator imzasında market_data yoksa bile crash etmesin:
        # ama bu durumda orchestrator dosyanı güncellemen gerekir.
        log.warning("FAZ-13 orchestrator does not accept market_data. Update run_faz13_auto_pipeline signature!")
        result = run_faz13_auto_pipeline(
            league=league_key,
            date_str=date_str,
            home=home,
            away=away,
            mode="PREMATCH",
        )
        market_flag, market_reason = "NO_MARKET_DATA", "orchestrator_signature_missing_market_data"
    except Exception as e:
        log.exception(f"FAZ-13 pipeline crash: {e}")
        result = {
            "notes": {"error": f"FAZ-13 crash: {e}"},
        }

    # FAZ-23 META (opsiyonel)
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
                result.setdefault("meta", {})
                result["meta"]["faz23"] = meta
        except Exception as e:
            log.warning(f"FAZ-23 meta fail: {e}")

    return result, market_flag, market_reason

# ================================================================
# TELEGRAM COMMANDS
# ================================================================
@bot.message_handler(commands=["start"])
def cmd_start(m):
    bot.reply_to(m, "Zeynal Core AI online. /mac LEAGUE | YYYY-MM-DD | Home - Away")

@bot.message_handler(func=lambda m: (m.text or "").strip().startswith("/mac"))
def cmd_mac(m):
    parsed = _parse_mac_command(m.text)
    if not parsed:
        bot.reply_to(m, "Format: /mac LEAGUE | YYYY-MM-DD | Home - Away")
        return

    league, date_str, home, away = parsed

    # hızlı ack
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
# WEBHOOK (Fly.io)
# ================================================================
@app.route("/", methods=["GET"])
def index():
    return "OK", 200

@app.route("/webhook", methods=["POST"])
def webhook():
    # opsiyonel secret
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
        log.warning("WEBHOOK_URL not set; polling mode recommended for local dev.")
        return
    try:
        bot.remove_webhook()
        time.sleep(0.2)
        bot.set_webhook(url=WEBHOOK_URL)
        log.info(f"Webhook set: {WEBHOOK_URL}")
    except Exception as e:
        log.warning(f"Webhook set failed: {e}")

# ================================================================
# MAIN
# ================================================================
if __name__ == "__main__":
    # Fly.io: webhook set + flask run
    _set_webhook()

    port = int(os.getenv("PORT", "8080"))
    # threaded False: daha stabil / düşük bellek
    app.run(host="0.0.0.0", port=port, threaded=False)

# -*- coding: utf-8 -*-
"""
Zeynal Core AI - FINAL BUILD (FAZ-7/10/11/12/13/15/17/22/23)
ENGINEERING / HIGH FOCUS / HATA AVCI MODE
Fly.io: gunicorn --workers 1 --threads 4 --bind 0.0.0.0:8080 main:app
"""

import os
import json
import time
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

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
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()

PORT = int(os.getenv("PORT", "8080"))

# Fly.io 256/512MB için makul limitler
OCR_MAX_WORKERS = int(os.getenv("OCR_MAX_WORKERS", "2"))
OCR_TIMEOUT_S = int(os.getenv("OCR_TIMEOUT_S", "12"))

FAZ17_MARKET_ENABLED = os.getenv("FAZ17_MARKET_ENABLED", "1").strip() == "1"
FAZ23_META_ENABLED = os.getenv("FAZ23_META_ENABLED", "1").strip() == "1"
AUTO_WEBHOOK = os.getenv("AUTO_WEBHOOK", "1").strip() == "1"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN missing")

# ================================================================
# TELEGRAM + FLASK
# ================================================================
bot = telebot.TeleBot(BOT_TOKEN, threaded=True, num_threads=2)
app = Flask(__name__)

# ================================================================
# OCR DEBUG STATE + GLOBAL OCR CACHE (light)
# ================================================================
LAST_OCR_TEXT = None
LAST_OCR_META = {}

OCR_CACHE = {}
OCR_CACHE_LOCK = threading.Lock()

OCR_POOL = ThreadPoolExecutor(max_workers=max(1, min(4, OCR_MAX_WORKERS)))

# ================================================================
# FAZ STATUS
# ================================================================
# Format: {"FAZ-10": {"ok": bool, "msg": str}}
FAZ_STATUS = {}


def _set_faz(faz_name: str, ok: bool, msg: str):
    FAZ_STATUS[faz_name] = {"ok": bool(ok), "msg": str(msg)}


def _safe_import(path: str, attr: str):
    """
    Fail-soft import. Import eder, yoksa None döner (crash yok).
    """
    try:
        module = __import__(path, fromlist=[attr])
        return getattr(module, attr)
    except Exception as e:
        return None


# ================================================================
# SAFE IMPORTS (FAZ modules)
# ================================================================
# FAZ-7 (opsiyonel)
faz7_memory = _safe_import("faz7_engine.faz7_memory", "faz7_memory")

# FAZ-10
faz10_stability_check = _safe_import("faz10_engine.faz10_stability", "faz10_stability_check")

# FAZ-11
faz11_feedback = _safe_import("faz11_engine.faz11_feedback", "faz11_feedback")
faz11_last_summary = _safe_import("faz11_engine.faz11_feedback", "faz11_last_summary")

# FAZ-12
faz12_run_once = _safe_import("faz12_engine.faz12_autoadjust", "faz12_run_once")
faz12_auto_profile = _safe_import("faz12_engine.faz12_autoadjust", "faz12_auto_profile")

# FAZ-13 orchestrator
normalize_manual_text = _safe_import("faz13_engine.faz13_orchestrator", "normalize_manual_text")
normalize_api_data = _safe_import("faz13_engine.faz13_orchestrator", "normalize_api_data")
normalize_visual_meta = _safe_import("faz13_engine.faz13_orchestrator", "normalize_visual_meta")
run_faz13_auto_pipeline = _safe_import("faz13_engine.faz13_orchestrator", "run_faz13_auto_pipeline")
faz13_daily_coupon = _safe_import("faz13_engine.faz13_orchestrator", "faz13_daily_coupon")

# FAZ-15 (opsiyonel)
faz15_preprocess = (
    _safe_import("faz15_engine.faz15_preprocess", "faz15_preprocess")
    or _safe_import("faz15_engine.faz15_preprocess", "faz15_run")
)

# FAZ-17 market (birkaç olası isim)
faz17_fetch_market = (
    _safe_import("faz17_engine.faz17_market", "faz17_fetch_market")
    or _safe_import("faz17_engine.faz17_market_fetcher", "faz17_fetch_market")
    or _safe_import("faz17_engine.faz17_market_fetcher", "fetch_market")
    or _safe_import("faz17_engine.faz17_market_fetcher", "get_market")
)

# FAZ-22 meta engine (fonksiyon adı senin tercihin: faz22_meta_engine)
faz22_meta_engine = (
    _safe_import("faz22_engine.faz22_meta_engine", "faz22_meta_engine")
    or _safe_import("faz22_engine.faz22_meta_engine", "faz22_meta_engine_full")
)

# FAZ-23 meta (opsiyonel)
faz23_meta_evaluate = _safe_import("faz23_engine.faz23_meta", "faz23_meta_evaluate")

# İlk durumları set et (yeşil/kırmızı)
_set_faz("FAZ-7", faz7_memory is not None, "loaded" if faz7_memory else "faz7_memory missing")
_set_faz("FAZ-10", faz10_stability_check is not None, "stability loaded" if faz10_stability_check else "missing")
_set_faz("FAZ-11", faz11_feedback is not None, "feedback loaded" if faz11_feedback else "missing")
_set_faz("FAZ-12", faz12_run_once is not None, "autoadjust loaded" if faz12_run_once else "missing")
_set_faz("FAZ-13", run_faz13_auto_pipeline is not None, "orchestrator loaded" if run_faz13_auto_pipeline else "missing")
_set_faz("FAZ-15", faz15_preprocess is not None, "loaded" if faz15_preprocess else "missing")
_set_faz("FAZ-17", FAZ17_MARKET_ENABLED and (faz17_fetch_market is not None), "market enabled" if (FAZ17_MARKET_ENABLED and faz17_fetch_market) else ("disabled" if not FAZ17_MARKET_ENABLED else "fetcher missing"))
_set_faz("FAZ-22", faz22_meta_engine is not None, "meta engine loaded" if faz22_meta_engine else "missing")
_set_faz("FAZ-23", (FAZ23_META_ENABLED and (faz23_meta_evaluate is not None)) or (faz23_meta_evaluate is not None), "datahub loaded" if faz23_meta_evaluate else ("disabled" if not FAZ23_META_ENABLED else "missing"))

# ================================================================
# HELPERS
# ================================================================
def _safe_json(obj) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, indent=2)
    except Exception:
        return str(obj)


def _clean_team(s: str) -> str:
    return (s or "").strip().lower().replace(".", "").replace("-", " ").replace("  ", " ")


def _normalize_league_key(league: str) -> str:
    L = (league or "").strip().upper()
    if L in ("EUROLEAGUE", "EL", "EURL"):
        return "EUROLEAGUE"
    if L in ("NBA",):
        return "NBA"
    return L


def _parse_mac_command(text: str):
    """
    Beklenen format:
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


# ================================================================
# FAZ-17 MARKET SAFE WRAPPER
# ================================================================
def _try_fetch_market_safe(league, date_str, home, away):
    """
    Returns: (market_data, market_flag, market_reason)
    market_flag: MARKET_OK | NO_MARKET_DATA | MARKET_DISABLED
    """
    if not FAZ17_MARKET_ENABLED:
        return None, "MARKET_DISABLED", "FAZ17_MARKET_ENABLED=0"
    if not faz17_fetch_market:
        return None, "NO_MARKET_DATA", "faz17_fetch_market is None (import/wire missing)"

    league_key = _normalize_league_key(league)

    # 1) direct try
    try:
        md = faz17_fetch_market(
            league=league_key,
            date_str=date_str,
            home=home,
            away=away,
        )
        if md:
            return md, "MARKET_OK", "direct"
    except Exception as e:
        log.warning("FAZ-17 market fetch failed (direct): %s", e)

    # 2) normalized teams try
    try:
        md = faz17_fetch_market(
            league=league_key,
            date_str=date_str,
            home=_clean_team(home),
            away=_clean_team(away),
        )
        if md:
            return md, "MARKET_OK", "normalized_teams"
    except Exception as e:
        log.warning("FAZ-17 market fetch failed (normalized_teams): %s", e)

    return None, "NO_MARKET_DATA", "all attempts failed/empty"


# ================================================================
# PIPELINE
# ================================================================
def run_match_pipeline(league: str, date_str: str, home: str, away: str, source_type: str = "mac_command") -> dict:
    meta = {
        "league": _normalize_league_key(league),
        "date_str": date_str,
        "home": home,
        "away": away,
        "source_type": source_type,
        "ts": int(time.time()),
    }

    # FAZ-7 memory (opsiyonel)
    if faz7_memory is not None:
        try:
            try:
                faz7_memory(meta)
            except TypeError:
                faz7_memory()
            _set_faz("FAZ-7", True, "memory ok")
        except Exception as e:
            _set_faz("FAZ-7", False, f"memory crash: {e}")

    # FAZ-10 stability
    if faz10_stability_check is not None:
        try:
            try:
                faz10_stability_check(source_type, meta)
            except TypeError:
                faz10_stability_check()
            _set_faz("FAZ-10", True, "stability ok")
        except Exception as e:
            _set_faz("FAZ-10", False, f"stability crash: {e}")

    # FAZ-12 autoadjust
    if faz12_run_once is not None:
        try:
            faz12_run_once()
            _set_faz("FAZ-12", True, "autoadjust ok")
        except Exception as e:
            _set_faz("FAZ-12", False, f"autoadjust crash: {e}")

    # FAZ-12 profile (opsiyonel)
    profile = None
    if faz12_auto_profile is not None:
        try:
            try:
                profile = faz12_auto_profile(meta)
            except TypeError:
                profile = faz12_auto_profile()
        except Exception as e:
            log.warning("FAZ-12 auto_profile failed (non-fatal): %s", e)
            profile = None

    # FAZ-17 market
    market_data, market_flag, market_reason = _try_fetch_market_safe(meta["league"], date_str, home, away)

    # FAZ-15 preprocess (opsiyonel)
    if faz15_preprocess is not None:
        try:
            try:
                faz15_preprocess(meta)
            except TypeError:
                faz15_preprocess()
            _set_faz("FAZ-15", True, "preprocess ok")
        except Exception as e:
            _set_faz("FAZ-15", False, f"preprocess crash: {e}")

    # FAZ-13 orchestrator (zorunlu gibi)
    if run_faz13_auto_pipeline is None:
        _set_faz("FAZ-13", False, "run_faz13_auto_pipeline missing")
        raise RuntimeError("FAZ-13 missing")

    # Çalıştır
    try:
        # imza toleransı: market_data paramı yoksa düşür
        try:
            result = run_faz13_auto_pipeline(
                league=meta["league"],
                date_str=date_str,
                home=home,
                away=away,
                source="manual",
                manual_text=None,
                api_data=None,
                visual_meta=None,
                market_data=market_data,
                profile=profile,
            )
        except TypeError:
            # market_data / profile desteklemeyen sürüm
            result = run_faz13_auto_pipeline(
                league=meta["league"],
                date_str=date_str,
                home=home,
                away=away,
                source="manual",
                manual_text=None,
                api_data=None,
                visual_meta=None,
            )
            if market_data is not None:
                market_flag = "NO_MARKET_DATA"
                market_reason = "orchestrator_signature_missing_market_data"
        _set_faz("FAZ-13", True, "pipeline ok")
    except Exception as e:
        _set_faz("FAZ-13", False, f"pipeline crash: {e}")
        raise

    if not isinstance(result, dict):
        result = {"result": result}

    # raw input debug
    result.setdefault("raw", {})
    result["raw"].setdefault("input", {})
    result["raw"]["input"].update(
        {
            "source": source_type,
            "league": meta["league"],
            "date_str": date_str,
            "home": home,
            "away": away,
            "market_flag": market_flag,
            "market_reason": market_reason,
            "market_data": market_data if market_data else {
                "ok": False,
                "main_total": None,
                "total_line": None,
                "confidence": 0.0,
                "sources": [],
                "reason": "disabled" if market_flag == "MARKET_DISABLED" else "no_sources_no_cache",
                "cache_hit": False,
            },
        }
    )

    # FAZ-22 meta engine (opsiyonel)
    if faz22_meta_engine is not None:
        try:
            extra = None
            try:
                extra = faz22_meta_engine(meta=meta, faz13_result=result)
            except TypeError:
                extra = faz22_meta_engine(result)
            result.setdefault("faz22", {})
            result["faz22"] = extra
            _set_faz("FAZ-22", True, "meta ok")
        except Exception as e:
            _set_faz("FAZ-22", False, f"meta crash: {e}")
            log.warning("FAZ-22 error: %s", e)

    # FAZ-23 meta evaluate (opsiyonel)
    if FAZ23_META_ENABLED and (faz23_meta_evaluate is not None):
        try:
            meta_out = None
            try:
                meta_out = faz23_meta_evaluate(
                    league=meta["league"],
                    date_str=date_str,
                    home=home,
                    away=away,
                    faz13_result=result,
                    market_data=market_data,
                )
            except TypeError:
                meta_out = faz23_meta_evaluate(league=meta["league"], date_str=date_str, home=home, away=away)
            result.setdefault("meta23", {})
            result["meta23"]["external"] = meta_out
            _set_faz("FAZ-23", True, "datahub ok")
        except Exception as e:
            _set_faz("FAZ-23", False, f"datahub crash: {e}")
            log.warning("FAZ-23 meta fail: %s", e)

    # FAZ-11 feedback (opsiyonel)
    if faz11_feedback is not None:
        try:
            outcome = "NEUTRAL"
            # outcome basit çıkarım
            m23 = (result or {}).get("meta23") or {}
            try:
                over = float(m23.get("model_over", 0.5))
                under = float(m23.get("model_under", 0.5))
                if over > under + 0.05:
                    outcome = "OVER"
                elif under > over + 0.05:
                    outcome = "UNDER"
            except Exception:
                outcome = "NEUTRAL"

            faz11_feedback(source_type, meta, _safe_json(result), outcome)
            _set_faz("FAZ-11", True, "feedback ok")
        except Exception as e:
            _set_faz("FAZ-11", False, f"feedback crash: {e}")
            log.warning("FAZ-11 feedback error: %s", e)

    return result


# ================================================================
# RENDERERS
# ================================================================
def _render_status() -> str:
    lines = ["🧩 FAZ STATUS:"]
    order = ["FAZ-7", "FAZ-10", "FAZ-11", "FAZ-12", "FAZ-13", "FAZ-15", "FAZ-17", "FAZ-22", "FAZ-23"]
    for k in order:
        s = FAZ_STATUS.get(k, {"ok": False, "msg": "unknown"})
        icon = "✅" if s.get("ok") else "🔴"
        lines.append(f"{icon} {k} - {s.get('msg')}")
    return "\n".join(lines)


def _render_prediction_message(result: dict, league: str, home: str, away: str) -> str:
    fusion_total = result.get("fusion_total") or result.get("total") or result.get("pred_total")
    band = result.get("band") or result.get("total_band")
    score_vector = result.get("score_vector") or result.get("vector")

    lines = []
    lines.append("🏀 FAZ-13 Maç Tahmini (Pro)")
    lines.append(f"Maç: {home} - {away}")
    lines.append(f"Lig: {league}")
    lines.append("—" * 28)

    if fusion_total is not None:
        lines.append(f"• Fusion Total: {fusion_total}")
    if band is not None:
        lines.append(f"• Bant: {band}")
    if score_vector is not None:
        lines.append(f"• Score Vector: {score_vector}")

    per = result.get("periods") or result.get("period_projection")
    if per:
        lines.append("—" * 28)
        lines.append("⏱️ Periyot:")
        lines.append(str(per))

    return "\n".join(lines)


# ================================================================
# TELEGRAM COMMANDS
# ================================================================
@bot.message_handler(commands=["start"])
def on_start(msg):
    bot.reply_to(
        msg,
        "Zeynal Core AI aktif.\n"
        "/mac LIG | YYYY-MM-DD | Ev - Dep\n"
        "/status -> FAZ durumları",
    )


@bot.message_handler(commands=["status"])
def on_status(msg):
    bot.reply_to(msg, _render_status())


@bot.message_handler(func=lambda m: (m.text or "").strip().startswith("/mac"))
def on_mac(msg):
    parsed = _parse_mac_command(msg.text)
    if not parsed:
        bot.reply_to(msg, "Format: /mac LIG | YYYY-MM-DD | Ev - Dep")
        return

    league, date_str, home, away = parsed
    bot.send_message(msg.chat.id, f"⏳ Analiz ediliyor:\n{league} | {date_str}\n{home} - {away}")

    try:
        result = run_match_pipeline(league, date_str, home, away, source_type="mac_command")
        bot.send_message(msg.chat.id, _render_prediction_message(result, _normalize_league_key(league), home, away))
        bot.send_message(msg.chat.id, _safe_json(result))
    except Exception as e:
        log.exception("MAC error")
        bot.reply_to(msg, f"❌ Hata: {e}")


# ================================================================
# WEBHOOK (Fly.io)
# ================================================================
@app.route("/", methods=["GET"])
def health():
    return "OK", 200


@app.route("/webhook", methods=["POST"])
def webhook():
    if WEBHOOK_SECRET:
        if request.headers.get("X-Webhook-Secret", "") != WEBHOOK_SECRET:
            return "FORBIDDEN", 403

    try:
        update = telebot.types.Update.de_json(request.get_data(as_text=True))
        bot.process_new_updates([update])
    except Exception as e:
        log.exception("Webhook processing error: %s", e)
    return "OK", 200


def _set_webhook_safe():
    if not WEBHOOK_URL:
        log.info("WEBHOOK_URL yok. (Local dev için normal)")
        return
    try:
        bot.remove_webhook()
        time.sleep(0.2)
        bot.set_webhook(url=WEBHOOK_URL)
        log.info("Webhook set: %s", WEBHOOK_URL)
    except Exception as e:
        log.warning("Webhook set failed: %s", e)


# Gunicorn import-time: crash yok, sadece dene
if AUTO_WEBHOOK:
    try:
        _set_webhook_safe()
    except Exception as _e:
        log.warning("AUTO_WEBHOOK failed: %s", _e)


# ================================================================
# MAIN (local)
# ================================================================
if __name__ == "__main__":
    _set_webhook_safe()
    app.run(host="0.0.0.0", port=PORT, threaded=False)

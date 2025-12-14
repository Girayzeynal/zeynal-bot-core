# -*- coding: utf-8 -*-
"""
Zeynal Core AI - FINAL BUILD (FAZ-7/10/11/12/13/15/17/22/23)
ENGINEERING / HIGH FOCUS / HATA AVCI MODE

Amaç:
- FAZ modüllerini "hayalet" olmaktan çıkarıp: ✅ / 🔴 net görünür yapmak
- Faz10/Faz11 imza uyuşmazlıklarını fixlemek
- Market (FAZ-17/FAZ-23) hata verse bile pipeline'ı kırmamak
- Fly.io 512MB free profile ile stabil çalışmak
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

# OCR / concurrency (Fly 512MB)
OCR_MAX_WORKERS = int(os.getenv("OCR_MAX_WORKERS", "2"))
OCR_TIMEOUT_S = int(os.getenv("OCR_TIMEOUT_S", "12"))

# Flags
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
# FAZ-13 OCR DEBUG STATE + GLOBAL OCR CACHE
# ================================================================
LAST_OCR_TEXT = None
LAST_OCR_META = {}

OCR_CACHE = {}  # {img_hash: {"text": str, "meta": dict, "ts": int}}
OCR_CACHE_LOCK = threading.Lock()
OCR_POOL = ThreadPoolExecutor(max_workers=OCR_MAX_WORKERS)

# ================================================================
# FAZ STATUS (✅ / 🔴)
# ================================================================
FAZ_STATUS = {}  # name -> {"ok": bool, "msg": str, "icon": str}


def _set_faz(name: str, ok: bool, msg: str = ""):
    FAZ_STATUS[name] = {
        "ok": bool(ok),
        "icon": "✅" if ok else "🔴",
        "msg": msg or ("OK" if ok else "MISSING/FAILED"),
    }


def _safe_import(module_path: str, symbol: str = None):
    """
    Import fail olursa crash yok: STATUS'a düşer, None döner.
    """
    try:
        mod = __import__(module_path, fromlist=[symbol] if symbol else [])
        if symbol:
            return getattr(mod, symbol)
        return mod
    except Exception as e:
        # burada "name" olarak modül yolunu yazmak yerine FAZ label'ları zaten ayrı set ediliyor
        log.warning(f"Import failed: {module_path}{'.'+symbol if symbol else ''} -> {e}")
        return None


# ================================================================
# IMPORTS (opsiyonel ama STATUS'a yazar)
# ================================================================
# FAZ-7
faz7_memory = _safe_import("faz7_engine.faz7_memory", "faz7_memory")
_set_faz("FAZ-7", faz7_memory is not None, "faz7_memory loaded" if faz7_memory else "faz7_memory missing")

# FAZ-10
faz10_stability_check = _safe_import("faz10_engine.faz10_stability", "faz10_stability_check")
_set_faz("FAZ-10", faz10_stability_check is not None, "stability loaded" if faz10_stability_check else "missing")

# FAZ-11
faz11_feedback = _safe_import("faz11_engine.faz11_feedback", "faz11_feedback")
faz11_last_summary = _safe_import("faz11_engine.faz11_feedback", "faz11_last_summary")
_set_faz("FAZ-11", faz11_feedback is not None, "feedback loaded" if faz11_feedback else "missing")

# FAZ-12
faz12_run_once = _safe_import("faz12_engine.faz12_autoadjust", "faz12_run_once")
faz12_auto_profile = _safe_import("faz12_engine.faz12_autoadjust", "faz12_auto_profile")
_set_faz("FAZ-12", faz12_run_once is not None, "autoadjust loaded" if faz12_run_once else "missing")

# FAZ-13
normalize_manual_text = _safe_import("faz13_engine.faz13_orchestrator", "normalize_manual_text")
normalize_api_data = _safe_import("faz13_engine.faz13_orchestrator", "normalize_api_data")
normalize_visual_meta = _safe_import("faz13_engine.faz13_orchestrator", "normalize_visual_meta")
run_faz13_auto_pipeline = _safe_import("faz13_engine.faz13_orchestrator", "run_faz13_auto_pipeline")
_set_faz("FAZ-13", run_faz13_auto_pipeline is not None, "orchestrator loaded" if run_faz13_auto_pipeline else "missing")

# FAZ-15
faz15_preprocess = _safe_import("faz15_engine.faz15_preprocess", "faz15_preprocess")
_set_faz("FAZ-15", faz15_preprocess is not None, "preprocess loaded" if faz15_preprocess else "missing")

# FAZ-17
faz17_fetch_market = _safe_import("faz17_engine.faz17_market_fetcher", "faz17_fetch_market")
faz17_market_adjust = _safe_import("faz17_engine.faz17_market_adjust", "faz17_market_adjust")
_set_faz("FAZ-17", (faz17_fetch_market is not None or not FAZ17_MARKET_ENABLED), "market enabled" if FAZ17_MARKET_ENABLED else "disabled")

# FAZ-22 (kullanıcının istediği isim: faz22_meta_engine)
faz22_meta_engine = _safe_import("faz22_engine.faz22_meta", "faz22_meta_engine")
_set_faz("FAZ-22", faz22_meta_engine is not None, "meta engine loaded" if faz22_meta_engine else "missing")

# FAZ-23 DataHub
fetch_match_totals = _safe_import("faz23_engine.faz23_datahub", "fetch_match_totals")
_set_faz("FAZ-23", fetch_match_totals is not None, "datahub loaded" if fetch_match_totals else "missing")

# ================================================================
# HELPERS
# ================================================================
def _now_ts() -> int:
    return int(time.time())


def _safe_json(obj) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, indent=2)
    except Exception:
        return str(obj)


def _parse_mac_command(text: str):
    """
    Beklenen:
    /mac NBA | 2025-12-14 | Orlando - New York
    """
    raw = (text or "").strip()
    raw = raw.replace("/mac", "", 1).strip()

    parts = [p.strip() for p in raw.split("|")]
    if len(parts) < 3:
        raise ValueError("Format hatası.\nÖrnek: /mac NBA | 2025-12-14 | Orlando - New York")

    league = parts[0]
    date_str = parts[1]
    teams = parts[2]

    if "-" not in teams:
        raise ValueError("Takım ayırıcı '-' yok.\nÖrnek: Orlando - New York")

    home, away = [x.strip() for x in teams.split("-", 1)]
    if not home or not away:
        raise ValueError("Home/Away boş görünüyor.")

    return league, date_str, home, away


def _build_meta(league: str, date_str: str, home: str, away: str, source_type: str):
    return {
        "league": league,
        "date": date_str,
        "home": home,
        "away": away,
        "source_type": source_type,
        "ts": _now_ts(),
    }


def get_market_data(league: str, date_str: str, home: str, away: str):
    """
    Market data toplayıcı (çökme yok):
    1) FAZ-23 DataHub (fetch_match_totals) -> içinde odds/line olabilir
    2) FAZ-17 fetcher (faz17_fetch_market)
    """
    market_data = None

    # 1) FAZ-23 DataHub
    if fetch_match_totals is not None:
        try:
            ext = fetch_match_totals(league=league, date_str=date_str, home=home, away=away)
            if isinstance(ext, dict):
                odds = ext.get("odds")
                if isinstance(odds, dict):
                    market_data = dict(odds)
                    market_data.setdefault("src", {"faz23": True})
        except Exception as e:
            log.warning(f"FAZ-23 datahub failed (non-fatal): {e}")

    # 2) FAZ-17
    if market_data is None and FAZ17_MARKET_ENABLED and faz17_fetch_market is not None:
        try:
            market_data = faz17_fetch_market(
                league=league,
                date_str=date_str,
                home=home,
                away=away,
                want_live=False,
            )
        except Exception as e:
            log.warning(f"FAZ-17 market fetch failed (non-fatal): {e}")
            market_data = None

    # 3) FAZ-17 adjust (opsiyonel)
    if market_data is not None and faz17_market_adjust is not None:
        try:
            market_data = faz17_market_adjust(market_data)
        except Exception as e:
            log.warning(f"FAZ-17 market adjust failed (non-fatal): {e}")

    return market_data


def _decide_outcome(result: dict) -> str:
    """
    FAZ-11 feedback için outcome.
    Basit: meta23 model_over vs model_under -> OVER/UNDER/NEUTRAL
    """
    try:
        m = (result or {}).get("meta23") or {}
        over = float(m.get("model_over", 0.5))
        under = float(m.get("model_under", 0.5))
        if over > under + 0.05:
            return "OVER"
        if under > over + 0.05:
            return "UNDER"
        return "NEUTRAL"
    except Exception:
        return "NEUTRAL"


# ================================================================
# CORE MATCH PIPELINE
# ================================================================
def run_match_pipeline(league: str, date_str: str, home: str, away: str, source_type: str = "mac_command"):
    meta = _build_meta(league, date_str, home, away, source_type=source_type)

    # FAZ-7 memory
    if faz7_memory is not None:
        try:
            try:
                faz7_memory(meta)
            except TypeError:
                faz7_memory()
            _set_faz("FAZ-7", True, "memory ok")
        except Exception as e:
            _set_faz("FAZ-7", False, f"memory crash: {e}")

    # FAZ-10
    if faz10_stability_check is not None:
        try:
            s = faz10_stability_check(source_type, meta)
            meta["faz10"] = s
            _set_faz("FAZ-10", True, "stability ok")
        except Exception as e:
            _set_faz("FAZ-10", False, f"stability crash: {e}")
            log.warning(f"FAZ-10 error: {e}")

    # FAZ-12 run
    if faz12_run_once is not None:
        try:
            faz12_run_once()
            _set_faz("FAZ-12", True, "autoadjust ok")
        except Exception as e:
            _set_faz("FAZ-12", False, f"autoadjust crash: {e}")
            log.warning(f"FAZ-12 error: {e}")

    # FAZ-12 profile
    profile = None
    if faz12_auto_profile is not None:
        try:
            try:
                profile = faz12_auto_profile(meta)
            except TypeError:
                profile = faz12_auto_profile()
        except Exception as e:
            log.warning(f"FAZ-12 auto_profile failed (non-fatal): {e}")
            profile = None

    # MARKET
    market_data = get_market_data(league, date_str, home, away)

    # FAZ-15 preprocess
    if faz15_preprocess is not None:
        try:
            try:
                faz15_preprocess(meta)
            except TypeError:
                faz15_preprocess()
            _set_faz("FAZ-15", True, "preprocess ok")
        except Exception as e:
            _set_faz("FAZ-15", False, f"preprocess crash: {e}")
            log.warning(f"FAZ-15 error: {e}")

    # FAZ-13
    if run_faz13_auto_pipeline is None:
        _set_faz("FAZ-13", False, "run_faz13_auto_pipeline missing")
        raise RuntimeError("FAZ-13 missing")

    result = run_faz13_auto_pipeline(
        league=league,
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
    _set_faz("FAZ-13", True, "pipeline ok")

    # FAZ-22 meta
    if faz22_meta_engine is not None:
        try:
            try:
                extra = faz22_meta_engine(meta=meta, faz13_result=result)
            except TypeError:
                extra = faz22_meta_engine(result)
            result["faz22"] = extra
            _set_faz("FAZ-22", True, "meta ok")
        except Exception as e:
            _set_faz("FAZ-22", False, f"meta crash: {e}")
            log.warning(f"FAZ-22 error: {e}")

    # FAZ-23 meta flag
    if FAZ23_META_ENABLED:
        _set_faz("FAZ-23", fetch_match_totals is not None, "meta enabled")

    # FAZ-11 feedback
    if faz11_feedback is not None:
        try:
            result_text = _safe_json(result)
            outcome = _decide_outcome(result)
            faz11_feedback(source_type, meta, result_text, outcome)
            _set_faz("FAZ-11", True, "feedback ok")
        except Exception as e:
            _set_faz("FAZ-11", False, f"feedback crash: {e}")
            log.warning(f"FAZ-11 feedback error: {e}")

    return result


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
    lines = ["🧩 FAZ STATUS:"]
    order = ["FAZ-7", "FAZ-10", "FAZ-11", "FAZ-12", "FAZ-13", "FAZ-15", "FAZ-17", "FAZ-22", "FAZ-23"]
    for k in order:
        s = FAZ_STATUS.get(k, {"icon": "🔴", "msg": "unknown"})
        lines.append(f"{s.get('icon','🔴')} {k} - {s.get('msg','')}")
    bot.reply_to(msg, "\n".join(lines))


@bot.message_handler(commands=["mac"])
def on_mac(msg):
    text = msg.text or ""
    try:
        league, date_str, home, away = _parse_mac_command(text)
    except Exception as e:
        bot.reply_to(msg, f"❌ {e}")
        return

    bot.reply_to(msg, f"⏳ Analiz ediliyor:\n{league} | {date_str}\n{home} - {away}")

    try:
        result = run_match_pipeline(league, date_str, home, away, source_type="mac_command")
        bot.reply_to(msg, _safe_json(result))
    except Exception as e:
        bot.reply_to(msg, f"❌ Hata: {e}")


# ================================================================
# WEBHOOK (Fly.io)
# ================================================================
@app.get("/")
def health():
    return "OK", 200


@app.post("/webhook")
def telegram_webhook():
    if WEBHOOK_SECRET:
        token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if token != WEBHOOK_SECRET:
            return "forbidden", 403

    update = request.get_data(as_text=True)
    try:
        upd = telebot.types.Update.de_json(update)
        bot.process_new_updates([upd])
    except Exception as e:
        log.exception(f"Webhook update parse error: {e}")

    return "OK", 200


def _maybe_set_webhook():
    if not AUTO_WEBHOOK:
        log.info("AUTO_WEBHOOK=0 -> webhook ayarlanmayacak.")
        return
    if not WEBHOOK_URL:
        log.warning("WEBHOOK_URL boş -> webhook ayarlanamadı (polling de yok).")
        return
    try:
        bot.remove_webhook()
        time.sleep(0.2)
        bot.set_webhook(url=WEBHOOK_URL, secret_token=WEBHOOK_SECRET if WEBHOOK_SECRET else None)
        log.info("Webhook set OK.")
    except Exception as e:
        log.warning(f"Webhook set failed: {e}")


# ================================================================
# BOOTSTRAP (Gunicorn altında da webhook/polling çalışsın)
# ================================================================
_BOOT_LOCK = threading.Lock()
_BOOT_DONE = False

def _start_polling():
    try:
        bot.infinity_polling(timeout=20, long_polling_timeout=20)
    except Exception as e:
        log.warning(f"Polling failed: {e}")

def _boot_once():
    global _BOOT_DONE
    with _BOOT_LOCK:
        if _BOOT_DONE:
            return
        _BOOT_DONE = True

    # Webhook'u gunicorn altında da set et
    if AUTO_WEBHOOK and WEBHOOK_URL:
        _maybe_set_webhook()

    # 🔥 SADECE webhook YOKSA ve AUTO_WEBHOOK kapalıysa polling
    if (not WEBHOOK_URL) and (not AUTO_WEBHOOK):
        threading.Thread(
            target=_start_polling,
            daemon=True
        ).start()

@app.before_request
def _boot_hook():
    # İlk gelen request ile bir kere boot et
    _boot_once()


if __name__ == "__main__":
    _maybe_set_webhook()
    # Fly.io gunicorn kullanıyorsa burası çalışmaz zaten.
    # Lokal debug için:
    # app.run(host="0.0.0.0", port=PORT)

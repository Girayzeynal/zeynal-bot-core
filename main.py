import os
import json
import logging
from typing import Any, Dict, Optional, List

import telebot
from telebot import types
from flask import Flask, request

# ================================================================
# 🔧 LOGGING
# ================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("hoopbrain-main")

# ================================================================
# ⚙️ CONFIG & GLOBALS
# ================================================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
ENGINEERING_MODE = os.getenv("ENGINEERING_MODE", "ON").upper() == "ON"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is required")

PORT = int(os.getenv("PORT", "8080"))

DATA_DIR = os.getenv("DATA_DIR", "/data")
FAZ7_DIR = os.path.join(DATA_DIR, "faz7")
os.makedirs(FAZ7_DIR, exist_ok=True)

FAZ7_MEMORY_FILE = os.path.join(FAZ7_DIR, "faz7_memory.json")
FAZ11_HISTORY_FILE = os.path.join(FAZ7_DIR, "faz11_history.json")

VISUAL_STACK: List[Dict[str, Any]] = []
VISUAL_STACK_MAX = 32

# FAZ-23 MAX Global holder
LAST_FAZ13_META = {}
FAZ23_MODE = os.getenv("FAZ23_MODE", "MAX").upper()
FAZ23_DEFAULT_BAREMS = [229.5, 231.5, 233.5, 235.5]

# ================================================================
# 🧩 SAFE IMPORT HELPERS
# ================================================================
def _safe_import(module_path: str, attrs: Optional[List[str]] = None):
    try:
        module = __import__(module_path, fromlist=attrs or [])
    except Exception as e:
        log.debug("SAFE IMPORT FAILED: %s (%s)", module_path, e)
        if not attrs:
            return None
        return {name: None for name in attrs}

    if not attrs:
        return module

    out = {}
    for name in attrs:
        try:
            out[name] = getattr(module, name)
        except Exception:
            out[name] = None
    return out

# ================================================================
# 📦 IMPORT FAZ MODULES
# ================================================================
_faz10 = _safe_import("faz10_engine.faz10_stability", ["faz10_stability_check"])
faz10_stability_check = (_faz10 or {}).get("faz10_stability_check")

_faz11 = _safe_import("faz11_engine.faz11_feedback", ["faz11_feedback", "faz11_last_summary"])
faz11_feedback = (_faz11 or {}).get("faz11_feedback")
faz11_last_summary = (_faz11 or {}).get("faz11_last_summary")

_faz12 = _safe_import("faz12_engine.faz12_autoadjust", ["faz12_run_once", "faz12_auto_profile"])
faz12_run_once = (_faz12 or {}).get("faz12_run_once")
faz12_auto_profile = (_faz12 or {}).get("faz12_auto_profile")

_faz13 = _safe_import(
    "faz13_engine.faz13_orchestrator",
    [
        "normalize_manual_text",
        "normalize_visual_meta",
        "normalize_api_data",
        "run_faz13_auto_pipeline",
        "faz13_daily_coupon",
        "faz13_upcoming_coupon",
        "faz13_league_coupon",
        "faz13_live_coupon",
    ],
)
normalize_manual_text = (_faz13 or {}).get("normalize_manual_text")
normalize_visual_meta = (_faz13 or {}).get("normalize_visual_meta")
normalize_api_data = (_faz13 or {}).get("normalize_api_data")
run_faz13_auto_pipeline = (_faz13 or {}).get("run_faz13_auto_pipeline")
faz13_daily_coupon = (_faz13 or {}).get("faz13_daily_coupon")
faz13_upcoming_coupon = (_faz13 or {}).get("faz13_upcoming_coupon")
faz13_league_coupon = (_faz13 or {}).get("faz13_league_coupon")
faz13_live_coupon = (_faz13 or {}).get("faz13_live_coupon")

from faz13_engine.league_autodetect import guess_league

_faz13_god = _safe_import("faz13_engine.faz13_god_layer", ["run_faz13_with_god_layer"])
run_faz13_with_god_layer = (_faz13_god or {}).get("run_faz13_with_god_layer")

_faz17 = _safe_import("faz17_engine.faz17_market_adjust", ["faz17_market_adjust"])
faz17_market_adjust = (_faz17 or {}).get("faz17_market_adjust")

_faz22 = _safe_import("faz22_engine.faz22_meta", ["faz22_meta_engine"])
faz22_meta_engine = (_faz22 or {}).get("faz22_meta_engine")

_faz13_ocr = _safe_import("faz13_engine.ultra_ocr_v3", ["ultra_ocr_engine_v3"])
_ext_ultra_ocr_engine_v3 = (_faz13_ocr or {"ultra_ocr_engine_v3": None}).get("ultra_ocr_engine_v3")

_faz23meta = _safe_import(
    "faz23_engine.faz23_meta_engine",
    ["faz23_prematch_predict", "faz23_live_predict", "faz23_news_enrich"],
)
faz23_prematch_predict = (_faz23meta or {}).get("faz23_prematch_predict")
faz23_live_predict = (_faz23meta or {}).get("faz23_live_predict")
faz23_news_enrich = (_faz23meta or {}).get("faz23_news_enrich")

_fazlive = _safe_import("live_providers.core", ["get_live_match_global", "HoopbrainLiveError"])
get_live_match_global = (_fazlive or {}).get("get_live_match_global")
HoopbrainLiveError = (_fazlive or {}).get("HoopbrainLiveError")

# ================================================================
# 🧠 FAZ-23 MAX ENGINE IMPORT
# ================================================================
from faz23_engine.faz23_max import (
    Faz23MaxConfig,
    faz23_max_predict,
    faz23_max_comment,
    build_fusion_vector,
)

# ================================================================
# 🧠 FALLBACKS & MEMORY HELPERS
# ================================================================
def _safe_float(val: Any):
    try:
        return float(str(val).replace(",", "."))
    except:
        return None

def _load_json(path: str, default: Any):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return default

def _save_json(path: str, data: Any):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.error("JSON kaydedilemedi: %s (%s)", path, e)

def faz7_load_memory():
    mem = _load_json(FAZ7_MEMORY_FILE, {})
    mem.setdefault("stats", {})
    return mem

def faz7_save_memory(mem):
    _save_json(FAZ7_MEMORY_FILE, mem)

def faz7_touch_stat(key: str, delta: int = 1):
    mem = faz7_load_memory()
    stats = mem.get("stats", {})
    stats[key] = stats.get(key, 0) + delta
    mem["stats"] = stats
    faz7_save_memory(mem)

# ================================================================
# 🧱 FAZ-10 HardSync
# ================================================================
def faz10_hardsync(brain: dict, calib: Optional[dict] = None):
    if faz10_stability_check is None:
        return {
            "regime": "NORMAL",
            "stability_score": 1.0,
            "anomaly_level": 0.0,
            "suggested_mode": brain.get("mode", "INIT"),
            "bucket": (calib or {}).get("bucket", "MID"),
            "lock": False,
            "lock_reason": "NO_FAZ10_MODULE",
        }
    try:
        stability = faz10_stability_check("FAZ-13", {}) or {}
    except:
        stability = {}

    regime = stability.get("regime", "NORMAL").upper()
    score = float(stability.get("stability_score", 1.0))
    anomaly = float(stability.get("anomaly_level", 0.0))
    suggested_mode = stability.get("suggested_mode", "INIT").upper()

    lock = False
    lock_reason = "NO_LOCK"
    if ENGINEERING_MODE and (regime in ("CRITICAL", "UNSTABLE") or anomaly >= 0.7):
        lock = True
        lock_reason = "CRITICAL_LOCK"

    return {
        "regime": regime,
        "stability_score": score,
        "anomaly_level": anomaly,
        "suggested_mode": suggested_mode,
        "bucket": (calib or {}).get("bucket", "MID"),
        "lock": lock,
        "lock_reason": lock_reason,
    }

# ================================================================
# 🔎 ULTRA OCR ENGINE v3
# ================================================================
def ultra_ocr_engine_v3(img_bytes: bytes) -> Dict[str, Any]:
    if _ext_ultra_ocr_engine_v3:
        try:
            return _ext_ultra_ocr_engine_v3(img_bytes)
        except Exception as e:
            log.error("Ultra OCR v3 hata: %s", e)
    return {"text": "", "meta": {"engine": "NONE"}}

# ================================================================
# 🤖 TELEGRAM BOT
# ================================================================
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
app = Flask(__name__)

def _send_long_text(message, text):
    max_len = 3500
    for i in range(0, len(text), max_len):
        bot.reply_to(message, text[i:i+max_len])

# ================================================================
# /test_faz13
# ================================================================
@bot.message_handler(commands=["test_faz13"])
def cmd_test_faz13(message):
    try:
        from faz13_engine.faz13_orchestrator import run_faz13_auto_pipeline
        result = run_faz13_auto_pipeline(
            league="NBA",
            date="2025-01-01",
            home_team="TEST_HOME",
            away_team="TEST_AWAY",
            full_output=False,
        )
        text = (
            "🧪 *FAZ-13 Test*\n"
            f"Match: {result['match']}\n"
            f"Fusion: {result['fusion_total_call']}\n"
            f"Vector: {result['internal_score_vector']}"
        )
        bot.reply_to(message, text, parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ test_faz13 hata: {e}")

# ================================================================
# 🏀 /mac — FAZ-13 tahmin
# ================================================================
@bot.message_handler(commands=["mac"])
def cmd_mac(message):
    try:
        txt = message.text.replace("/mac", "").strip()
        if "|" not in txt:
            bot.reply_to(message, "Format: /mac Euroleague | 2025-12-05 | A - B")
            return

        league, date, teams = [p.strip() for p in txt.split("|")]

        if "-" not in teams:
            bot.reply_to(message, "Takım formatı hatalı.")
            return

        home, away = [p.strip() for p in teams.split("-")]

        result = run_faz13_auto_pipeline(
            league=league,
            date=date,
            home_team=home,
            away_team=away,
            full_output=True,
        )

        # ⭐ FAZ-23 MAX meta yakalama
        global LAST_FAZ13_META
        if isinstance(result, dict) and "internal_meta" in result:
            LAST_FAZ13_META = result["internal_meta"]

        text = (
            f"🎯 *FAZ-13 Tahmin*\n"
            f"Maç: {result['match']}\n"
            f"Fusion: {result['fusion_total_call']}\n"
            f"Vector: {result['internal_score_vector']}"
        )
        bot.reply_to(message, text, parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ /mac hata: {e}")

# ================================================================
# 🚀 /faz23 — FAZ-23 MAX ANA TAHMİN
# ================================================================
def faz23_build_fusion_from_faz13(meta: dict) -> dict:
    return {
        "base_total": meta.get("base_total", 165.0),
        "tempo_factor": meta.get("tempo_factor", 1.0),
        "defense_factor": meta.get("defense_factor", 1.0),
        "pace_volatility": meta.get("pace_volatility", 1.0),
        "defense_volatility": meta.get("defense_volatility", 1.0),
        "home_adv": meta.get("home_adv", 1.0),
        "h2h_factor": meta.get("h2h_factor", 1.0),
        "hot_shooting_risk": meta.get("hot_shooting_risk", 1.0),
        "clutch_factor": meta.get("clutch_factor", 1.0),
        "national_bonus": meta.get("national_bonus", 1.0),
        "schedule_fatigue": meta.get("schedule_fatigue", 1.0),
        "style_pace": meta.get("style_pace", 1.0),
    }

@bot.message_handler(commands=["faz23"])
def cmd_faz23(message):
    try:
        if FAZ23_MODE != "MAX":
            bot.reply_to(message, "FAZ-23 MAX modu kapalı.")
            return

        global LAST_FAZ13_META
        if not LAST_FAZ13_META:
            bot.reply_to(message, "❌ Önce /mac çalıştır → FAZ-13 meta gelsin.")
            return

        raw = message.text.replace("/faz23", "").strip()
        if raw:
            try:
                barems = [float(x) for x in raw.split(",")]
            except:
                bot.reply_to(message, "Barem formatı yanlış.")
                return
        else:
            barems = FAZ23_DEFAULT_BAREMS

        match_meta = {
            "league": LAST_FAZ13_META.get("league", "Unknown"),
            "season": LAST_FAZ13_META.get("season", "2025-26"),
            "home": LAST_FAZ13_META.get("home_team", "HOME"),
            "away": LAST_FAZ13_META.get("away_team", "AWAY"),
            "type": LAST_FAZ13_META.get("match_type", "club"),
            "stage": LAST_FAZ13_META.get("stage", "league"),
            "start_ts": LAST_FAZ13_META.get("start_ts", int(time.time())),
        }

        fusion = faz23_build_fusion_from_faz13(LAST_FAZ13_META)

        cfg = Faz23MaxConfig()
        result = faz23_max_predict(
            match_meta=match_meta,
            fusion_input=fusion,
            barem_grid=barems,
            cfg=cfg,
        )
        comment = faz23_max_comment(result)
        _send_long_text(message, comment)

    except Exception as e:
        bot.reply_to(message, f"❌ /faz23 hata: {e}")

# ================================================================
# 🌐 FLASK ROUTES
# ================================================================
@app.route("/", methods=["GET"])
def index():
    return "HoopBrain FAZ-CORE: OK", 200

@app.route("/webhook", methods=["POST"])
def telegram_webhook():
    if request.headers.get("content-type") == "application/json":
        update = telebot.types.Update.de_json(request.get_data().decode("utf-8"))
        bot.process_new_updates([update])
    return "OK", 200

# ================================================================
# 🚀 MAIN
# ================================================================
if __name__ == "__main__":
    if not WEBHOOK_URL:
        bot.infinity_polling(skip_pending=True)
    else:
        try:
            info = bot.get_webhook_info()
            if info.url != WEBHOOK_URL:
                bot.delete_webhook()
                bot.set_webhook(url=WEBHOOK_URL)
        except:
            pass
        app.run(host="0.0.0.0", port=PORT)

import os
import json
import time
import logging
import hashlib

import telebot
import numpy as np
import pandas as pd
from flask import Flask, request


# ================================================================
# 🔧 LOGGING
# ================================================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


# ================================================================
# 🔧 CONFIG
# ================================================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", 8080))

if not BOT_TOKEN:
    raise Exception("BOT_TOKEN bulunamadı.")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
app = Flask(__name__)


# ================================================================
# 🔧 SAFE IMPORT HELPER
# ================================================================
def _safe_import(path: str, names: list):
    try:
        module = __import__(path, fromlist=names)
        return {name: getattr(module, name, None) for name in names}
    except Exception as e:
        log.error("Import error [%s]: %s", path, e)
        return {name: None for name in names}


# ================================================================
# 🔧 IMPORT FAZ MODULES
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

_faz13_god = _safe_import("faz13_engine.faz13_god_layer", ["run_faz13_with_god_layer"])
run_faz13_with_god_layer = (_faz13_god or {}).get("run_faz13_with_god_layer")

_faz17 = _safe_import("faz17_engine.faz17_market_adjust", ["faz17_market_adjust"])
faz17_market_adjust = (_faz17 or {}).get("faz17_market_adjust")

_faz22 = _safe_import("faz22_engine.faz22_meta", ["faz22_meta_engine"])
faz22_meta_engine = (_faz22 or {}).get("faz22_meta_engine")

_faz13ocr = _safe_import("faz13_engine.ultra_ocr_v3", ["ultra_ocr_engine_v3"])
_ext_ultra_ocr_engine_v3 = (_faz13ocr or {}).get("ultra_ocr_engine_v3")

# ================================================================
#  FAZ-23 MAX IMPORT
# ================================================================
try:
    # Hem tahmin motoru hem de config TEK dosyadan geliyor
    from faz23_engine.faz23_max import Faz23MaxConfig, faz23_max_predict
except Exception as e:
    log.error(f"[FAZ-23] Import error: {e}")
    faz23_max_predict = None
    Faz23MaxConfig = None


# ================================================================
# 🔧 GLOBAL STATE
# ================================================================
LAST_FAZ13_META = None


# ================================================================
# 🔥 UNIVERSAL RESULT NORMALIZER (TÜM FAZ'LARI STABİL HALE GETİREN ÇEKİRDEK)
# ================================================================
def normalize_result(result):
    # None → boş
    if result is None:
        return {
            "match": "N/A",
            "fusion_total_call": None,
            "internal_score_vector": None,
            "comment": "No result",
            "internal_meta": {},
        }

    # Eğer zaten dict ise direkt return
    if isinstance(result, dict):
        return result

    # Eğer tuple ise → FAZ-13 veya FAZ-23 format
    if isinstance(result, tuple):
        try:
            # En az 4 eleman varsa meta, fusion, vector, comment
            if len(result) >= 4:
                meta = result[0]
                fusion_call = result[1]
                vector = result[2]
                comment = result[3]

                # meta dict değilse fallback dict
                if not isinstance(meta, dict):
                    meta = {}

                return {
                    "match": f"{meta.get('home_team', 'Unknown')} - {meta.get('away_team', 'Unknown')}",
                    "fusion_total_call": fusion_call,
                    "internal_score_vector": vector,
                    "comment": comment,
                    "internal_meta": meta,
                }
        except:
            pass

        # Tuple çözülemezse → string'e sarmala
        return {
            "match": "Unknown",
            "fusion_total_call": None,
            "internal_score_vector": None,
            "comment": str(result),
            "internal_meta": {},
        }

    # String → hata mesajı olabilir → sarmala
    if isinstance(result, str):
        return {
            "match": "Unknown",
            "fusion_total_call": None,
            "internal_score_vector": None,
            "comment": result,
            "internal_meta": {},
        }

    # Hiçbir şeye uymadı → fallback
    return {
        "match": "Unknown",
        "fusion_total_call": None,
        "internal_score_vector": None,
        "comment": "Invalid format",
        "internal_meta": {},
    }


# ================================================================
# TELEGRAM BOT HELPERS
# ================================================================
def _send_long_text(message, text: str):
    max_len = 3500
    for i in range(0, len(text), max_len):
        bot.reply_to(message, text[i:i + max_len])


# ================================================================
# /mac — FAZ-13 tahmin komutu
# ================================================================
@bot.message_handler(commands=["mac"])
def cmd_mac(message):
    global LAST_FAZ13_META

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

        # FAZ-13 PIPELINE
        raw = run_faz13_auto_pipeline(
            league=league,
            date=date,
            home_team=home,
            away_team=away,
            full_output=True,
        )

        result = normalize_result(raw)

        # FAZ-23 MAX meta yakalama
        if "internal_meta" in result:
            LAST_FAZ13_META = result["internal_meta"]

        text = (
            " *FAZ-13 Tahmin*\n"
            f"Maç: {result['match']}\n"
            f"Fusion: {result['fusion_total_call']}\n"
            f"Vector: {result['internal_score_vector']}"
        )

        bot.reply_to(message, text, parse_mode="Markdown")

    except Exception as e:
        bot.reply_to(message, f"❌ /mac hata: {e}")


# ================================================================
# /faz23 — FAZ-23 MAX ANA TAHMİN
# ================================================================
@bot.message_handler(commands=["faz23"])
def cmd_faz23(message):
    try:
        if LAST_FAZ13_META is None:
            bot.reply_to(message, "❌ Önce /mac çalıştır → FAZ-13 meta gelsin.")
            return

        raw = faz23_max_predict(
            match_meta=LAST_FAZ13_META,
            fusion_input=LAST_FAZ13_META,
            barem_grid=[165, 170, 175],
            cfg=Faz23MaxConfig(),
        )

        result = normalize_result(raw)

        text = (
            " *FAZ-23 MAX*\n"
            f"Maç: {result['match']}\n"
            f"Fusion: {result['fusion_total_call']}\n"
            f"Vector: {result['internal_score_vector']}"
        )

        bot.reply_to(message, text, parse_mode="Markdown")

    except Exception as e:
        bot.reply_to(message, f"❌ /faz23 hata: {e}")


# ================================================================
# /status — Sistem Durumu
# ================================================================
@bot.message_handler(commands=["status"])
def cmd_status(message):
    text = (
        "🧠 FAZ-CORE STATUS\n\n"
        f"ENGINEERING_MODE: ON\n"
        f"LAST_FAZ13_META: {'VAR' if LAST_FAZ13_META else 'YOK'}\n"
        f"WEBHOOK_URL: {WEBHOOK_URL if WEBHOOK_URL else 'NOT SET'}\n"
    )
    bot.reply_to(message, text)


# ================================================================
# FLASK ROUTES — TELEGRAM WEBHOOK
# ================================================================
@app.route("/", methods=["GET"])
def index():
    return "HoopBrain FAZ-CORE OK", 200


@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        json_str = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return "OK", 200
    except Exception as e:
        log.error("Webhook error: %s", e)
        return "OK", 200


# ================================================================
# MAIN
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

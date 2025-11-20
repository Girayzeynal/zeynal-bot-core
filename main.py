import os
import sys
import time
import json
from typing import List, Any, Dict
from threading import Thread

import requests
import numpy as np
import pandas as pd
import telebot
from flask import Flask, request

# ============================================================
#                     BOT & CONFIG
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    print("ERROR: BOT_TOKEN ortam değişkeni tanımlı değil.")
    sys.exit(1)

bot = telebot.TeleBot(BOT_TOKEN)

MEMORY_FILE = "faz7_memory.json"

# Webhook ayarı:
#   WEBHOOK_URL = https://<app-adin>.fly.dev/webhook
TELEGRAM_MODE = os.getenv("TELEGRAM_MODE", "webhook").lower()
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# ============================================================
#                 FLASK APP (Fly.io + Webhook)
# ============================================================

app = Flask(__name__)


@app.route("/", methods=["GET"])
def index():
    # Fly.io health check endpoint
    return "OK", 200


@app.route("/webhook", methods=["POST"])
def telegram_webhook():
    # Telegram webhook POST -> TeleBot'a ilet
    if request.headers.get("content-type") == "application/json":
        json_str = request.get_data().decode("utf-8")
        data = json.loads(json_str)
        update = telebot.types.Update.de_json(data)
        bot.process_new_updates([update])
        return "OK", 200
    return "Unsupported Media Type", 415


# ============================================================
#            FAZ-4 NBA SİMÜLASYON MOTORU
# ============================================================

from nba_fetcher import fetch_nba_live_games
from nba_analyzer import analyze_live_games
from nba_models import NBAGameState


def _simple_sim_from_game(game: NBAGameState) -> dict:
    hs = game.home_stats
    aw = game.away_stats

    if not hs or not aw:
        return {
            "home": game.home_team,
            "away": game.away_team,
            "score_est": None,
            "pace_est": None,
            "pick": "YOK",
            "confidence": 0.0,
        }

    score_est = hs.pts + aw.pts

    home_pace = hs.pace_est if hs.pace_est is not None else 0
    away_pace = aw.pace_est if aw.pace_est is not None else 0
    pace_est = round((home_pace + away_pace) / 2, 1)

    diff = hs.pts - aw.pts
    if diff > 0:
        pick = game.home_team
    elif diff < 0:
        pick = game.away_team
    else:
        pick = "DENGELİ"

    from math import fabs
    confidence = max(0.5, min(0.99, fabs(diff) / 20.0))

    return {
        "home": game.home_team,
        "away": game.away_team,
        "score_est": round(score_est, 1),
        "pace_est": pace_est,
        "pick": pick,
        "confidence": round(confidence, 2),
    }


# ============================================================
#                    FAZ-5 ENGINE
# ============================================================

from faz5_engine.heavy_engine_main import run_heavy_engine


# ============================================================
#                    FAZ-6 ENGINE WRAPPER
# ============================================================

from faz6_engine import run_faz6_engine, build_coupon_message as faz6_build_coupon_message


def safe_run_faz6_engine(mode: str) -> Dict[str, Any]:
    try:
        result = run_faz6_engine(mode=mode)
        if not isinstance(result, dict):
            return {
                "status": "error",
                "detail": f"Motor beklenmeyen tip döndürdü: {type(result).__name__}",
                "raw": result,
            }

        if "status" not in result:
            result = {"status": "ok", **result}

        return result

    except Exception as e:
        return {
            "status": "error",
            "detail": f"FAZ-6 motor exception: {repr(e)}",
        }


def format_faz6_message(result: dict) -> str:
    if not isinstance(result, dict):
        return f"❌ *FAZ-6 HATA*\nGeçersiz sonuç tipi: {type(result).__name__}"

    status = result.get("status", "ok")
    if status != "ok":
        detail = result.get("detail")
        if not detail:
            detail = f"Detay yok. Ham sonuç: {repr(result)}"
        return f"❌ *FAZ-6 HATA*\n{detail}"

    mode = result.get("mode", "").upper()
    output = result.get("result", {})
    preds = output.get("predictions") or output.get("portfolio") or []

    text = f"🧠 *FAZ-6 {mode} SONUCU*\n\n"

    for p in preds:
        text += (
            f"📌 {p.get('id')}\n"
            f"🎯 {p.get('pick')} ({p.get('market')})\n"
            f"📈 Güven: {p.get('confidence')} | Edge: {p.get('edge')}\n"
            f"💰 Stake: {p.get('recommended_stake')}\n"
            f"— — —\n"
        )

    if len(text) > 3800:
        text = text[:3800] + "\n… (çıktı kısaltıldı)"

    return text


# ============================================================
#          FAZ-7.9 MEMORY / STRATEJİ MOTORU
# ============================================================

def init_memory():
    if not os.path.exists(MEMORY_FILE):
        data = {
            "days": [],
            "safe": 0,
            "bal": 0,
            "agg": 0,
        }
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)


def load_memory() -> Dict[str, Any]:
    init_memory()
    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_memory(data: Dict[str, Any]) -> None:
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def register_daily_stats(conf: float, edge: float) -> None:
    mem = load_memory()
    today = {
        "ts": int(time.time()),
        "conf": float(conf),
        "edge": float(edge),
    }
    mem["days"].append(today)
    # sadece son 7 günü tut
    if len(mem["days"]) > 7:
        mem["days"] = mem["days"][-7:]
    save_memory(mem)


def faz79_brain() -> Dict[str, Any]:
    mem = load_memory()
    days = mem.get("days", [])

    if len(days) == 0:
        return {
            "mode": "INIT",
            "conf": 0.0,
            "edge": 0.0,
            "trend": "INIT",
            "slope": 0.0,
            "vol": 0.0,
            "stake_norm": 1.00,
            "safe": False,
            "bal": True,
            "agg": False,
        }

    df = pd.DataFrame(days)
    df["t"] = range(len(df))

    avg_conf = float(df["conf"].mean())
    avg_edge = float(df["edge"].mean())

    if len(df) >= 2:
        slope = float(np.polyfit(df["t"], df["conf"], 1)[0])
        vol = float(df["conf"].std())
    else:
        slope = 0.0
        vol = 0.0

    if slope > 0.01:
        trend = "UP"
    elif slope < -0.01:
        trend = "DOWN"
    else:
        trend = "FLAT"

    if avg_conf > 0.7 and avg_edge > 0.05:
        mode = "SAFE"
    elif avg_conf > 0.4:
        mode = "BAL"
    else:
        mode = "AGG"

    return {
        "mode": mode,
        "conf": round(avg_conf, 3),
        "edge": round(avg_edge, 3),
        "trend": trend,
        "slope": round(slope, 4),
        "vol": round(vol, 4),
        "stake_norm": 1.00,
        "safe": mode == "SAFE",
        "bal": mode == "BAL",
        "agg": mode == "AGG",
    }


# ============================================================
#                    TELEGRAM KOMUTLARI
# ============================================================

@bot.message_handler(commands=["start"])
def start_cmd(message):
    bot.reply_to(
        message,
        "🔥 Bot aktif!\nFAZ-4 + FAZ-5 + FAZ-6 + FAZ-7.9 bağlı.\nKomut listesi için /help yaz.",
    )


@bot.message_handler(commands=["help"])
def help_cmd(message):
    bot.reply_to(
        message,
        """
📌 Komutlar:

/start - Botu başlatır
/help - Komut listesi
/status - Sistem durumu

/simulate_nba - NBA canlı simülasyon

/heavy - FAZ-5 Standart
/heavy_risk - FAZ-5 Risk
/heavy_edge - FAZ-5 Edge
/heavy_auto - FAZ-5 Auto
/heavy_full - FAZ-5 Full

/faz6_test - FAZ-6 Test
/faz6_auto - FAZ-6 Auto
/faz6_risk - FAZ-6 Risk
/faz6_edge - FAZ-6 Edge
/faz6_real - FAZ-6 Real
/faz6_balance - FAZ-6 Balance
/faz6_coupon - FAZ-6 Kupon

/faz7_status - FAZ-7.9 hafıza özeti
/faz7_plan   - FAZ-7.9 strateji planı
""",
    )


@bot.message_handler(commands=["status"])
def status_cmd(message):
    bot.reply_to(
        message,
        "🟢 Sistem stabil.\nFAZ-4 aktif.\nFAZ-5 bağlı.\nFAZ-6 online.\nFAZ-7.9 hafıza motoru açık.",
    )


# ----- FAZ-4: NBA -----

@bot.message_handler(commands=["simulate_nba"])
def simulate_nba_cmd(message):
    bot.send_message(message.chat.id, "🏀 Simülasyon başlatılıyor...")

    games: List[NBAGameState] = fetch_nba_live_games()
    if not games:
        bot.send_message(message.chat.id, "Canlı NBA verisi bulunamadı.")
        return

    results = [_simple_sim_from_game(g) for g in games]
    analysis = analyze_live_games(games)

    reply = "📊 *NBA Simülasyon Sonuçları*\n\n"
    for r in results:
        reply += (
            f"🏠 {r['home']} vs ✈️ {r['away']}\n"
            f"📈 Tahmini Skor: {r['score_est']}\n"
            f"⏱ Tempo: {r['pace_est']}\n"
            f"🎯 Kazanan: {r['pick']} ({int(r['confidence'] * 100)}%)\n\n"
        )

    reply += "🧠 Ham Analiz:\n" + analysis

    bot.send_message(message.chat.id, reply, parse_mode="Markdown")


# ----- FAZ-5: HEAVY ENGINE -----

@bot.message_handler(commands=["heavy"])
def heavy_cmd(message):
    bot.reply_to(message, run_heavy_engine(mode="standard"))


@bot.message_handler(commands=["heavy_risk"])
def heavy_risk_cmd(message):
    bot.reply_to(message, run_heavy_engine(mode="risk"))


@bot.message_handler(commands=["heavy_edge"])
def heavy_edge_cmd(message):
    bot.reply_to(message, run_heavy_engine(mode="edge"))


@bot.message_handler(commands=["heavy_auto"])
def heavy_auto_cmd(message):
    bot.reply_to(message, run_heavy_engine(mode="auto"))


@bot.message_handler(commands=["heavy_full"])
def heavy_full_cmd(message):
    bot.reply_to(message, run_heavy_engine(mode="full"))


# ----- FAZ-6: TELEGRAM SARICI + KUPON -----

def _run_faz6_and_reply(message, mode: str):
    result = safe_run_faz6_engine(mode=mode)

    # FAZ-7.9 hafıza için günlük conf/edge kaydı
    if result.get("status") == "ok":
        body = result.get("result", {})
        preds = body.get("portfolio") or body.get("predictions") or []
        if preds:
            avg_conf = sum(float(p.get("confidence", 0.0)) for p in preds) / len(preds)
            avg_edge = sum(float(p.get("edge", 0.0)) for p in preds) / len(preds)
            register_daily_stats(avg_conf, avg_edge)

    msg = format_faz6_message(result)
    bot.reply_to(message, msg, parse_mode="Markdown")


@bot.message_handler(commands=["faz6_test"])
def faz6_test_cmd(message):
    _run_faz6_and_reply(message, "test")


@bot.message_handler(commands=["faz6_auto"])
def faz6_auto_cmd(message):
    _run_faz6_and_reply(message, "auto")


@bot.message_handler(commands=["faz6_risk"])
def faz6_risk_cmd(message):
    _run_faz6_and_reply(message, "risk")


@bot.message_handler(commands=["faz6_edge"])
def faz6_edge_cmd(message):
    _run_faz6_and_reply(message, "edge")


@bot.message_handler(commands=["faz6_real"])
def faz6_real_cmd(message):
    _run_faz6_and_reply(message, "real")


@bot.message_handler(commands=["faz6_balance"])
def faz6_balance_cmd(message):
    _run_faz6_and_reply(message, "balance")


@bot.message_handler(commands=["faz6_coupon"])
def faz6_coupon_cmd(message):
    # Varsayılan: balance modu üzerinden kupon
    engine_result = safe_run_faz6_engine("balance")
    text = faz6_build_coupon_message(engine_result, max_coupons=3)
    bot.reply_to(message, text, parse_mode="Markdown")


# ----- FAZ-7.9 KOMUTLARI -----

@bot.message_handler(commands=["faz7_status"])
def faz7_status(message):
    mem = load_memory()

    if not mem.get("days"):
        msg = "📊 FAZ-7.9 Hafıza: Henüz veri yok."
    else:
        df = pd.DataFrame(mem["days"])
        msg = (
            "🧠 *FAZ-7.9 HAFIZA ÖZETİ*\n\n"
            f"SAFE: {mem.get('safe', 0)}\n"
            f"BAL : {mem.get('bal', 0)}\n"
            f"AGG : {mem.get('agg', 0)}\n\n"
            f"7 Günlük Ortalama Confidence: {df['conf'].mean():.3f}\n"
            f"7 Günlük Ortalama Edge: {df['edge'].mean():.3f}"
        )

    bot.reply_to(message, msg, parse_mode="Markdown")


@bot.message_handler(commands=["faz7_plan"])
def faz7_plan(message):
    info = faz79_brain()

    msg = (
        "🧠 *FAZ-7.9 STRATEJİ BEYNİ*\n\n"
        f"Mod: {info['mode']}\n"
        f"🔍 Günlük: conf={info['conf']} edge={info['edge']}\n"
        f"📅 Trend: {info['trend']} (slope {info['slope']})\n"
        f"🌪 Volatilite: {info['vol']}\n"
        f"🔧 Stake Normalize: {info['stake_norm']}\n\n"
        f"SAFE: {'✅' if info['safe'] else '❌'}\n"
        f"BAL: {'✅' if info['bal'] else '❌'}\n"
        f"AGG: {'✅' if info['agg'] else '❌'}\n"
    )

    bot.reply_to(message, msg, parse_mode="Markdown")


# ============================================================
#                      ÇALIŞTIRMA NOKTASI
# ============================================================

def main():
    init_memory()

    if TELEGRAM_MODE == "webhook" and WEBHOOK_URL:
        print(f"INFO: Webhook modu. URL = {WEBHOOK_URL}")
        bot.remove_webhook()
        time.sleep(1)
        bot.set_webhook(WEBHOOK_URL)
        print("INFO: Flask server 0.0.0.0:8080 üzerinde başlıyor (webhook + health).")
        app.run(host="0.0.0.0", port=8080)
    else:
        print("WARN: WEBHOOK_URL bulunamadı veya TELEGRAM_MODE != 'webhook'. Polling moduna geçiliyor.")
        # health için Flask'i arka planda aç
        t = Thread(target=lambda: app.run(host="0.0.0.0", port=8080), daemon=True)
        t.start()
        print("INFO: Telegram bot polling başlıyor...")
        bot.infinity_polling(skip_pending=True, timeout=60, long_polling_timeout=60)


if __name__ == "__main__":
    main()

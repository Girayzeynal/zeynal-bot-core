import sys
import os
import time
from typing import List
from threading import Thread
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests
from telebot import TeleBot

# ============================================================
#                     BOT AYARLARI
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    print("ERROR: BOT_TOKEN ortam değişkeni tanımlı değil.")
    sys.exit(1)

bot = TeleBot(BOT_TOKEN)

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
    pace_est = round(((hs.pace_est or 0) + (aw.pace_est or 0)) / 2, 1)

    diff = hs.pts - aw.pts
    pick = game.home_team if diff > 0 else (game.away_team if diff < 0 else "DENGELİ")

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
#             FAZ-6 TELEGRAM ÇIKTI FORMATLAYICI
# ============================================================

def format_faz6_message(result: dict) -> str:
    if not isinstance(result, dict):
        return f"❌ *FAZ-6 HATA*\nGeçersiz sonuç tipi: {type(result).__name__}"

    if result.get("status") != "ok":
        return f"❌ *FAZ-6 HATA*\n{result.get('detail','Detay yok')}"

    mode = result.get("mode", "").upper()
    data = result.get("result", {})
    preds = data.get("predictions") or []

    text = f"🧠 *FAZ-6 {mode} SONUCU*\n\n"
    for p in preds:
        text += (
            f"📌 {p.get('id')}\n"
            f"🎯 {p.get('pick')} ({p.get('market')})\n"
            f"📈 Güven: {p.get('confidence')} | Edge: {p.get('edge')}\n"
            f"💰 Stake: {p.get('recommended_stake')}\n"
            f"— — —\n"
        )

    return text[:3800]


# ============================================================
#              FAZ-6 KUPON MOTORU
# ============================================================

def build_coupon_message(result: dict, max_coupons: int = 3) -> str:
    if result.get("status") != "ok":
        return f"❌ Kupon üretilemedi:\n{result.get('detail','-')}"

    preds = (
        result.get("result", {}).get("portfolio")
        or result.get("result", {}).get("predictions")
        or []
    )

    if not preds:
        return "❌ Kupon üretilemedi: uygun tahmin yok."

    per_coupon = max(1, len(preds) // max_coupons or 1)
    coupons = []
    for i in range(0, len(preds), per_coupon):
        coupons.append(preds[i:i + per_coupon])
        if len(coupons) >= max_coupons:
            break

    text = "💵 *FAZ-6 Kupon Önerileri*\n\n"
    for idx, cp in enumerate(coupons, start=1):
        text += f"🎟 Kupon {idx}\n"
        for p in cp:
            text += (
                f"• {p['id']} → {p['pick']} ({p['market']})\n"
                f"  Güven: {p['confidence']} | Edge: {p['edge']}\n"
            )
        text += "— — —\n"

    return text


# ============================================================
#                       FAZ-5 ENGINE
# ============================================================

from faz5_engine.heavy_engine_main import run_heavy_engine


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


# ============================================================
#                 FAZ-6 ENGINE WRAPPER
# ============================================================

from faz6_engine import run_faz6_engine as _raw_run_faz6_engine


def safe_run_faz6_engine(mode: str) -> dict:
    try:
        result = _raw_run_faz6_engine(mode=mode)
        if not isinstance(result, dict):
            return {
                "status": "error",
                "detail": "Motor geçersiz tip döndürdü.",
                "raw": result,
            }

        if "status" not in result:
            result = {"status": "ok", **result}

        return result

    except Exception as e:
        return {
            "status": "error",
            "detail": f"FAZ-6 exception: {repr(e)}",
        }


def _run_faz6_and_reply(message, mode: str):
    msg = format_faz6_message(safe_run_faz6_engine(mode))
    bot.reply_to(message, msg, parse_mode="Markdown")


@bot.message_handler(commands=["faz6_test"])
def faz6_test_cmd(message): _run_faz6_and_reply(message, "test")


@bot.message_handler(commands=["faz6_auto"])
def faz6_auto_cmd(message): _run_faz6_and_reply(message, "auto")


@bot.message_handler(commands=["faz6_risk"])
def faz6_risk_cmd(message): _run_faz6_and_reply(message, "risk")


@bot.message_handler(commands=["faz6_edge"])
def faz6_edge_cmd(message): _run_faz6_and_reply(message, "edge")


@bot.message_handler(commands=["faz6_real"])
def faz6_real_cmd(message): _run_faz6_and_reply(message, "real")


@bot.message_handler(commands=["faz6_balance"])
def faz6_balance_cmd(message): _run_faz6_and_reply(message, "balance")


@bot.message_handler(commands=["faz6_coupon"])
def faz6_coupon_cmd(message):
    msg = build_coupon_message(safe_run_faz6_engine("balance"), max_coupons=3)
    bot.reply_to(message, msg, parse_mode="Markdown")


# ============================================================
#                       FAZ-7 STRATEJİ
# ============================================================

def faz7_strategy(engine_result: dict,
                  bankroll: float = 100.0,
                  mood: str = "normal") -> dict:

    preds = (engine_result.get("result", {}).get("portfolio") or [])
    if not preds:
        return {
            "status": "error",
            "detail": "FAZ-6 geçersiz çıktı."
        }

    avg_conf = sum(p.get("confidence", 0) for p in preds) / len(preds)
    avg_edge = sum(p.get("edge", 0) for p in preds) / len(preds)

    if mood == "tilt_risk":
        daily_limit = bankroll * 0.02
    elif mood == "hot_streak":
        daily_limit = bankroll * 0.06
    else:
        daily_limit = bankroll * 0.04

    total_raw = sum(p.get("recommended_stake", 1.0) for p in preds)
    scale_factor = min(1.0, daily_limit / max(total_raw, 1.0))

    for p in preds:
        raw = float(p.get("recommended_stake", 1.0))
        p["normalized_stake"] = round(raw * scale_factor, 2)

    return {
        "status": "ok",
        "avg_conf": round(avg_conf, 3),
        "avg_edge": round(avg_edge, 3),
        "daily_limit": round(daily_limit, 2),
        "scale_factor": round(scale_factor, 3),
        "play": {
            "safe": True,
            "balanced": avg_edge >= 0.028,
            "aggressive": avg_edge >= 0.035 and mood != "tilt_risk",
            "ultra": avg_edge >= 0.040 and mood == "hot_streak",
        },
        "predictions": preds,
    }


@bot.message_handler(commands=["faz7_plan"])
def faz7_plan_cmd(message):
    f6 = safe_run_faz6_engine("balance")
    f7 = faz7_strategy(f6, bankroll=100.0, mood="normal")

    if f7["status"] != "ok":
        bot.reply_to(message, "FAZ-7 strateji hatası.")
        return

    txt = (
        "🧠 *FAZ-7 Günlük Strateji*\n\n"
        f"📈 Ortalama Güven: {f7['avg_conf']}\n"
        f"📊 Ortalama Edge: {f7['avg_edge']}\n"
        f"💰 Günlük Limit: {f7['daily_limit']}\n"
        f"🔧 Stake Normalize: {f7['scale_factor']}x\n\n"
        f"🎛 Oynanacak Seviye:\n"
        f"• SAFE: {f7['play']['safe']}\n"
        f"• BALANCED: {f7['play']['balanced']}\n"
        f"• AGGRESSIVE: {f7['play']['aggressive']}\n"
        f"• ULTRA: {f7['play']['ultra']}\n"
    )

    bot.reply_to(message, txt, parse_mode="Markdown")


# ============================================================
#                FLY.IO HEALTHCHECK SERVER
# ============================================================

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")


def start_health_server():
    server = HTTPServer(("0.0.0.0", 8080), HealthHandler)
    print("INFO: Health server 8080 çalışıyor.")
    server.serve_forever()


# ============================================================
#                    HEARTBEAT (ANTI-IDLE)
# ============================================================

def heartbeat():
    while True:
        try:
            requests.get("http://127.0.0.1:8080", timeout=3)
        except Exception:
            pass
        time.sleep(20)


# ============================================================
#                    BOT POLLING LOOP
# ============================================================

def start_bot():
    while True:
        try:
            print("INFO: Polling başlıyor...")
            bot.infinity_polling(
                skip_pending=True,
                timeout=60,
                long_polling_timeout=60,
            )
        except Exception as e:
            print(f"ERROR: Polling hata: {e!r}")
            time.sleep(3)


# ============================================================
#                      ÇALIŞTIRMA NOKTASI
# ============================================================

def main():
    print("INFO: Bot başlatıldı. FAZ-4/5/6/7 aktif.")

    Thread(target=start_health_server, daemon=True).start()
    Thread(target=heartbeat, daemon=True).start()

    start_bot()


if __name__ == "__main__":
    main()

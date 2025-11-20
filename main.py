import sys
import os
import time
import json
import datetime
from typing import List, Dict, Any, Optional
from threading import Thread
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests
from telebot import TeleBot

# ============================================================
#                    TELEGRAM BOT TOKEN
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    print("ERROR: BOT_TOKEN ortam değişkeni tanımlı değil.")
    sys.exit(1)

bot = TeleBot(BOT_TOKEN)

# ============================================================
#                    NBA FAZ-4 MOTORU
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
    pick = game.home_team if diff > 0 else game.away_team if diff < 0 else "DENGELİ"

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
#                    FAZ-6 ENGINE (TEK DOSYA)
# ============================================================

from faz6_engine import run_faz6_engine, build_coupon_message


def format_faz6_message(result: dict) -> str:
    if not isinstance(result, dict):
        return f"❌ *FAZ-6 HATA*\nGeçersiz sonuç tipi: {type(result).__name__}"

    if result.get("status") != "ok":
        detail = result.get("detail", "Detay yok.")
        return f"❌ *FAZ-6 HATA*\n{detail}"

    mode = result.get("mode", "").upper()
    output = result.get("result", {})
    preds = output.get("portfolio", [])

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
        text = text[:3800] + "\n… (kısaltıldı)"

    return text


def safe_run_faz6_engine(mode: str) -> dict:
    try:
        res = run_faz6_engine(mode=mode)
        if "status" not in res:
            res = {"status": "ok", **res}
        return res
    except Exception as e:
        return {"status": "error", "detail": repr(e)}


# ============================================================
#                      FAZ-7.9 MEMORY ENGINE
# ============================================================

MEMORY_FILE = "faz7_memory.json"


def load_memory() -> List[Dict[str, Any]]:
    try:
        with open(MEMORY_FILE, "r") as f:
            return json.load(f)
    except:
        return []


def save_memory(mem):
    with open(MEMORY_FILE, "w") as f:
        json.dump(mem, f, indent=4)


def register_today(conf: float, edge: float, mode: str, match_count: int):
    mem = load_memory()
    today = datetime.date.today().isoformat()

    mem = [x for x in mem if x["date"] != today]
    mem.append({
        "date": today,
        "conf": conf,
        "edge": edge,
        "mode": mode,
        "match_count": match_count
    })

    save_memory(mem)


def calc_7d_stats(mem):
    last = mem[-7:]
    if not last:
        return (0, 0)
    avg_conf = sum(x["conf"] for x in last) / len(last)
    avg_edge = sum(x["edge"] for x in last) / len(last)
    return (avg_conf, avg_edge)


def calc_trend(mem):
    last = mem[-3:]
    if len(last) < 3:
        return ("INIT", 0.0)

    slope = last[-1]["conf"] - last[0]["conf"]

    if slope > 0.015:
        return ("UP", slope)
    if slope < -0.015:
        return ("DOWN", slope)
    return ("FLAT", slope)


def volatility(mem):
    last = mem[-7:]
    if len(last) < 3:
        return 0.0
    confs = [x["conf"] for x in last]
    avg = sum(confs) / len(confs)
    var = sum((x - avg) ** 2 for x in confs) / len(confs)
    return var ** 0.5


def select_faz7_mode(trend, vol):
    if trend == "UP" and vol < 0.005:
        return "AGG"
    if trend == "UP":
        return "BAL"
    if trend == "DOWN":
        return "SAFE"
    return "BAL"


def stake_multiplier(mode):
    if mode == "SAFE":
        return 0.90
    if mode == "BAL":
        return 1.00
    if mode == "AGG":
        return 1.10
    return 1.00


# ============================================================
#                TELEGRAM COMMANDS — FAZ-7.9
# ============================================================

@bot.message_handler(commands=["faz7_plan"])
def faz7_plan_cmd(message):
    mem = load_memory()

    today_conf = 0.621
    today_edge = 0.034
    today_mode = "BAL"
    matches = 6

    register_today(today_conf, today_edge, today_mode, matches)

    avg_conf, avg_edge = calc_7d_stats(mem)
    trend, slope = calc_trend(mem)
    vol = volatility(mem)

    mode = select_faz7_mode(trend, vol)
    stake_x = stake_multiplier(mode)

    txt = f"""
🧠 *FAZ-7.9 STRATEJİ BEYNİ*

🎯 Mod: {mode}
📈 Günlük: conf={today_conf} edge={today_edge}
📅 7 Gün Ort.: conf={avg_conf:.3f} edge={avg_edge:.3f}
📊 Trend: {trend} (slope {slope:.4f})
🌪 Volatilite: {vol:.4f}
🔧 Stake Normalize: {stake_x:.2f}

SAFE: {'✅' if mode=='SAFE' else '❌'}
BAL : {'✅' if mode=='BAL' else '❌'}
AGG : {'✅' if mode=='AGG' else '❌'}
"""
    bot.reply_to(message, txt, parse_mode="Markdown")


@bot.message_handler(commands=["faz7_status"])
def faz7_status_cmd(message):
    mem = load_memory()

    safe = sum(1 for x in mem if x["mode"] == "SAFE")
    bal = sum(1 for x in mem if x["mode"] == "BAL")
    agg = sum(1 for x in mem if x["mode"] == "AGG")

    avg_conf, avg_edge = calc_7d_stats(mem)

    txt = f"""
🧠 *FAZ-7.9 HAFIZA ÖZETİ*

SAFE: {safe}
BAL : {bal}
AGG : {agg}

7 Günlük Ortalama Confidence: {avg_conf:.3f}
7 Günlük Ortalama Edge: {avg_edge:.3f}
"""
    bot.reply_to(message, txt, parse_mode="Markdown")


# ============================================================
#                 FAZ-3, FAZ-4, FAZ-5 KOMUTLARI
# ============================================================

@bot.message_handler(commands=["start"])
def start_cmd(message):
    bot.reply_to(message, "🔥 Sistem aktif! /help ile tüm komutlar.")


@bot.message_handler(commands=["help"])
def help_cmd(message):
    bot.reply_to(message, """
Komutlar:
/simulate_nba
/heavy
/faz6_auto
/faz6_coupon
/faz7_plan
/faz7_status
""")


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
    server.serve_forever()


def heartbeat():
    while True:
        try:
            requests.get("http://127.0.0.1:8080", timeout=3)
        except:
            pass
        time.sleep(20)


# ============================================================
#                    BOT POLLING LOOP
# ============================================================

def start_bot():
    while True:
        try:
            bot.infinity_polling(skip_pending=True, timeout=60, long_polling_timeout=60)
        except Exception as e:
            print(f"POLLING ERROR: {e!r}")
            time.sleep(3)


# ============================================================
#                     ÇALIŞTIRMA NOKTASI
# ============================================================

def main():
    health_thread = Thread(target=start_health_server, daemon=True)
    health_thread.start()

    heartbeat_thread = Thread(target=heartbeat, daemon=True)
    heartbeat_thread.start()

    start_bot()


if __name__ == "__main__":
    main()

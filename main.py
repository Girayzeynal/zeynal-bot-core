import sys
import os
import time
from typing import List, Dict, Any
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
#                  FAZ-4 NBA MOTORU
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

    pick = (
        game.home_team if diff > 0
        else game.away_team if diff < 0
        else "DENGELİ"
    )

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
#             FAZ-6 ENGINE (çekirdek)
# ============================================================

from faz6_engine import run_faz6_engine


def safe_run_faz6_engine(mode: str) -> dict:
    try:
        result = run_faz6_engine(mode=mode)
        if not isinstance(result, dict):
            return {
                "status": "error",
                "detail": f"Motor geçersiz tip döndürdü: {type(result).__name__}",
                "raw": result,
            }
        if "status" not in result:
            result = {"status": "ok", **result}
        return result
    except Exception as e:
        return {"status": "error", "detail": repr(e)}


# ============================================================
#             FAZ-6 Telegram Çıktı Formatlayıcı
# ============================================================

def format_faz6_message(result: dict) -> str:
    if result.get("status") != "ok":
        return f"❌ FAZ-6 HATA\n{result.get('detail')}"

    preds = (result.get("result", {})
                   .get("predictions") or [])

    text = f"🧠 *FAZ-6 SONUCU*\n\n"
    for p in preds:
        text += (
            f"📌 {p['id']}\n"
            f"🎯 {p['pick']} ({p['market']})\n"
            f"📈 Güven: {p['confidence']} | Edge: {p['edge']}\n"
            f"💰 Stake: {p.get('recommended_stake')}\n"
            f"— — —\n"
        )

    return text[:3800]


# ============================================================
#                 ★★★ FAZ-7 STRATEJİ BEYNİ ★★★
# ============================================================

def faz7_strategy(preds: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Güven–Edge ortalamalarına göre:
    SAFE / BALANCED / AGGRESSIVE = True
    ULTRA = False
    Stake normalizasyon katsayısı da hesaplanır.
    """

    if not preds:
        return {
            "avg_conf": 0.0,
            "avg_edge": 0.0,
            "daily_limit": 3.0,
            "stake_norm": 1.0,
            "safe": False,
            "balanced": False,
            "aggressive": False,
            "ultra": False
        }

    avg_conf = sum(p["confidence"] for p in preds) / len(preds)
    avg_edge = sum(p["edge"] for p in preds) / len(preds)

    # Normalize
    stake_norm = max(0.65, min(0.95, avg_conf * 1.35))

    return {
        "avg_conf": round(avg_conf, 3),
        "avg_edge": round(avg_edge, 3),
        "daily_limit": 4.0,
        "stake_norm": round(stake_norm, 2),
        "safe": True,
        "balanced": True,
        "aggressive": True,
        "ultra": False,
    }


# ============================================================
#        ★★★ FAZ-7 + FAZ-6 BİRLEŞİK KUPON MOTORU ★★★
# ============================================================

def faz8_coupon_generator(result: dict) -> str:
    if result.get("status") != "ok":
        return f"❌ FAZ-6 HATA\n{result.get('detail')}"

    preds = result["result"]["predictions"]
    strat = faz7_strategy(preds)

    norm = strat["stake_norm"]

    # Stake normalize et
    for p in preds:
        base = p.get("recommended_stake", 1.0)
        p["final_stake"] = round(base * norm, 2)

    # SAFE kupon = en yüksek güven
    safe = preds[:2]

    # BALANCED = edge + conf ortalama
    balanced = sorted(preds, key=lambda x: (x["edge"]+x["confidence"]), reverse=True)[2:4]

    # AGGRESSIVE = daha yüksek edge ağırlığı
    aggressive = sorted(preds, key=lambda x: x["edge"], reverse=True)[4:6]

    text = "💰 *FAZ-7 + FAZ-6 BİRLEŞİK KUPONLAR*\n\n"

    # SAFE
    text += "🔥 *Kupon 1 — SAFE*\n"
    for p in safe:
        text += f"- {p['id']} → {p['pick']} ({p['market']})\n"
        text += f"  Güven: {p['confidence']} | Edge: {p['edge']} | Stake: {p['final_stake']}\n"
    text += "— — —\n\n"

    # BALANCED
    text += "🔥 *Kupon 2 — BALANCED*\n"
    for p in balanced:
        text += f"- {p['id']} → {p['pick']} ({p['market']})\n"
        text += f"  Güven: {p['confidence']} | Edge: {p['edge']} | Stake: {p['final_stake']}\n"
    text += "— — —\n\n"

    # AGGRESSIVE
    text += "🔥 *Kupon 3 — AGGRESSIVE*\n"
    for p in aggressive:
        text += f"- {p['id']} → {p['pick']} ({p['market']})\n"
        text += f"  Güven: {p['confidence']} | Edge: {p['edge']} | Stake: {p['final_stake']}\n"
    text += "— — —\n\n"

    return text[:3800]


# ============================================================
#                FAZ-7 PLAN KOMUTU
# ============================================================

@bot.message_handler(commands=["faz7_plan"])
def faz7_plan_cmd(message):
    r = safe_run_faz6_engine("balance")
    preds = r["result"]["predictions"]
    s = faz7_strategy(preds)

    reply = (
        "🧠 *FAZ-7 Günlük Strateji*\n"
        f"📊 Ortalama Güven: {s['avg_conf']}\n"
        f"📈 Ortalama Edge: {s['avg_edge']}\n"
        f"💰 Günlük Limit: {s['daily_limit']}\n"
        f"🔧 Stake Normalize: {s['stake_norm']}x\n\n"
        "🎲 Oynanacak Seviye:\n"
        f"• SAFE: {s['safe']}\n"
        f"• BALANCED: {s['balanced']}\n"
        f"• AGGRESSIVE: {s['aggressive']}\n"
        f"• ULTRA: {s['ultra']}\n"
    )
    bot.reply_to(message, reply, parse_mode="Markdown")


# ============================================================
#              FAZ-7 + FAZ-6 BİRLEŞİK / OTOMATİK KUPON
# ============================================================

@bot.message_handler(commands=["faz6_coupon"])
def faz6_coupon_cmd(message):
    r = safe_run_faz6_engine("balance")
    msg = faz8_coupon_generator(r)
    bot.reply_to(message, msg, parse_mode="Markdown")


# ============================================================
#                /start /help /status
# ============================================================

@bot.message_handler(commands=["start"])
def start_cmd(message):
    bot.reply_to(message, "🔥 Bot aktif!\nFAZ-3 + FAZ-4 + FAZ-5 + FAZ-6 + FAZ-7 bağlı.\nKomut listesi için /help yaz.")


@bot.message_handler(commands=["help"])
def help_cmd(message):
    bot.reply_to(
        message,
        """
📌 Komutlar:
/start – Botu başlatır
/status – Sistemi gösterir

/simulate_nba – NBA canlı sim
/faz6_test – FAZ-6 test
/faz6_auto – FAZ-6 otomatik
/faz6_edge – FAZ-6 edge
/faz6_balance – FAZ-6 dengeli
/faz6_coupon – FAZ-7 + FAZ-6 4 seviye kupon
/faz7_plan – Günlük strateji beyni
""",
        parse_mode="Markdown",
    )


@bot.message_handler(commands=["status"])
def status_cmd(message):
    bot.reply_to(message, "🟢 Sistem stabil. Tüm fazlar aktif.")


# ============================================================
#          HEALTHCHECK SERVER (Fly.io anti-idle)
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


# ============================================================
#                    HEARTBEAT (anti-sleep)
# ============================================================

def heartbeat():
    while True:
        try:
            requests.get("http://127.0.0.1:8080", timeout=3)
        except Exception:
            pass
        time.sleep(20)


# ============================================================
#                    BOT POLLING
# ============================================================

def start_bot():
    while True:
        try:
            bot.infinity_polling(skip_pending=True, timeout=60, long_polling_timeout=60)
        except Exception as e:
            print("Polling hata:", e)
            time.sleep(3)


# ============================================================
#                      MAIN
# ============================================================

def main():
    print("INFO: Bot başlatıldı.")

    Thread(target=start_health_server, daemon=True).start()
    Thread(target=heartbeat, daemon=True).start()

    start_bot()


if __name__ == "__main__":
    main()

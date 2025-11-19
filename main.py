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
#             FAZ-6 TELEGRAM ÇIKTI FORMATLAYICI
# ============================================================

def format_faz6_message(result: dict) -> str:
    """
    run_faz6_engine çıktısını Telegram mesajına çevirir.
    """
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
#         YENİ FAZ-6 4-KUPON HİBRİT KUPON MOTORU (main.py)
# ============================================================

def build_coupon_message(engine_result: Dict[str, Any],
                         max_coupons: int = 4) -> str:
    """
    FAZ-6 motor çıktısından 4 seviyeli kupon seti üretir.

    - 4 kupon: SAFE, BALANCED, AGGRESSIVE, ULTRA
    - Her kupon 3–4 maç arasında (veri yettiği kadar)
    - Dağıtım, confidence+edge skoruna göre round-robin yapılır
    """

    status = engine_result.get("status", "ok")
    if status != "ok":
        detail = engine_result.get("detail", "Bilinmeyen hata")
        return f"❌ *FAZ-6 KUPON HATASI*\n{detail}"

    result = engine_result.get("result", {})
    preds: List[Dict[str, Any]] = (
        result.get("portfolio")
        or result.get("predictions")
        or []
    )

    if not preds:
        return "⚠ Kupon oluşturmak için yeterli maç bulunamadı."

    # Güç sıralaması: önce edge, sonra confidence
    sorted_preds = sorted(
        preds,
        key=lambda p: (float(p.get("edge", 0.0)), float(p.get("confidence", 0.0))),
        reverse=True,
    )

    # Kupon slotları
    coupon_count = min(max_coupons, 4)
    coupons: List[List[Dict[str, Any]]] = [[] for _ in range(coupon_count)]

    MAX_PICKS_PER_COUPON = 4
    # 3–4 arası hedef; veri azsa doğal olarak daha az olabilir.

    pointer = 0
    total_capacity = coupon_count * MAX_PICKS_PER_COUPON
    used = 0

    for p in sorted_preds:
        if used >= total_capacity:
            break

        # Uygun slot bul (round-robin ama dolu olanları geç)
        attempts = 0
        while attempts < coupon_count and len(coupons[pointer]) >= MAX_PICKS_PER_COUPON:
            pointer = (pointer + 1) % coupon_count
            attempts += 1

        if attempts >= coupon_count and all(
            len(c) >= MAX_PICKS_PER_COUPON for c in coupons
        ):
            break

        coupons[pointer].append(p)
        used += 1
        pointer = (pointer + 1) % coupon_count

    labels = ["SAFE", "BALANCED", "AGGRESSIVE", "ULTRA"]
    lines: List[str] = []
    lines.append("🎟 *FAZ-6 KUPONLARI (4-Seviyeli AI Dağılım)*\n")

    for idx, coupon in enumerate(coupons, start=1):
        if not coupon:
            continue

        label = labels[idx - 1] if idx - 1 < len(labels) else "MIXED"
        lines.append(f"🔥 *Kupon {idx} — {label}*")

        total_stake = 0.0
        for p in coupon:
            stake = float(p.get("recommended_stake", 1.0))
            total_stake += stake

            match_id = p.get("id") or p.get("match") or "?"
            pick = p.get("pick") or p.get("selection") or "N/A"
            market = p.get("market", "")
            conf = p.get("confidence", p.get("conf", 0))
            edge = p.get("edge", 0)

            lines.append(
                f"- {match_id} | {pick} ({market})\n"
                f"  Güven: {conf} | Edge: {edge} | Stake: {stake}"
            )

        lines.append(f"💰 Toplam Stake: {round(total_stake, 2)}\n")

    text = "\n".join(lines)
    if len(text) > 3800:
        text = text[:3800] + "\n… (çıktı kısaltıldı)"
    return text


# ============================================================
#                    FAZ-3 TELEGRAM KOMUTLARI
# ============================================================

@bot.message_handler(commands=["start"])
def start_cmd(message):
    bot.reply_to(
        message,
        "🔥 Bot aktif!\nFAZ-3 + FAZ-4 + FAZ-5 + FAZ-6 bağlı.\nKomut listesi için /help yaz."
    )


@bot.message_handler(commands=["help"])
def help_cmd(message):
    bot.reply_to(
        message,
        """
📌 Komutlar:

/start - Botu başlatır
/status - Sistemi gösterir

/simulate_nba - NBA canlı simülasyon

/heavy - FAZ-5 Standart
/heavy_risk - FAZ-5 Risk
/heavy_edge - FAZ-5 Edge
/heavy_auto - FAZ-5 Otomatik
/heavy_full - FAZ-5 Full

/faz6_test - FAZ-6 Test
/faz6_auto - FAZ-6 Auto
/faz6_risk - FAZ-6 Risk
/faz6_edge - FAZ-6 Edge
/faz6_real - FAZ-6 Real
/faz6_balance - FAZ-6 Balance
/faz6_coupon - FAZ-6 Kupon (4 seviye)
"""
    )


@bot.message_handler(commands=["status"])
def status_cmd(message):
    bot.reply_to(
        message,
        "🟢 Sistem stabil.\nFAZ-4 aktif.\nFAZ-5 bağlı.\nFAZ-6 tam online."
    )


# ============================================================
#                       FAZ-4 NBA KOMUTU
# ============================================================

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
#                       FAZ-6 ENGINE WRAPPER
# ============================================================

from faz6_engine import run_faz6_engine as _raw_run_faz6_engine


def safe_run_faz6_engine(mode: str) -> dict:
    try:
        result = _raw_run_faz6_engine(mode=mode)
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


def _run_faz6_and_reply(message, mode: str):
    result = safe_run_faz6_engine(mode=mode)
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


# ============================================================
#                    FAZ-6 KUPON (4 Kupon)
# ============================================================

@bot.message_handler(commands=["faz6_coupon"])
def faz6_coupon_cmd(message):
    # Kuponlar her zaman FAZ-6 "balance" modunun çıktısından
    result = safe_run_faz6_engine(mode="balance")
    msg = build_coupon_message(result, max_coupons=4)
    bot.reply_to(message, msg, parse_mode="Markdown")


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
    print("INFO: Health server 0.0.0.0:8080 üzerinde çalışıyor.")
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
            print("INFO: Telegram bot polling başlıyor...")
            bot.infinity_polling(
                skip_pending=True,
                timeout=60,
                long_polling_timeout=60,
            )
        except Exception as e:
            print(f"ERROR: Polling hata verdi: {e!r}")
            time.sleep(3)


# ============================================================
#                      ÇALIŞTIRMA NOKTASI
# ============================================================

def main():
    print("INFO: Bot başlatıldı. Tüm motorlar aktif.")

    health_thread = Thread(target=start_health_server, daemon=True)
    health_thread.start()

    heartbeat_thread = Thread(target=heartbeat, daemon=True)
    heartbeat_thread.start()

    start_bot()


if __name__ == "__main__":
    main()

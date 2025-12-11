# -*- coding: utf-8 -*-
"""
MAIN (Telegram + Webhook)
- /mac komutu FAZ-13 Full Auto Fetch → faz13_orchestrator.run_faz13_auto_pipeline
- Mevcut Fly.io 256/512MB profiline uygun, basit sync worker.
"""

import os
import logging
from flask import Flask, request
import telebot

from faz13_engine.faz13_orchestrator import run_faz13_auto_pipeline

# =========================
#   CONFIG
# =========================
BOT_TOKEN  = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # örn: https://zeynal-bot-core.fly.dev/webhook

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is required")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("main")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)
app = Flask(__name__)


# =========================
#   HELPERS
# =========================
def parse_mac_text(txt: str):
    """
    /mac NBA | 2025-12-11 | Lakers - Spurs
    """
    raw = txt.strip()
    try:
        body = raw.split(" ", 1)[1].strip()
    except Exception:
        return None, None, None, None

    parts = [p.strip() for p in body.split("|")]
    if len(parts) < 3:
        return None, None, None, None

    league = parts[0]
    date_str = parts[1]
    teams = parts[2]
    if "-" in teams:
        home = teams.split("-")[0].strip()
        away = teams.split("-")[1].strip()
    elif "–" in teams:
        home = teams.split("–")[0].strip()
        away = teams.split("–")[1].strip()
    else:
        return None, None, None, None
    return league, date_str, home, away


def fmt_prediction_text(league, date_str, home, away, res: dict) -> str:
    fam = res["family"]
    total = res["total"]
    lo, hi = res["band"]
    v1, v2, v3 = res["vector"]
    q1, q2, q3, q4 = res["periods"]
    h_pts, a_pts = res["team_scores"]
    meta = res["meta23"]
    an = res["analysis"]
    live = res["live_ctx"]

    lines = []
    lines.append(f"🏀 FAZ-13 Maç Tahmini (Pro) Maç: {home} - {away} Tarih: {date_str} Lig: {league} | Lig Family: {fam}")
    lines.append("—" * 12 + " 🧅 TOPLAM ")
    lines.append(f"TAHMİNİ Fusion Total: {league} | {home} - {away} | TOTAL {total:.1f} band ({lo:.1f}-{hi:.1f}) (NEUTRAL) Bant: {lo:.1f} – {hi:.1f} Score Vector: ({v1:.1f}, {v2:.1f}, {v3:.1f})")

    # Live bilgisi
    if live.get("is_live"):
        lt = live.get("live_total")
        pd = live.get("pace_delta")
        provider = live.get("provider") or "live"
        lines.append(f"⏱️ LIVE MODE: provider={provider} live_total={lt} pace_delta={pd}")

    lines.append("📊 PERİYOT PROJEKSİYONLARI 1Ç: %.1f 2Ç: %.1f 3Ç: %.1f 4Ç: %.1f İY: %.1f | İİY: %.1f | Maç: %.1f" %
                 (q1, q2, q3, q4, q1+q2, q1+q2, total))
    lines.append("🎯 TAKIM SKOR TAHMİNİ Ev Sahibi (%s): %.1f Deplasman (%s): %.1f" % (home, h_pts, away, a_pts))

    lines.append("🧠 HABER / ANALİZ • Lig baseline (iç çekirdek): %.1f • Tempo stili: %s • Volatilite → Pace:%.2f | Def:%.2f • Maç tipi: %s • News Range: %s • Home advantage boost ~ +%.02f (family=%s)" %
                 (an["league_baseline"], "MID", an["volatility"], an["def"], an["match_type"], an["news_range"], an["home_boost"], fam))

    lines.append("——— FAZ-23")
    lines.append("META DEĞERLENDİRME 🧠 FAZ-23 PREMATCH Meta Tahmin 🏆 Lig: %s 🏀 Maç: %s - %s 📊 Toplam Sayı Barem Analizi • Ana total çizgisi: %.1f • Model over ölçüsü : %.3f • Model under ölçüsü : %.3f 📑 Özet: flags=%s" %
                 (league, home, away, meta["primary_total"], meta["model_over"], meta["model_under"], ",".join(meta["flags"])))
    return "\n".join(lines)


# =========================
#   TELEGRAM HANDLERS
# =========================
@bot.message_handler(commands=["mac"])
def cmd_mac(m):
    parsed = parse_mac_text(m.text or "")
    if not all(parsed):
        bot.reply_to(m, "Format: /mac LIG | YYYY-MM-DD | Ev - Deplasman")
        return
    league, date_str, home, away = parsed

    try:
        result = run_faz13_auto_pipeline(
            league=league, date_str=date_str, home=home, away=away,
            prematch_total_hint=None, recent_points_avg=None
        )
        text = fmt_prediction_text(league, date_str, home, away, result)
        bot.reply_to(m, text)
    except Exception as e:  # noqa: BLE001
        log.exception("cmd_mac error")
        bot.reply_to(m, f"Hata: {e}")


@bot.message_handler(commands=["start", "help"])
def cmd_help(m):
    bot.reply_to(m, "Komut: /mac LIG | YYYY-MM-DD | Ev - Deplasman\nÖrnek: /mac NBA | 2025-12-12 | Lakers - Spurs")


# =========================
#   WEBHOOK
# =========================
@app.route("/webhook", methods=["POST"])
def webhook():
    if request.headers.get("content-type") == "application/json":
        update = request.get_data().decode("utf-8")
        bot.process_new_updates([telebot.types.Update.de_json(update)])
        return ""
    return "bad request", 400


@app.route("/")
def index():
    return "OK", 200


def _ensure_webhook():
    if WEBHOOK_URL:
        try:
            bot.remove_webhook()
        except Exception:
            pass
        bot.set_webhook(url=WEBHOOK_URL + "/webhook", max_connections=40, allowed_updates=["message"])
        log.info("Webhook set to %s/webhook", WEBHOOK_URL)
    else:
        log.warning("WEBHOOK_URL is empty; polling fallback")
        bot.remove_webhook()
        bot.infinity_polling(skip_pending=True, interval=0, timeout=20)


if __name__ == "__main__":
    # Fly.io süreçleri gunicorn ile çalıştırır; lokalde test için:
    _ensure_webhook()
    app.run(host="0.0.0.0", port=8080)

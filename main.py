# ================================================================
# MAIN ENTRY – ELITE CORE LOCKED PIPELINE (FINAL REBUILD v1)
# ================================================================
import os
import json
import logging
from flask import Flask, request
import telebot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
log = logging.getLogger("MAIN")

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
app = Flask(__name__)

from core.elite_league_registry import normalize_league_input

# ✅ FAZ-17 dışarıya sadece surface fonksiyonlarını açar
from faz17_engine import faz17_fetch_market, faz17_fetch_market_safe

# ✅ FAZ-13 yalnızca core tahmin üretir
from faz13_engine.faz13_orchestrator import run_faz13_auto_pipeline


def parse_mac_command(text: str):
    """Expected: /mac LEAGUE | YYYY-MM-DD | HOME - AWAY"""
    try:
        raw = text.replace("/mac", "").strip()
        parts = [p.strip() for p in raw.split("|")]
        if len(parts) != 3:
            return None
        league_raw = parts[0]
        date_str = parts[1]
        teams = parts[2].split("-")
        if len(teams) != 2:
            return None
        home = teams[0].strip()
        away = teams[1].strip()
        league = normalize_league_input(league_raw)
        return {"league": league, "date": date_str, "home": home, "away": away}
    except Exception:
        return None


@bot.message_handler(commands=["mac"])
def handle_mac(message):
    parsed = parse_mac_command(message.text or "")
    if not parsed:
        bot.reply_to(message, "❌ Format hatalı.\n/mac LIG | YYYY-MM-DD | EV - DEP")
        return

    league = parsed["league"]
    date_str = parsed["date"]
    home = parsed["home"]
    away = parsed["away"]

    log.info(f"MAC REQUEST | {league} | {date_str} | {home} vs {away}")

    # ------------------------------------------------------------
    # FAZ-17 MARKET (ONLY DATA) — SAFE WRAPPER
    # ------------------------------------------------------------
    market_data, market_meta = faz17_fetch_market_safe(
        provider_fetch_func=faz17_fetch_market,
        league=league,
        date_str=date_str,
        home=home,
        away=away,
    )

    # ------------------------------------------------------------
    # FAZ-13 CORE (ONLY PRED) — consumes market as signal
    # ------------------------------------------------------------
    result = run_faz13_auto_pipeline(
        league=league,
        home=home,
        away=away,
        date_str=date_str,
        market_data=market_data,
        market_meta=market_meta,
    )

    # Minimal, stabil cevap (uzun formatı sonra FAZ-13 GOD layer’a bağlarız)
    reply = (
        f"🏀 {home} - {away}\n"
        f"📅 {date_str}\n"
        f"🏷️ Lig: {league}\n\n"
        f"🎯 FAZ-13 Base: {result.get('base_pred')}\n"
        f"📌 Band: {result.get('band')}\n"
        f"🧩 Enrichment: {', '.join(result.get('enrichment') or []) or 'Yok'}\n\n"
        f"📈 Market:\n"
        f" • Used: {result['market']['used']}\n"
        f" • Conf: {result['market']['confidence']}\n"
        f" • Line: {result['market'].get('totals_line')}\n"
        f" • Reason: {result['market']['reason']}\n"
    )

    bot.reply_to(message, reply)


@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    # ✅ Stabil parse: string -> dict -> Update
    raw = request.get_data(as_text=True) or ""
    try:
        payload = json.loads(raw) if raw else {}
    except Exception:
        payload = {}
    update = telebot.types.Update.de_json(payload)
    bot.process_new_updates([update])
    return "OK", 200


@app.route("/")
def health():
    return "OK", 200


if __name__ == "__main__":
    if WEBHOOK_URL:
        bot.remove_webhook()
        bot.set_webhook(url=f"{WEBHOOK_URL}/{BOT_TOKEN}")
        log.info("Webhook set")
    else:
        log.info("Running in polling mode")
    bot.infinity_polling()

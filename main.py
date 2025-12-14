# ================================================================
# 🧠 MAIN ENTRY – ELITE CORE LOCKED PIPELINE
# ================================================================

import os
import logging
from flask import Flask, request

import telebot

# ================================================================
# 🔧 LOGGING
# ================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
log = logging.getLogger("MAIN")

# ================================================================
# 🔑 ENV
# ================================================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")

# ================================================================
# 🤖 BOT + APP
# ================================================================
bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
app = Flask(__name__)

# ================================================================
# 🧠 ELITE CORE IMPORTS
# ================================================================
from core.elite_league_registry import (
    normalize_league_input,
)

# ================================================================
# 🔥 FAZ IMPORTS
# ================================================================
from faz17_engine.faz17_market_fetcher import (
    faz17_fetch_market_safe
)

from faz13_engine.faz13_orchestrator import (
    run_faz13_auto_pipeline
)

# ================================================================
# 🧩 OPTIONAL: REAL PROVIDER FETCH
# (senin mevcut provider fonksiyonun burada olmalı)
# ================================================================
try:
    from faz17_engine.providers import faz17_fetch_market
except Exception:
    faz17_fetch_market = None
    log.warning("faz17_fetch_market provider not found")

# ================================================================
# 🧭 COMMAND PARSER
# ================================================================
def parse_mac_command(text: str):
    """
    Expected:
    /mac LEAGUE | YYYY-MM-DD | HOME - AWAY
    """
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

        return {
            "league": league,
            "date": date_str,
            "home": home,
            "away": away,
        }
    except Exception:
        return None

# ================================================================
# 🎯 /mac HANDLER
# ================================================================
@bot.message_handler(commands=["mac"])
def handle_mac(message):
    parsed = parse_mac_command(message.text)
    if not parsed:
        bot.reply_to(
            message,
            "❌ Format hatalı.\n"
            "/mac LIG | YYYY-MM-DD | EV - DEP"
        )
        return

    league = parsed["league"]
    date_str = parsed["date"]
    home = parsed["home"]
    away = parsed["away"]

    log.info(f"MAC REQUEST | {league} | {date_str} | {home} vs {away}")

    # ------------------------------------------------------------
    # FAZ-17 MARKET (SAFE)
    # ------------------------------------------------------------
    market_data = None
    market_meta = None

    if faz17_fetch_market:
        market_data, market_meta = faz17_fetch_market_safe(
            provider_fetch_func=faz17_fetch_market,
            league=league,
            date_str=date_str,
            home=home,
            away=away,
        )

        if market_meta and not market_meta.get("market", {}).get("used"):
            log.warning(
                f"MARKET REJECTED | {market_meta.get('market', {}).get('reason')}"
            )

    # ------------------------------------------------------------
    # FAZ-13 PIPELINE
    # ------------------------------------------------------------
    result = run_faz13_auto_pipeline(
        league=league,
        home=home,
        away=away,
        date_str=date_str,
        market_data=market_data,
        market_meta=market_meta,
    )

    # ------------------------------------------------------------
    # 📤 RESPONSE FORMAT (CLEAN)
    # ------------------------------------------------------------
    reply = (
        f"🏀 {home} - {away}\n"
        f"📅 {date_str}\n"
        f"🏷️ Lig: {league}\n\n"
        f"📊 Market:\n"
        f"  • Kullanıldı: {result['market']['used']}\n"
        f"  • Güven: {result['market']['confidence']}\n"
        f"  • Sebep: {result['market']['reason']}\n\n"
        f"🧠 Enrichment: {', '.join(result['enrichment']) if result['enrichment'] else 'Yok'}\n"
        f"⚙️ Ağırlıklar: {result['weights']}\n"
    )

    bot.reply_to(message, reply)

# ================================================================
# 🌐 WEBHOOK
# ================================================================
@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    update = telebot.types.Update.de_json(
        request.stream.read().decode("utf-8")
    )
    bot.process_new_updates([update])
    return "OK", 200

@app.route("/")
def health():
    return "OK", 200

# ================================================================
# 🚀 STARTUP
# ================================================================
if __name__ == "__main__":
    if WEBHOOK_URL:
        bot.remove_webhook()
        bot.set_webhook(url=f"{WEBHOOK_URL}/{BOT_TOKEN}")
        log.info("Webhook set")
    else:
        log.info("Running in polling mode")
        bot.infinity_polling()

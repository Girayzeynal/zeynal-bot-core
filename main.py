from __future__ import annotations
import os
import logging
from flask import Flask, request
import telebot
from telebot import types

from faz17_engine.faz17_market_fetcher import fetch_market
from faz13_engine.faz13_orchestrator import run_faz13_auto_pipeline
from faz22_engine.faz22_meta import faz22_meta_engine

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()
PORT = int(os.getenv("PORT", "8080"))

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ZeynalBot")

app = Flask(__name__)
bot = telebot.TeleBot(BOT_TOKEN, threaded=True)


@app.route("/", methods=["GET"])
def health():
    return "OK", 200


@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def telegram_webhook():
    update = types.Update.de_json(request.get_json(force=True))
    bot.process_new_updates([update])
    return "OK", 200


@bot.message_handler(commands=["mac"])
def cmd_mac(message: types.Message):
    try:
        raw = message.text.replace("/mac", "", 1).strip()
        league, date_str, matchup = [p.strip() for p in raw.split("|")]
        home, away = [x.strip() for x in matchup.split("-")]

        market_data, market_meta = fetch_market(league, date_str, home, away)

        faz13 = run_faz13_auto_pipeline(
            league=league,
            home=home,
            away=away,
            date_str=date_str,
            market_data=market_data,
        )

        faz22 = faz22_meta_engine({
            "league": league,
            "base_pred": faz13["base_pred"],
            "band": faz13["band"],
            "confidence": faz13["confidence"],
            "market": faz13["market"],
        })

        reply = (
            f"🏀 {home} — {away}\n"
            f"{league} | {date_str}\n\n"
            f"🧠 Base: {faz22['base_pred']}\n"
            f"📦 Band: {faz22['band']}\n"
            f"✅ Confidence: {faz22['confidence']}\n"
            f"⚠️ Risk: {faz22['risk']}\n"
            f"📈 Market: {faz22['market']}"
        )

        bot.reply_to(message, reply)

    except Exception as e:
        log.exception("Pipeline crashed")
        bot.reply_to(message, f"❌ Pipeline crashed: {e}")


if __name__ == "__main__":
    if WEBHOOK_URL:
        bot.set_webhook(WEBHOOK_URL)
    app.run(host="0.0.0.0", port=PORT) 

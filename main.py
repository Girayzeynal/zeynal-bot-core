import os
import json
import logging
from flask import Flask, request
import telebot

from core.elite_league_registry import normalize_league_input
from faz13_engine.faz13_orchestrator import run_faz13_auto_pipeline
from faz17_engine.faz17_market import fetch_market

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
log = logging.getLogger("MAIN")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()
PORT = int(os.getenv("PORT", "8080"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
app = Flask(__name__)

def parse_mac_command(text: str):
    try:
        raw = text.replace("/mac", "").strip()
        parts = [p.strip() for p in raw.split("|")]
        if len(parts) != 3:
            return None
        league = normalize_league_input(parts[0])  # sen lig verdin, sadece normalize
        date_str = parts[1]
        teams = parts[2].split("-")
        if len(teams) != 2:
            return None
        home = teams[0].strip()
        away = teams[1].strip()
        return {"league": league, "date": date_str, "home": home, "away": away}
    except Exception:
        return None

@bot.message_handler(commands=["status"])
def handle_status(message):
    odds_ok = bool(os.getenv("ODDS_API_KEY","").strip()) and bool(os.getenv("ODDS_API_URL","").strip())
    sport_ok = bool(os.getenv("API_SPORT_KEY","").strip()) and bool(os.getenv("API_SPORT_URL","").strip())
    reply = (
        "🧠 Zeynal Core AI /status\n"
        f"✅ Mode: {'WEBHOOK' if WEBHOOK_URL else 'POLLING'}\n"
        f"✅ PORT: {PORT}\n"
        f"📈 ODDS: {'OK' if odds_ok else 'MISSING'}\n"
        f"📰 API-SPORTS: {'OK' if sport_ok else 'MISSING'}\n"
    )
    bot.reply_to(message, reply)

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

    # MARKET (ZORUNLU)
    market_data, market_meta = fetch_market(league, date_str, home, away)

    # NEWS/INJURY placeholder (None yok)
    # Burayı bir sonraki adımda API-Sports injuries endpoint’i ile dolduracağız.
    context = {
        "team_stats": {},        # bir sonraki adım: last 5 games avg
        "injuries": {"count": 0, "items": []},
        "news": {"count": 0, "items": []},
    }

    faz13 = run_faz13_auto_pipeline(
        league=league,
        home=home,
        away=away,
        date_str=date_str,
        market_data=market_data,
        market_meta=market_meta,
        extra_inputs=context,
    )

    # Reply (CORE MODE)
    periods = faz13.get("periods", {})
    band = faz13.get("band")
    risk = faz13.get("risk")
    conf = faz13.get("confidence")
    base = faz13.get("base_pred")
    market_line = faz13.get("market", {}).get("line")
    market_delta = faz13.get("market", {}).get("delta")
    ou_dir = faz13.get("ou", {}).get("dir")

    reply = (
        f"🏀 {home} - {away}\n"
        f"🏷️ {league} | 📅 {date_str}\n\n"
        f"🧠 Base: {base}\n"
        f"🎯 Band: {band}\n"
        f"✅ Confidence: {conf}\n"
        f"🏷️ Risk: {risk}\n\n"
        f"📈 Market Line: {market_line}\n"
        f"📉 Market Δ: {market_delta}\n"
        f"🔼/🔽 O/U Dir: {ou_dir}\n\n"
        f"📊 Periyot Tahminleri:\n"
        f" • 1Q: {periods.get('q1')}\n"
        f" • 2Q: {periods.get('q2')} (İY: {periods.get('h1')})\n"
        f" • 3Q: {periods.get('q3')}\n"
        f" • 4Q: {periods.get('q4')} (2Y: {periods.get('h2')})\n"
    )
    bot.reply_to(message, reply)

@app.route("/webhook", methods=["POST"])
@app.route("/webhook/<path:extra>", methods=["POST"])
def webhook(extra=None):
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
        log.info("Starting in WEBHOOK mode")
        bot.remove_webhook()
        bot.set_webhook(url=WEBHOOK_URL)
        app.run(host="0.0.0.0", port=PORT)
    else:
        log.info("Starting in POLLING mode (no webhook)")
        bot.infinity_polling() 

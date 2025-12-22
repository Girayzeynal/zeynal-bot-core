import os
import json
import logging
from flask import Flask, request
import telebot

from core.elite_league_registry import normalize_league_input
from faz17_engine import faz17_fetch_market, faz17_fetch_market_safe
from faz13_engine import run_faz13_auto_pipeline
from faz22_engine import faz22_meta_engine
from faz23_engine import faz23_memory_write, faz23_apply_result

# -------------------------------------------------
# LOGGING
# -------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
log = logging.getLogger("MAIN")

# -------------------------------------------------
# ENV
# -------------------------------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()
PORT = int(os.getenv("PORT", "8080"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")

# -------------------------------------------------
# TELEGRAM + FLASK
# -------------------------------------------------
bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
app = Flask(__name__)

# -------------------------------------------------
# PARSERS
# -------------------------------------------------
def parse_mac_command(text: str):
    """
    /mac LEAGUE | YYYY-MM-DD | HOME - AWAY
    """
    try:
        raw = text.replace("/mac", "").strip()
        parts = [p.strip() for p in raw.split("|")]
        if len(parts) != 3:
            return None
        league = normalize_league_input(parts[0])
        date_str = parts[1]
        teams = parts[2].split("-")
        if len(teams) != 2:
            return None
        home = teams[0].strip()
        away = teams[1].strip()
        return {"league": league, "date": date_str, "home": home, "away": away}
    except Exception:
        return None


def parse_result_command(text: str):
    """
    /result LEAGUE | YYYY-MM-DD | HOME - AWAY | TOTAL
    """
    try:
        raw = text.replace("/result", "").strip()
        parts = [p.strip() for p in raw.split("|")]
        if len(parts) != 4:
            return None
        league = normalize_league_input(parts[0])
        date_str = parts[1]
        teams = parts[2].split("-")
        if len(teams) != 2:
            return None
        home = teams[0].strip()
        away = teams[1].strip()
        total = float(parts[3])
        return {
            "league": league,
            "date": date_str,
            "home": home,
            "away": away,
            "total": total
        }
    except Exception:
        return None

# -------------------------------------------------
# /mac HANDLER
# -------------------------------------------------
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

    # FAZ-17
    market_data, market_meta = faz17_fetch_market_safe(
        provider_fetch_func=faz17_fetch_market,
        league=league,
        date_str=date_str,
        home=home,
        away=away,
    )

    # FAZ-13
    faz13 = run_faz13_auto_pipeline(
        league=league,
        home=home,
        away=away,
        date_str=date_str,
        market_data=market_data,
        market_meta=market_meta,
    )

    # FAZ-22
    match_data = {
        "league": league,
        "base_pred": faz13.get("base_pred"),
        "faz13_pred": faz13.get("base_pred"),
        "band": faz13.get("band"),
        "faz17_market_ref": (faz13.get("market") or {}).get("totals_line"),
    }
    faz22 = faz22_meta_engine(match_data)

    # FAZ-23 memory
    faz23_memory_write(
        league=league,
        date_str=date_str,
        home=home,
        away=away,
        faz13_result=faz13,
        faz22_result=faz22,
        actual_total=None,
    )

    # ✅ REPLY (market_data YOK!)
    market = faz13.get("market") or {}

    reply = (
        f"🏀 {home} - {away}\n"
        f"🏷️ {league} | 📅 {date_str}\n\n"
        f"🧠 Base: {faz13.get('base_pred')}\n"
        f"🎯 Band: {faz13.get('band')}\n"
        f"🧬 META: {faz22.get('meta_pred')} "
        f"[{faz22.get('range_low')}, {faz22.get('range_high')}]\n"
        f"✅ Confidence: {faz22.get('confidence')}\n"
        f"📈 Market Line: {market.get('totals_line')}\n"
    )

    bot.reply_to(message, reply)

# -------------------------------------------------
# /result HANDLER
# -------------------------------------------------
@bot.message_handler(commands=["result"])
def handle_result(message):
    parsed = parse_result_command(message.text or "")
    if not parsed:
        bot.reply_to(message, "❌ Format hatalı.\n/result LIG | YYYY-MM-DD | EV - DEP | TOTAL")
        return

    out = faz23_apply_result(
        league=parsed["league"],
        date_str=parsed["date"],
        home=parsed["home"],
        away=parsed["away"],
        actual_total=parsed["total"],
    )

    bot.reply_to(
        message,
        f"✅ Sonuç işlendi.\nTags: {out.get('tags')}\nAbsErr: {out.get('abs_error')}"
    )

# -------------------------------------------------
# WEBHOOK ENDPOINT (SABİT PATH)
# -------------------------------------------------
@app.route("/webhook", methods=["POST"])
def webhook():
    raw = request.get_data(as_text=True) or ""
    try:
        payload = json.loads(raw) if raw else {}
    except Exception:
        payload = {}
    update = telebot.types.Update.de_json(payload)
    bot.process_new_updates([update])
    return "OK", 200

# -------------------------------------------------
# HEALTH CHECK
# -------------------------------------------------
@app.route("/")
def health():
    return "OK", 200

# -------------------------------------------------
# ENTRYPOINT (FINAL)
# -------------------------------------------------
if __name__ == "__main__":
    if WEBHOOK_URL:
        log.info("Starting in WEBHOOK mode")
        bot.remove_webhook()
        bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")
        app.run(host="0.0.0.0", port=PORT)
    else:
        log.info("Starting in POLLING mode (no webhook)")
        bot.infinity_polling()

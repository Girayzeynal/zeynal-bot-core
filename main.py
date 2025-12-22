# main.py
import os
import json
import logging
from flask import Flask, request
import telebot

from core.elite_league_registry import normalize_league_input
from faz17_engine.providers import faz17_fetch_market
from faz17_engine.faz17_market_fetcher import faz17_fetch_market_safe
from faz13_engine.faz13_orchestrator import run_faz13_auto_pipeline
from faz22_engine.faz22_meta import faz22_meta_engine
from faz23_engine.faz23_core import faz23_memory_write
from faz23_engine.faz23_feedback import faz23_apply_result, get_w_market

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
log = logging.getLogger("MAIN")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()
PORT = int(os.getenv("PORT", "8080"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
app = Flask(__name__)

_LAST_UPD = {"id": 0}

def _dedupe_update(payload: dict) -> bool:
    try:
        upd_id = int(payload.get("update_id", 0))
        if upd_id <= _LAST_UPD["id"]:
            return False
        _LAST_UPD["id"] = upd_id
        return True
    except Exception:
        return True

def parse_mac_command(text: str):
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
        return {"league": league, "date": date_str, "home": home, "away": away, "total": total}
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
        f"⚙️ w_market(NBA): {get_w_market('NBA')}\n"
        f"⚙️ w_market(EUROLEAGUE): {get_w_market('EUROLEAGUE')}\n"
    )
    bot.reply_to(message, reply)

@bot.message_handler(commands=["mac"])
def handle_mac(message):
    parsed = parse_mac_command(message.text or "")
    if not parsed:
        bot.reply_to(message, "❌ Format hatalı.\n/mac LIG | YYYY-MM-DD | EV - DEP")
        return

    league = parsed["league"]; date_str = parsed["date"]; home = parsed["home"]; away = parsed["away"]
    log.info(f"MAC REQUEST | {league} | {date_str} | {home} vs {away}")

    market_data, market_meta = faz17_fetch_market_safe(
        provider_fetch_func=faz17_fetch_market,
        league=league,
        date_str=date_str,
        home=home,
        away=away,
    )

    faz13 = run_faz13_auto_pipeline(
        league=league,
        home=home,
        away=away,
        date_str=date_str,
        market_data=market_data,
        market_meta=market_meta,
    )

    market_line = (market_data or {}).get("totals_line") if isinstance(market_data, dict) else None
    match_data = {
        "league": league,
        "faz13_pred": faz13.get("base_pred"),
        "band": faz13.get("band"),
        "faz17_market_ref": market_line,
    }
    faz22 = faz22_meta_engine(match_data)

    faz23_memory_write(
        league=league,
        date_str=date_str,
        home=home,
        away=away,
        faz13_result=faz13,
        faz22_result=faz22,
        actual_total=None,
    )

    periods = faz13.get("periods", {})
    base = faz13.get("base_pred")
    band = faz13.get("band")
    meta_pred = faz22.get("meta_pred")
    rlow = faz22.get("range_low"); rhigh = faz22.get("range_high")
    conf = faz22.get("confidence")

    # market delta + alt/üst
    delta = faz22.get("market", {}).get("delta")
    ou_dir = "UNKNOWN"
    if market_line is not None and meta_pred is not None:
        try:
            ou_dir = "OVER" if float(meta_pred) > float(market_line) else "UNDER"
        except Exception:
            pass

    reply = (
        f"🏀 {home} - {away}\n"
        f"🏷️ {league} | 📅 {date_str}\n\n"
        f"🧠 Base: {base}\n"
        f"🎯 Band: {band}\n"
        f"🧬 META: {meta_pred} [{rlow}, {rhigh}]\n"
        f"✅ Confidence: {conf}\n"
        f"📈 Market Line: {market_line}\n"
        f"📉 Market Δ: {delta}\n"
        f"🔼/🔽 O/U Dir: {ou_dir}\n\n"
        f"📊 Periyot Tahminleri:\n"
        f" • 1Q: {periods.get('q1')}\n"
        f" • 2Q: {periods.get('q2')} (İY: {periods.get('h1')})\n"
        f" • 3Q: {periods.get('q3')}\n"
        f" • 4Q: {periods.get('q4')} (2Y: {periods.get('h2')})\n"
    )
    bot.reply_to(message, reply)

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
    bot.reply_to(message, f"✅ Sonuç işlendi.\nTags: {out.get('tags')}\nAbsErr: {out.get('abs_error')}")

@app.route("/webhook", methods=["POST"])
@app.route("/webhook/<path:extra>", methods=["POST"])
def webhook(extra=None):
    raw = request.get_data(as_text=True) or ""
    try:
        payload = json.loads(raw) if raw else {}
    except Exception:
        payload = {}

    if not _dedupe_update(payload):
        return "OK", 200

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

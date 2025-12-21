# main.py
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
log = logging.getLogger("MAIN")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()
PORT = int(os.getenv("PORT", "8080"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
app = Flask(__name__)


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
        return {"league": league, "date": date_str, "home": home, "away": away, "total": total}
    except Exception:
        return None


def _format_reply(f13: dict, f22: dict) -> str:
    home = f13.get("home", "?")
    away = f13.get("away", "?")
    league = f13.get("league", "?")
    date_str = f13.get("date", "?")

    base_pred = f13.get("base_pred")
    band = f13.get("band", [])
    periods = f13.get("periods", {})
    play = f13.get("play", {}) if isinstance(f13.get("play"), dict) else {}
    play_flag = play.get("play", True)
    play_risk = play.get("risk", "MID")
    play_reason = play.get("reason", "ok")

    meta_pred = f22.get("meta_pred")
    rlow = f22.get("range_low")
    rhigh = f22.get("range_high")
    conf = f22.get("confidence")
    hist = f22.get("history", {}) if isinstance(f22.get("history"), dict) else {}

    market = f13.get("market", {}) if isinstance(f13.get("market"), dict) else {}
    m_used = market.get("used", False)
    m_conf = market.get("confidence", 0.0)
    m_line = market.get("totals_line", None)

    return (
        f"🏀 {home} - {away}\n"
        f"🏷️ {league} | 📅 {date_str}\n\n"
        f"🧠 FAZ-13 Base: {base_pred}\n"
        f"🎯 FAZ-13 Band: {band}\n"
        f"🚦 Oynanır mı?: {play_flag} | Risk: {play_risk} | Reason: {play_reason}\n\n"
        f"🧬 FAZ-22 META: {meta_pred}\n"
        f"📌 Final Band: [{rlow}, {rhigh}]\n"
        f"✅ Confidence: {conf}\n"
        f"📚 History: n={hist.get('n',0)} hit={hist.get('hit_rate',0)} mae={hist.get('mae',0)}\n\n"
        f"⏱️ Senaryo (Toplam):\n"
        f" • 1Q: {periods.get('q1')}  2Q: {periods.get('q2')}  (İY: {periods.get('h1')})\n"
        f" • 3Q: {periods.get('q3')}  4Q: {periods.get('q4')}\n\n"
        f"📈 Market:\n"
        f" • Used: {m_used} | Conf: {m_conf} | Line: {m_line}\n"
    )


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

    # FAZ-17 market (safe)
    market_data, market_meta = faz17_fetch_market_safe(
        provider_fetch_func=faz17_fetch_market,
        league=league,
        date_str=date_str,
        home=home,
        away=away,
    )

    # FAZ-13 base
    faz13 = run_faz13_auto_pipeline(
        league=league,
        home=home,
        away=away,
        date_str=date_str,
        market_data=market_data,
        market_meta=market_meta,
    )

    # FAZ-22 meta + true confidence
    match_data = {
        "league": league,
        "base_pred": faz13.get("base_pred"),
        "faz13_pred": faz13.get("base_pred"),
        "band": faz13.get("band"),
        "faz17_market_ref": (faz13.get("market") or {}).get("totals_line"),
    }
    faz22 = faz22_meta_engine(match_data)

    # FAZ-23 memory write
    faz23_memory_write(
        league=league,
        date_str=date_str,
        home=home,
        away=away,
        faz13_result=faz13,
        faz22_result=faz22,
        actual_total=None,
    )

    bot.reply_to(message, _format_reply(faz13, faz22))


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

    msg = (
        f"✅ Sonuç işlendi.\n"
        f"🏷️ {parsed['league']} | 📅 {parsed['date']}\n"
        f"🏀 {parsed['home']} - {parsed['away']}\n"
        f"📌 Actual Total: {parsed['total']}\n\n"
        f"🧠 Error: {out.get('error')}\n"
        f"🏷️ Tags: {', '.join(out.get('tags') or []) or 'Yok'}\n"
        f"📉 AbsErr: {out.get('abs_error')}\n"
        f"🎯 HitBand: {out.get('hit_band')}\n"
        f"🧬 MetaΔ: {out.get('meta_delta_hint')}\n"
        f"⚙️ NewWeights: {out.get('new_weights')}\n"
    )
    bot.reply_to(message, msg)


@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
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
    # Lokal test için polling
    log.info("Starting in polling mode (local)")
    bot.infinity_polling() 

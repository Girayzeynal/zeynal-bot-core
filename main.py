import os, json, logging
from flask import Flask, request
import telebot

from core.elite_league_registry import normalize_league_input
from faz13_engine.faz13_orchestrator import run_faz13_auto_pipeline
from faz17_engine.faz17_market import fetch_market
from faz23_engine.faz23_stats import build_context_for_match

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
log = logging.getLogger("MAIN")

BOT_TOKEN = os.getenv("BOT_TOKEN","").strip()
WEBHOOK_URL = os.getenv("WEBHOOK_URL","").strip()
PORT = int(os.getenv("PORT","8080"))

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
app = Flask(__name__)

def parse_mac_command(text: str):
    try:
        raw = text.replace("/mac","").strip()
        p=[x.strip() for x in raw.split("|")]
        if len(p)!=3: return None
        league = normalize_league_input(p[0])
        date_str = p[1]
        t = p[2].split("-")
        if len(t)!=2: return None
        return {"league":league,"date":date_str,"home":t[0].strip(),"away":t[1].strip()}
    except Exception:
        return None

@bot.message_handler(commands=["mac"])
def handle_mac(message):
    parsed = parse_mac_command(message.text or "")
    if not parsed:
        bot.reply_to(message,"❌ /mac NBA | YYYY-MM-DD | HOME - AWAY"); return

    league, date_str, home, away = parsed["league"], parsed["date"], parsed["home"], parsed["away"]
    log.info(f"MAC | {league} | {date_str} | {home}-{away}")

    market_data, market_meta = fetch_market(league, date_str, home, away)
    context = build_context_for_match(league, home, away, date_str, last_n=5)

    faz13 = run_faz13_auto_pipeline(
        league=league,
        home=home,
        away=away,
        date_str=date_str,
        market_data=market_data,
        market_meta=market_meta,
        extra_inputs=context,
    )

    p = faz13["periods"]
    reply = (
        f"🏀 {home} - {away}\n"
        f"🏷️ {league} | 📅 {date_str}\n\n"
        f"🧠 Base: {faz13['base_pred']}\n"
        f"🎯 Band: {faz13['band']}\n"
        f"✅ Confidence: {faz13['confidence']}\n"
        f"⚠️ Risk: {faz13['risk']}\n\n"
        f"📈 Market Line: {faz13['market']['line']}\n"
        f"📉 Market Δ: {faz13['market']['delta']}\n"
        f"🔼/🔽 O/U: {faz13['ou']['dir']}\n\n"
        f"📊 Periyotlar:\n"
        f"1Q {p['q1']} | 2Q {p['q2']} (İY {p['h1']}) | "
        f"3Q {p['q3']} | 4Q {p['q4']} (2Y {p['h2']})"
    )
    bot.reply_to(message, reply)

@bot.message_handler(commands=["status"])
def status(message):
    bot.reply_to(message,
        "🧠 Zeynal Core /status\n"
        f"ODDS {'OK' if os.getenv('ODDS_API_KEY') else 'MISSING'}\n"
        f"API-SPORTS {'OK' if os.getenv('API_SPORT_KEY') else 'MISSING'}"
    )

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    try: payload=json.loads(request.get_data(as_text=True) or "{}")
    except Exception: payload={}
    update=telebot.types.Update.de_json(payload)
    bot.process_new_updates([update])
    return "OK",200

@app.route("/")
def health(): return "OK",200

if __name__=="__main__":
    bot.remove_webhook() 

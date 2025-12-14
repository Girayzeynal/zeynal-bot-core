# -*- coding: utf-8 -*-
""" Zeynal Core AI - FIXED MAIN """

import os
import json
import time
import logging
import threading
import requests
from concurrent.futures import ThreadPoolExecutor
import telebot
from flask import Flask, request

# ================================================================
# LOGGING
# ================================================================
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("zeynal-core")

# ================================================================
# ENV
# ================================================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
PORT = int(os.getenv("PORT", "8080"))

ODDS_API_KEY = os.getenv("ODDS_API_KEY", "").strip()

AUTO_WEBHOOK = os.getenv("AUTO_WEBHOOK", "1").strip() == "1"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN missing")

# ================================================================
# TELEGRAM + FLASK
# ================================================================
bot = telebot.TeleBot(BOT_TOKEN, threaded=True)
app = Flask(__name__)

# ================================================================
# FAZ STATUS
# ================================================================
FAZ_STATUS = {}
def _set_faz(name: str, ok: bool, msg: str = ""):
    FAZ_STATUS[name] = {
        "ok": bool(ok),
        "icon": "✅" if ok else "",
        "msg": msg or ("OK" if ok else "FAILED"),
    }

# ================================================================
# JSON UTILS
# ================================================================
TG_LIMIT = 3900

def _safe_json(obj):
    try:
        s = json.dumps(obj, ensure_ascii=False, indent=2)
    except Exception:
        s = str(obj)

    chunks = []
    while len(s) > TG_LIMIT:
        chunks.append(s[:TG_LIMIT])
        s = s[TG_LIMIT:]
    chunks.append(s)
    return chunks

# ================================================================
# ODDS SPORT KEY DISCOVERY
# ================================================================
_ODDS_SPORTS_CACHE = {"ts": 0, "data": []}

def odds_list_sports(ttl_sec: int = 6 * 3600):
    now = time.time()
    if _ODDS_SPORTS_CACHE["data"] and (now - _ODDS_SPORTS_CACHE["ts"] < ttl_sec):
        return _ODDS_SPORTS_CACHE["data"]

    if not ODDS_API_KEY:
        return []

    url = "https://api.the-odds-api.com/v4/sports"
    r = requests.get(url, params={"apiKey": ODDS_API_KEY}, timeout=10)
    data = r.json()
    _ODDS_SPORTS_CACHE["ts"] = now
    _ODDS_SPORTS_CACHE["data"] = data
    return data

def pick_sport_key_for_family(family: str):
    family = (family or "").lower()
    sports_list = odds_list_sports()
    candidates = []
    for s in sports_list:
        key = (s.get("key") or "").lower()
        title = (s.get("title") or "").lower()
        group = (s.get("group") or "").lower()

        score = 0
        if "basketball" in group or "basketball" in title:
            score += 2
        if family in title or family in key:
            score += 3

        if score > 0:
            candidates.append((score, s.get("key")))

    candidates.sort(reverse=True, key=lambda x: x[0])
    return candidates[0][1] if candidates else None

# ================================================================
# MARKET FETCH
# ================================================================
def get_market_data(league: str, date_str: str, home: str, away: str):
    sport_key = pick_sport_key_for_family(league)
    if not sport_key:
        return {"used": False, "error": f"No ODDS sport key for family={league}", "src": {}}

    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us,eu",
        "markets": "h2h,totals",
        "dateFormat": "iso"
    }
    r = requests.get(url, params=params, timeout=10).json()
    return {"used": True, "odds": r, "src": {"provider": sport_key}}

# ================================================================
# PARSER
# ================================================================
def _parse_mac_command(text: str):
    raw = (text or "").replace("/mac", "", 1).strip()
    parts = [p.strip() for p in raw.split("|")]
    if len(parts) < 3:
        raise ValueError("Format hatası.\nÖrnek: /mac NBA | 2025-12-14 | Orlando - New York")
    league, date_str, teams = parts[:3]
    if "-" not in teams:
        raise ValueError("Takım ayırıcı '-' yok.")
    home, away = [t.strip() for t in teams.split("-", 1)]
    return league, date_str, home, away

# ================================================================
# RUN PIPELINE
# ================================================================
def run_match_pipeline(league, date_str, home, away, source_type="mac_command"):
    meta = {"league": league, "date": date_str, "home": home, "away": away}

    market_data = get_market_data(league, date_str, home, away)

    result = {
        "meta": meta,
        "market_data": market_data
    }

    return result

# ================================================================
# TELEGRAM COMMAND HANDLERS
# ================================================================
@bot.message_handler(commands=["start"])
def on_start(msg):
    bot.reply_to(
        msg,
        "Zeynal Core AI aktif!\n"
        "/mac LIG | YYYY-MM-DD | Home - Away\n"
        "/status -> FAZ durumları"
    )

@bot.message_handler(commands=["status"])
def on_status(msg):
    lines = ["FAZ STATUS:"]
    for k, v in FAZ_STATUS.items():
        lines.append(f"{v['icon']} {k} - {v['msg']}")
    bot.reply_to(msg, "\n".join(lines))

@bot.message_handler(commands=["mac"])
def on_mac(msg):
    try:
        league, date_str, home, away = _parse_mac_command(msg.text)
    except Exception as e:
        bot.reply_to(msg, f"❌ {e}")
        return

    bot.reply_to(msg, f"⏳ Analiz ediliyor:\n{league} | {date_str}\n{home} - {away}")

    result = run_match_pipeline(league, date_str, home, away)
    for part in _safe_json(result):
        bot.reply_to(msg, f"```json\n{part}\n```", parse_mode="Markdown")

# ================================================================
# WEBHOOK + BOOTSTRAP
# ================================================================
@app.get("/")
def health():
    return "OK", 200

@app.post("/webhook")
def telegram_webhook():
    token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if WEBHOOK_SECRET and token != WEBHOOK_SECRET:
        return "forbidden", 403
    update = request.get_data(as_text=True)
    try:
        upd = telebot.types.Update.de_json(update)
        bot.process_new_updates([upd])
    except Exception as e:
        log.warning(f"Webhook parse error: {e}")
    return "OK", 200

# ================================================================
if __name__ == "__main__":
    if AUTO_WEBHOOK and WEBHOOK_URL:
        bot.remove_webhook()
        time.sleep(0.2)
        bot.set_webhook(url=WEBHOOK_URL, secret_token=WEBHOOK_SECRET if WEBHOOK_SECRET else None)
    else:
        bot.infinity_polling()

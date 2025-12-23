# main.py — FINAL BUILD (FAZ-7…FAZ-23 Guarded Orchestrator)
# Fly.io + Flask (health/webhook) + Telebot (Telegram)
# Goals:
# - Crash-proof: no unhandled exceptions in handlers
# - FAZ modules are OPTIONAL imports (no "hayalet" sessiz çöküş)
# - Market fetch guarded
# - FAZ-22 function name fixed: faz22_meta_engine
# - Webhook setup controlled via AUTO_SET_WEBHOOK=1 (safe for multi-worker)

import os
import json
import time
import logging
from typing import Any, Dict, Optional, Tuple

from flask import Flask, request

import telebot
from telebot import types


# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
log = logging.getLogger("ZeynalBotCore")


# -----------------------------------------------------------------------------
# Env
# -----------------------------------------------------------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()
PORT = int(os.getenv("PORT", "8080"))

AUTO_SET_WEBHOOK = os.getenv("AUTO_SET_WEBHOOK", "0").strip() in ("1", "true", "TRUE", "yes", "YES")


# -----------------------------------------------------------------------------
# App objects
# -----------------------------------------------------------------------------
app = Flask(__name__)

if not BOT_TOKEN:
    log.warning("BOT_TOKEN is missing. Telegram bot will NOT function until it is set.")
bot = telebot.TeleBot(BOT_TOKEN, threaded=True) if BOT_TOKEN else None


# -----------------------------------------------------------------------------
# Safe imports (FAZ)
# -----------------------------------------------------------------------------
def _safe_import(path: str, name: str):
    try:
        module = __import__(path, fromlist=[name])
        return getattr(module, name)
    except Exception as e:
        log.warning(f"Optional import failed: {path}.{name} -> {e}")
        return None


# Core league registry / normalizer (optional)
normalize_league = _safe_import("core.elite_league_registry", "normalize_league")

# FAZ-13 orchestrator (primary)
run_faz13_auto_pipeline = _safe_import("faz13_engine.faz13_orchestrator", "run_faz13_auto_pipeline")

# FAZ-17 market fetcher (optional)
fetch_market = _safe_import("faz17_engine.faz17_market_fetcher", "fetch_market")

# FAZ-22 meta engine (optional) — IMPORTANT: name must be faz22_meta_engine
faz22_meta_engine = _safe_import("faz22_engine.faz22_meta_engine", "faz22_meta_engine")

# FAZ-23 state/orchestrator hooks (optional)
faz23_apply_state = _safe_import("faz23_engine.faz23_state", "faz23_apply_state")
faz23_feedback = _safe_import("faz23_engine.faz23_state", "faz23_feedback")  # if exists


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _ok(v: Any) -> str:
    return "OK" if v else "MISSING"


def _compact_json(x: Any) -> str:
    try:
        return json.dumps(x, ensure_ascii=False)
    except Exception:
        return str(x)


def _parse_mac_command(text: str) -> Optional[Dict[str, str]]:
    """
    Expected:
      /mac <LEAGUE> | <YYYY-MM-DD> | <HOME>-<AWAY>
    Example:
      /mac NBA | 2025-12-23 | Boston-Celtics - Detroit-Pistons   (spaces tolerated)
    """
    try:
        raw = (text or "").strip()
        if not raw.startswith("/mac"):
            return None

        # remove leading "/mac"
        raw = raw.replace("/mac", "", 1).strip()

        parts = [p.strip() for p in raw.split("|")]
        if len(parts) != 3:
            return None

        league_in = parts[0]
        date_str = parts[1]
        matchup = parts[2]

        # normalize league if function exists
        league = normalize_league(league_in) if normalize_league else league_in.strip().upper()

        # parse HOME-AWAY (support both '-' and ' - ')
        if "-" not in matchup:
            return None

        # If user uses "HOME - AWAY" (with spaces), split by " - " first
        if " - " in matchup:
            home, away = [x.strip() for x in matchup.split(" - ", 1)]
        else:
            # fallback first dash split
            home, away = [x.strip() for x in matchup.split("-", 1)]

        if not league or not date_str or not home or not away:
            return None

        return {"league": league, "date_str": date_str, "home": home, "away": away}
    except Exception as e:
        log.warning(f"parse_mac_command failed: {e}")
        return None


def _safe_fetch_market(league: str, date_str: str, home: str, away: str) -> Tuple[Optional[dict], Optional[dict]]:
    if not fetch_market:
        return None, None
    try:
        return fetch_market(league, date_str, home, away)
    except Exception as e:
        log.warning(f"FAZ-17 market fetch failed: {e}")
        return None, None


def _build_context_for_match(league: str, home: str, away: str, date_str: str, market_data: Optional[dict]) -> Dict[str, Any]:
    # Keep context minimal; FAZ-13 can enrich it further.
    return {
        "league": league,
        "home": home,
        "away": away,
        "date_str": date_str,
        "market_data_present": bool(market_data),
        "ts": int(time.time()),
    }


def _format_faz13_reply(league: str, home: str, away: str, date_str: str, faz13: Dict[str, Any]) -> str:
    # Defensive reads
    base = faz13.get("base_pred")
    band = faz13.get("band")
    confidence = faz13.get("confidence")
    risk = faz13.get("risk")
    market = faz13.get("market")
    ou = None
    try:
        ou = (market or {}).get("ou", {})
    except Exception:
        ou = None

    periods = faz13.get("periods") or {}
    p1 = periods.get("q1")
    p2 = periods.get("q2")
    p3 = periods.get("q3")
    p4 = periods.get("q4")
    h1 = periods.get("h1")
    h2 = periods.get("h2")

    lines = []
    lines.append(f"🏀 {home} — {away}")
    lines.append(f"🗓️ {league} | {date_str}")
    lines.append("")
    lines.append(f"🎯 Base: {base}")
    lines.append(f"📦 Band: {band}")
    lines.append(f"🧠 Confidence: {confidence}")
    lines.append(f"⚠️ Risk: {risk}")
    lines.append(f"📈 Market: {market}")
    if ou:
        lines.append(f"🧮 O/U: {ou.get('dir')} (line={ou.get('line')})")
    lines.append("")
    lines.append("⏱️ Periyotlar:")
    lines.append(f"1Q: {p1} | 2Q: {p2} | İY: {h1}")
    lines.append(f"3Q: {p3} | 4Q: {p4} | 2Y: {h2}")

    return "\n".join(lines)


def _apply_faz22_if_available(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    FAZ-22 meta engine can post-process the payload:
    - calibration
    - sanity checks
    - variance/risk refinements
    """
    if not faz22_meta_engine:
        return payload
    try:
        out = faz22_meta_engine(payload)
        return out if isinstance(out, dict) else payload
    except Exception as e:
        log.warning(f"FAZ-22 meta engine failed: {e}")
        return payload


def _apply_faz23_if_available(league: str, home: str, away: str, date_str: str, result: Dict[str, Any]) -> None:
    """
    FAZ-23 state binding (optional). Does NOT break pipeline if missing.
    """
    if not faz23_apply_state:
        return
    try:
        faz23_apply_state(
            league=league,
            home=home,
            away=away,
            date_str=date_str,
            result=result,
        )
    except Exception as e:
        log.warning(f"FAZ-23 apply state failed: {e}")


def _run_pipeline(league: str, date_str: str, home: str, away: str) -> Dict[str, Any]:
    """
    Main orchestration:
    - FAZ-17 market
    - Context
    - FAZ-13 prediction
    - FAZ-22 meta post-process
    - FAZ-23 state apply
    """
    if not run_faz13_auto_pipeline:
        return {"error": "FAZ-13 orchestrator missing (run_faz13_auto_pipeline import failed)."}

    market_data, market_meta = _safe_fetch_market(league, date_str, home, away)
    context = _build_context_for_match(league, home, away, date_str, market_data)

    try:
        faz13 = run_faz13_auto_pipeline(
            league=league,
            home=home,
            away=away,
            date_str=date_str,
            market_data=market_data,
            market_meta=market_meta,
            extra_inputs=context,
        )
    except Exception as e:
        log.exception("FAZ-13 pipeline crashed")
        return {"error": f"FAZ-13 pipeline crashed: {e}"}

    if not isinstance(faz13, dict):
        return {"error": f"FAZ-13 returned non-dict: {type(faz13).__name__}"}

    # Meta engine post-process
    faz13 = _apply_faz22_if_available(faz13)

    # Guard periods
    if "periods" not in faz13:
        faz13["periods"] = {}

    # State apply
    _apply_faz23_if_available(league, home, away, date_str, faz13)

    return faz13


# -----------------------------------------------------------------------------
# Telegram handlers
# -----------------------------------------------------------------------------
if bot:

    @bot.message_handler(commands=["mac"])
    def handle_mac(message: types.Message):
        parsed = _parse_mac_command(message.text or "")
        if not parsed:
            bot.reply_to(
                message,
                "❌ Format:\n"
                "/mac LEAGUE | YYYY-MM-DD | HOME - AWAY\n"
                "Örn: /mac NBA | 2025-12-23 | Boston - Detroit"
            )
            return

        league = parsed["league"]
        date_str = parsed["date_str"]
        home = parsed["home"]
        away = parsed["away"]

        log.info(f"MAC | {league} | {date_str} | {home}-{away}")

        faz13 = _run_pipeline(league, date_str, home, away)
        if "error" in faz13:
            bot.reply_to(message, f"❌ {faz13['error']}")
            return

        reply = _format_faz13_reply(league, home, away, date_str, faz13)
        bot.reply_to(message, reply)

    @bot.message_handler(commands=["status"])
    def status(message: types.Message):
        bot.reply_to(
            message,
            "🤖 Zeynal Core /status\n"
            f"BOT_TOKEN: {_ok(BOT_TOKEN)}\n"
            f"WEBHOOK_URL: {_ok(WEBHOOK_URL)}\n"
            f"FAZ-13: {_ok(run_faz13_auto_pipeline)}\n"
            f"FAZ-17: {_ok(fetch_market)}\n"
            f"FAZ-22: {_ok(faz22_meta_engine)}\n"
            f"FAZ-23: {_ok(faz23_apply_state)}\n"
        )


# -----------------------------------------------------------------------------
# Flask routes (Fly.io health + Telegram webhook)
# -----------------------------------------------------------------------------
@app.route("/", methods=["GET"])
def health():
    return "OK", 200


@app.route("/debug/env", methods=["GET"])
def debug_env():
    # Keep it safe; do NOT print secrets.
    return {
        "BOT_TOKEN": _ok(BOT_TOKEN),
        "WEBHOOK_URL": _ok(WEBHOOK_URL),
        "PORT": PORT,
        "AUTO_SET_WEBHOOK": AUTO_SET_WEBHOOK,
        "FAZ13": bool(run_faz13_auto_pipeline),
        "FAZ17": bool(fetch_market),
        "FAZ22": bool(faz22_meta_engine),
        "FAZ23": bool(faz23_apply_state),
    }, 200


@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def telegram_webhook():
    try:
        payload = request.get_json(force=True)
        update = types.Update.de_json(payload)
        bot.process_new_updates([update])
        return "OK", 200
    except Exception as e:
        log.exception("Webhook processing failed")
        return "ERR", 200
    except Exception as e:
        log.exception(f"Webhook processing failed: {e}")
        return "ERR", 200  # Telegram retries; 200 prevents retry storms


# -----------------------------------------------------------------------------
# Webhook setup (optional & safe-ish)
# -----------------------------------------------------------------------------
_webhook_set_once = False


@app.before_request
def _maybe_set_webhook_once():
    """
    In multi-worker deployments, this can run per worker.
    We keep it conservative: only set if AUTO_SET_WEBHOOK=1 and WEBHOOK_URL is present,
    and only attempt once per worker process.
    """
    global _webhook_set_once
    if _webhook_set_once:
        return
    if not AUTO_SET_WEBHOOK:
        return
    if not bot or not WEBHOOK_URL:
        return
    try:
        bot.remove_webhook()
        # small delay helps Telegram side sometimes
        time.sleep(0.3)
        ok = bot.set_webhook(url=WEBHOOK_URL.rstrip("/") + f"/{BOT_TOKEN}")
        log.info(f"Webhook set: {ok} -> {WEBHOOK_URL.rstrip('/') + f'/{BOT_TOKEN}'}")
    except Exception as e:
        log.warning(f"Auto webhook setup failed: {e}")
    finally:
        _webhook_set_once = True


# -----------------------------------------------------------------------------
# Local run (NOT used by gunicorn on Fly normally)
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    # For local dev:
    #   export BOT_TOKEN=...
    #   export WEBHOOK_URL=https://<your-domain>
    #   export AUTO_SET_WEBHOOK=1
    app.run(host="0.0.0.0", port=PORT)

from __future__ import annotations

import os
import html
import logging
import asyncio
from datetime import datetime
from typing import Any, Dict, Tuple

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from baseline.team_baseline_store import TeamBaselineStore, TeamBaselineBootstrapper
from providers.espn_adapter import ESPNAdapter

from faz13_engine import Faz13Engine, PrematchRequest
from faz17_engine import Faz17Engine
from faz22_engine import Faz22Engine
from faz23_engine import Faz23Engine

from aiohttp import web

# ============================
# LOGGING
# ============================
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("zeynal-core")

# ============================
# ENV
# ============================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")
API_SPORTS_KEY = os.getenv("API_SPORTS_KEY")
API_SPORTS_BASE = os.getenv("API_SPORTS_BASE", "https://v1.basketball.api-sports.io")

PORT = int(os.getenv("PORT", "8080"))

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN")

# ============================
# HELPERS
# ============================
def _parse_date(date_str: str) -> datetime:
    return datetime.strptime(date_str.strip(), "%Y-%m-%d")

def nba_season_string(date_str: str) -> str:
    d = _parse_date(date_str)
    start = d.year if d.month >= 10 else d.year - 1
    return f"{start}-{start + 1}"

def _ensure(obj: Any, name: str, default):
    if not hasattr(obj, name):
        setattr(obj, name, default)
    return getattr(obj, name)

# ============================
# ANALYZE COMMAND
# ============================
async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()

    try:
        _, params = text.split(" ", 1)
        league, date_str, rest = params.split(" ", 2)

        if " vs " not in rest.lower():
            raise ValueError("vs bulunamadı")

        home_raw, away_raw = rest.split(" vs ", 1)
    except Exception:
        await update.message.reply_text(
            "Kullanım:\n/analyze NBA 2026-01-19 Atlanta Hawks vs Milwaukee Bucks",
            disable_web_page_preview=True,
        )
        return

    # --- ENGINE ---
    faz13: Faz13Engine = context.application.bot_data["faz13"]
    bootstrapper: TeamBaselineBootstrapper = context.application.bot_data["baseline_bootstrapper"]

    # ============================
    # 🔥 AUTO BASELINE BOOTSTRAP
    # ============================
    try:
        await bootstrapper.ensure_async(league=league, team_input=home_raw, min_games=6)
        await bootstrapper.ensure_async(league=league, team_input=away_raw, min_games=6)
    except Exception as e:
        logger.warning(f"Baseline bootstrap failed: {e}")

    # ============================
    # FAZ-13 PREMATCH
    # ============================
    try:
        season_str = nba_season_string(date_str)

        request = PrematchRequest(
            None,          # fixture_id (yoksa None)
            league,
            date_str,
            home_raw,
            away_raw,
        )

        result = await faz13.run_prematch(request)

        meta = _ensure(result, "meta", {})
        notes = _ensure(result, "notes", [])

        meta["season_str"] = season_str

        await update.message.reply_text(
            f"OK: analiz tamamlandı.\n"
            f"Sezon: {season_str}\n"
            f"Risk: {meta.get('risk', 'UNKNOWN')}\n\n"
            f"Notlar:\n" + "\n".join(f"- {n}" for n in notes),
            disable_web_page_preview=True,
        )

    except Exception as e:
        logger.exception("ANALYZE ERROR")
        await update.message.reply_text(
            f"Analiz hatası: {html.escape(str(e))}",
            disable_web_page_preview=True,
        )

# ============================
# APP BOOTSTRAP
# ============================
def _build_application() -> Application:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    baseline_store = TeamBaselineStore()
    bootstrapper = TeamBaselineBootstrapper(store=baseline_store, adapters=[ESPNAdapter()])

    app.bot_data["baseline_store"] = baseline_store
    app.bot_data["baseline_bootstrapper"] = bootstrapper

    app.bot_data["faz13"] = Faz13Engine(
        baseline_store=baseline_store,
        api_sports_key=API_SPORTS_KEY,
        api_sports_base=API_SPORTS_BASE,
    )

    app.bot_data["faz17"] = Faz17Engine()
    app.bot_data["faz22"] = Faz22Engine()
    app.bot_data["faz23"] = Faz23Engine()

    app.add_handler(CommandHandler("analyze", analyze_command))
    return app

# ============================
# MAIN
# ============================
def main():
    app = _build_application()
    logger.info("Bot polling started")
    app.run_polling()

if __name__ == "__main__":
    main()

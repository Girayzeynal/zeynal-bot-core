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


def _parse_analyze_params(raw: str):
    parts = raw.split()
    if len(parts) < 4:
        raise ValueError("Eksik parametre")

    league = parts[0]
    date_str = parts[1]
    rest = parts[2:]

    lower = [p.lower() for p in rest]
    if "vs" in lower:
        i = lower.index("vs")
        home = " ".join(rest[:i])
        away = " ".join(rest[i + 1 :])
    else:
        mid = len(rest) // 2
        home = " ".join(rest[:mid])
        away = " ".join(rest[mid:])

    return league, date_str, home.strip(), away.strip()

# ============================
# /analyze
# ============================
async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()

    try:
        _, params = text.split(" ", 1)
        league, date_str, home_raw, away_raw = _parse_analyze_params(params)
    except Exception as e:
        await update.message.reply_text(
            f"Parametre hatası: {html.escape(str(e))}",
            disable_web_page_preview=True,
        )
        return

    faz13: Faz13Engine = context.application.bot_data["faz13"]

    # ---- AUTO BASELINE BOOTSTRAP ----
    bootstrapper = context.application.bot_data.get("baseline_bootstrapper")
    if bootstrapper and hasattr(bootstrapper, "ensure_async"):
        await bootstrapper.ensure_async(league=league, team_input=home_raw, min_games=6)
        await bootstrapper.ensure_async(league=league, team_input=away_raw, min_games=6)

    # ---- FAZ-13 REQUEST (DOĞRU) ----
    req = PrematchRequest(
        fixture_id=0,
        league=league,
        date_str=date_str,
        home=home_raw,
        away=away_raw,
    )

    try:
        result = await faz13.run_prematch(req)

        await update.message.reply_text(
            result.render_html(),
            disable_web_page_preview=True,
        )

    except Exception as e:
        logger.exception("FAZ-13 ANALYZE ERROR")
        await update.message.reply_text(
            f"Analiz hatası: {html.escape(str(e))}",
            disable_web_page_preview=True,
        )

# ============================
# BOOTSTRAP
# ============================
def _build_application() -> Application:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    baseline_store = TeamBaselineStore()
    bootstrapper = TeamBaselineBootstrapper(store=baseline_store, adapters=[ESPNAdapter()])

    app.bot_data["baseline_store"] = baseline_store
    app.bot_data["baseline_bootstrapper"] = bootstrapper

    app.bot_data["faz13"] = Faz13Engine(
        api_sports_key=API_SPORTS_KEY,
        api_sports_base=API_SPORTS_BASE,
        baseline_store=baseline_store,
    )

    app.bot_data["faz22"] = Faz22Engine()
    app.bot_data["faz23"] = Faz23Engine()

    app.add_handler(CommandHandler("analyze", analyze_command))
    return app

# ============================
# MAIN
# ============================
def main():
    app = _build_application()
    asyncio.run(app.run_polling())

if __name__ == "__main__":
    main()

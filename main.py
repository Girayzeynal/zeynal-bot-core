"""
Entry point for the Zeynal Core bot.

This script wires together the various analysis engines (FAZ-13, FAZ-17, FAZ-22
and FAZ-23) and exposes them through a Telegram bot interface.  It expects
certain environment variables to be set for API keys and uses a simple
``DummyStatsAdapter`` as a placeholder for pulling team statistics.  Replace
``DummyStatsAdapter`` with a concrete implementation of
:class:`baseline.team_baseline_store.TeamStatsAdapter` that fetches real
aggregate statistics if you wish to make the predictions more accurate.

Environment variables:

``TELEGRAM_BOT_TOKEN``
    The bot token obtained from BotFather on Telegram.
``API_SPORTS_KEY``
    API key for your sports data provider (used by the stats adapter).
``API_SPORTS_BASE`` (optional)
    Base URL for the sports data API.  Defaults to the API Sports basketball endpoint.
``ODDS_API_KEY``
    API key for The Odds API.
``ODDS_BASE`` (optional)
    Base URL for The Odds API.  Defaults to the v4 endpoint.
``FAZ23_STORAGE`` (optional)
    Path to the SQLite database used by FAZ-23 to persist snapshots.
"""

import logging
import os
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode

from faz13_engine import Faz13Engine, PrematchRequest
from faz17_engine import Faz17Engine
from faz22_engine import Faz22Engine
from faz23_engine import Faz23Engine


# ---------------------------------------------------------------------------
# Stats adapter implementation
#
# Faz13Engine requires an object implementing TeamStatsAdapter in order to
# bootstrap team baselines.  This dummy adapter does not fetch real data and
# always returns ``None``, which causes the engine to fall back to the neutral
# baseline.  You should replace this with a real implementation that calls
# your preferred sports data API.
# ---------------------------------------------------------------------------
# DummyStatsAdapter is retained for backward compatibility but is no longer
# referenced by main().  ``Faz13Engine`` can now be initialized directly
# with an API key and base URL, so this class is unused in normal
# operation.  You may delete it entirely if you do not require legacy
# adapter support.
class DummyStatsAdapter:
    def __init__(self, api_key: str, base_url: str) -> None:
        self.api_key = api_key
        self.base_url = base_url

    def fetch_team_recent_aggregate(self, league: str, team: str, n_games: int):
        return None


def _env(name: str) -> str:
    """Read a required environment variable or raise."""
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return val


async def cmd_analyze(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /analyze command to perform a full match analysis."""
    if not context.args:
        await update.message.reply_text(
            "Kullanım: /analyze <lig> | <YYYY-MM-DD> | <EvTakım> - <DepTakım>"
        )
        return
    try:
        raw = " ".join(context.args)
        parts = [p.strip() for p in raw.split("|")]
        if len(parts) != 3:
            raise ValueError
        league = parts[0]
        date_str = parts[1]
        home, away = [x.strip() for x in parts[2].split("-")]
    except Exception:
        await update.message.reply_text(
            "Kullanım: /analyze <lig> | <YYYY-MM-DD> | <EvTakım> - <DepTakım>"
        )
        return
    # Retrieve engine instances from bot_data
    faz13: Faz13Engine = context.application.bot_data["faz13"]
    faz17: Faz17Engine = context.application.bot_data["faz17"]
    faz22: Faz22Engine = context.application.bot_data["faz22"]
    faz23: Faz23Engine = context.application.bot_data["faz23"]
    # Perform pre-match analysis
    core = await faz13.run_prematch(
        PrematchRequest(0, league, date_str, home, away)
    )
    # Market enrichment
    core = await faz17.enrich_with_market(core)
    # Confidence & risk calibration
    core = faz22.score_and_finalize(core)
    # Persist snapshot
    await faz23.record_snapshot(core)
    # Send result to user
    await update.message.reply_text(
        core.render_html(), parse_mode=ParseMode.HTML
    )


async def cmd_health(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Simple health check command."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    await update.message.reply_text(f"OK ✅\nUTC: {now}")


async def cmd_start(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send help/usage instructions."""
    msg = (
        "HoopBrain Bot\n"
        "Bu bot maç öncesi analiz ve simülasyon için tasarlanmıştır.\n"
        "Bahis tavsiyesi olarak kullanılmamalıdır.\n\n"
        "<b>Komutlar</b>\n"
        "/start – Yardım ve açıklama\n"
        "/health – Botun sağlık durumunu kontrol et\n"
        "/analyze <lig> | <YYYY-MM-DD> | <EvTakım> - <DepTakım> – Tam analiz raporu\n\n"
        "<b>Örnek:</b>\n/analyze NBA | 2025-12-25 | Lakers - Warriors"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


def main() -> None:
    """Instantiate engines and run the Telegram bot."""
    # Load required API keys
    token = _env("TELEGRAM_BOT_TOKEN")
    api_sports_key = _env("API_SPORTS_KEY")
    odds_key = _env("ODDS_API_KEY")
    # Optional environment variables with sensible defaults
    api_sports_base = os.getenv("API_SPORTS_BASE", "https://v1.basketball.api-sports.io")
    odds_base = os.getenv("ODDS_BASE", "https://api.the-odds-api.com/v4")
    faz23_storage = os.getenv("FAZ23_STORAGE", "faz23_storage.sqlite")
    # Build Telegram application
    app = (
        Application.builder()
        .token(token)
        .concurrent_updates(True)
        .build()
    )
    # Create engine instances
    # ``Faz13Engine`` accepts either a TeamStatsAdapter or an API key/base URL.
    # Passing the API key directly allows use of the built‑in default adapter.
    app.bot_data["faz13"] = Faz13Engine(api_sports_key, api_sports_base)
    app.bot_data["faz17"] = Faz17Engine(odds_key, odds_base)
    app.bot_data["faz22"] = Faz22Engine()
    app.bot_data["faz23"] = Faz23Engine(storage_path=faz23_storage)
    # Register command handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("health", cmd_health))
    app.add_handler(CommandHandler("analyze", cmd_analyze))
    logging.basicConfig(level=logging.INFO)
    log = logging.getLogger("zeynal-bot-core")
    log.info("Bot starting…")
    # Run the bot (blocking call)
    app.run_polling(
        allowed_updates=None, close_loop=False, drop_pending_updates=True
    )


if __name__ == "__main__":
    main() 

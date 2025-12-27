"""
Entry point for the Zeynal Core bot.

This module wires together the various analysis engines (FAZ‑13, FAZ‑17, FAZ‑22 and
FAZ‑23) and exposes them through a Telegram bot interface.  Rather than
instantiating the engines at import time, the engines are created lazily
in a ``post_init`` callback once the Telegram application has been built.
This design more closely follows the idioms of ``python‑telegram‑bot``
(v20+) and ensures that asynchronous resources like HTTP sessions are
constructed in an event loop context.  On shutdown the market client
session is closed cleanly via an ``on_shutdown`` callback.

Configuration is provided via environment variables.  The following
variables are mandatory:

``TELEGRAM_BOT_TOKEN``
    Bot token obtained from BotFather on Telegram.
``API_SPORTS_KEY``
    API key for your sports data provider.  Used by FAZ‑13 for team stats.
``ODDS_API_KEY``
    API key for The Odds API.  Used by FAZ‑17 for market totals.

The following variables are optional and have sensible defaults:

``API_SPORTS_BASE`` – Base URL for the sports data API (default:
    ``https://v1.basketball.api-sports.io``)
``ODDS_BASE`` – Base URL for The Odds API (default:
    ``https://api.the-odds-api.com/v4``)
``FAZ23_STORAGE`` – Path to the SQLite database used by FAZ‑23 to persist
    snapshots (default: ``faz23_storage.sqlite``)

If any mandatory variable is missing the bot will refuse to start.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode

from faz13_engine import Faz13Engine, PrematchRequest
from faz17_engine import Faz17Engine
from faz22_engine import Faz22Engine
from faz23_engine import Faz23Engine


@dataclass
class AppConfig:
    """Configuration values loaded from the environment.

    All fields correspond to environment variables.  Required fields are
    validated in :func:`load_config`.  Optional fields fall back to
    sensible defaults if not provided.
    """

    telegram_bot_token: str
    api_sports_key: str
    odds_api_key: str
    api_sports_base: str = "https://v1.basketball.api-sports.io"
    odds_base: str = "https://api.the-odds-api.com/v4"
    faz23_storage: str = "faz23_storage.sqlite"


def _require_env(name: str) -> str:
    """Return the value of an environment variable or raise.

    :param name: Name of the environment variable.
    :raises RuntimeError: if the environment variable is not set or empty.
    """
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def load_config() -> AppConfig:
    """Load configuration from environment variables.

    Returns an :class:`AppConfig` populated with required and optional
    environment variables.  Required variables must be present, otherwise
    a :class:`RuntimeError` is raised.
    """
    cfg = AppConfig(
        telegram_bot_token=_require_env("TELEGRAM_BOT_TOKEN"),
        api_sports_key=_require_env("API_SPORTS_KEY"),
        odds_api_key=_require_env("ODDS_API_KEY"),
        api_sports_base=os.getenv(
            "API_SPORTS_BASE", AppConfig.api_sports_base
        ),
        odds_base=os.getenv("ODDS_BASE", AppConfig.odds_base),
        faz23_storage=os.getenv(
            "FAZ23_STORAGE", AppConfig.faz23_storage
        ),
    )
    return cfg


async def post_init(application: Application) -> None:
    """Application post‑initialisation callback.

    This callback runs once after the Telegram ``Application`` has been
    constructed but before it starts polling updates.  It reads
    configuration from the environment and populates the ``bot_data``
    dictionary with the analysis engines.  Storing engines in
    ``bot_data`` allows command handlers to retrieve them without using
    global state.
    """
    cfg = load_config()
    # Build engine instances using configuration values.  FAZ‑13 accepts
    # either a TeamStatsAdapter or an API key/base URL.  Passing the
    # API key directly causes it to fall back to its built‑in stub
    # adapter when no concrete stats provider is supplied.
    application.bot_data["faz13"] = Faz13Engine(cfg.api_sports_key, cfg.api_sports_base)
    application.bot_data["faz17"] = Faz17Engine(cfg.odds_api_key, cfg.odds_base)
    application.bot_data["faz22"] = Faz22Engine()
    application.bot_data["faz23"] = Faz23Engine(storage_path=cfg.faz23_storage)


async def on_shutdown(application: Application) -> None:
    """Application shutdown callback.

    Ensures that any asynchronous resources are cleaned up when the bot
    stops.  In particular, this closes the aiohttp session used by
    ``Faz17Engine`` if it has been opened.
    """
    faz17: Optional[Faz17Engine] = application.bot_data.get("faz17")  # type: ignore[assignment]
    if faz17 and getattr(faz17, "session", None):
        session = faz17.session
        if session and not session.closed:
            await session.close()


async def cmd_analyze(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the `/analyze` command.

    Expected syntax: ``/analyze <league> | <YYYY-MM-DD> | <Home Team> - <Away Team>``.

    Parses user input, invokes the analysis engines and sends the
    formatted result back to the user.  Errors in parsing will result
    in a usage message being sent.
    """
    if not context.args:
        await update.message.reply_text(
            "Kullanım: /analyze <lig> | <YYYY-MM-DD> | <EvTakım> - <DepTakım>"
        )
        return
    try:
        raw_args = " ".join(context.args)
        parts = [p.strip() for p in raw_args.split("|")]
        if len(parts) != 3:
            raise ValueError
        league = parts[0]
        date_str = parts[1]
        home, away = [s.strip() for s in parts[2].split("-")]
    except Exception:
        await update.message.reply_text(
            "Kullanım: /analyze <lig> | <YYYY-MM-DD> | <EvTakım> - <DepTakım>"
        )
        return
    # Retrieve engines from bot_data; they were instantiated in post_init.
    faz13: Faz13Engine = context.application.bot_data["faz13"]
    faz17: Faz17Engine = context.application.bot_data["faz17"]
    faz22: Faz22Engine = context.application.bot_data["faz22"]
    faz23: Faz23Engine = context.application.bot_data["faz23"]
    # Perform pre‑match analysis
    core = await faz13.run_prematch(
        PrematchRequest(0, league, date_str, home, away)
    )
    # Enrich with market data
    core = await faz17.enrich_with_market(core)
    # Calibrate confidence and risk
    core = faz22.score_and_finalize(core)
    # Persist snapshot
    await faz23.record_snapshot(core)
    # Send result to user
    await update.message.reply_text(
        core.render_html(), parse_mode=ParseMode.HTML
    )


async def cmd_health(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Respond to `/health` with a simple status message."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    await update.message.reply_text(f"OK ✅\nUTC: {now}")


async def cmd_start(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Respond to `/start` or `/help` with usage instructions."""
    msg = (
        "HoopBrain Bot\n"
        "Bu bot maç öncesi analiz ve simülasyon için tasarlanmıştır.\n"
        "Bahis tavsiyesi olarak kullanılmamalıdır.\n\n"
        "<b>Komutlar</b>\n"
        "/start – Yardım ve açıklama\n"
        "/health – Botun sağlık durumunu kontrol et\n"
        "/analyze <lig> | <YYYY-MM-DD> | <EvTakım> - <DepTakım> – Tam analiz raporu\n\n"
        "<b>Örnek:</b>\n"
        "/analyze NBA | 2025-12-25 | Lakers - Warriors"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


def main() -> None:
    """Create the Telegram application, register handlers and run it."""
    # Load the configuration to obtain the bot token.  Engines are
    # initialized in the post_init callback rather than here.
    cfg = load_config()
    application = (
        Application.builder()
        .token(cfg.telegram_bot_token)
        .concurrent_updates(True)
        .post_init(post_init)
        .on_shutdown(on_shutdown)
        .build()
    )
    # Register command handlers
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_start))
    application.add_handler(CommandHandler("health", cmd_health))
    application.add_handler(CommandHandler("analyze", cmd_analyze))
    # Configure logging
    logging.basicConfig(level=logging.INFO)
    log = logging.getLogger("zeynal-bot-core")
    log.info("Bot starting…")
    # Run the bot.  run_polling() is a blocking call.
    application.run_polling(allowed_updates=None, close_loop=False, drop_pending_updates=True)


if __name__ == "__main__":
    main() 

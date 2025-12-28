"""
Main entry point for the HoopBrain Telegram bot.

This module wires together several underlying engines (FAZ13, FAZ16, FAZ17,
FAZ22 and FAZ23) to deliver pre‑match analysis, market enrichment,
Monte Carlo simulations, risk calibration and snapshot persistence.

The original version of this file in the repository contained a number of
problems:

* Top‑level imports were indented, causing a syntax error (`IndentationError`).
* Some lines were concatenated onto one another without proper line breaks,
  which made the file difficult to read and would have prevented it from
  running correctly.
* A placeholder comment suggested that helper functions such as
  ``cmd_analyze``, ``cmd_start`` and ``cmd_health`` would be defined elsewhere.
  For a functioning bot, these handlers need to be implemented in this
  module so that the `telegram.ext.Application` can register them.

This rewritten version corrects the indentation, restores missing newlines
and provides complete implementations of the command handlers. It also
includes comprehensive docstrings and comments to clarify the purpose of
each section.
"""

import logging
import os
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode

from faz13_engine import Faz13Engine, PrematchRequest
from baseline.team_baseline_store import TeamBaselineStore
from faz17_engine import Faz17Engine

# Try importing Faz16Engine from a number of possible module locations.  Some
# deployments of the FAZ‑16 engine package expose `Faz16Engine` directly from
# the top‑level package, while others ship it under ``faz16_engine.faz16_engine``
# or ``faz16_engine.engine``.  We attempt each location in turn and fall back
# to the next if an ``ImportError`` is raised.
try:
    from faz16_engine import Faz16Engine  # type: ignore[attr-defined]
except ImportError:
    try:
        from faz16_engine.faz16_engine import Faz16Engine  # type: ignore[attr-defined]
    except ImportError:
        from faz16_engine.engine import Faz16Engine  # type: ignore[attr-defined]

from faz22_engine import Faz22Engine
from faz23_engine import Faz23Engine

# Set an environment variable to help the FAZ‑13 engine locate its team
# statistics file.  When the bot is launched from different working
# directories (for example when deployed via Docker or in a serverless
# environment), relative paths can break.  By pointing ``TEAM_STATS_FILE``
# at the file sitting next to this module, we guarantee that the engine
# will always find its resource.  ``setdefault`` ensures we do not clobber
# an existing value.
os.environ.setdefault(
    "TEAM_STATS_FILE",
    os.path.join(os.path.dirname(__file__), "team_stats.json"),
)

# Configure logging once at module import time.  Downstream libraries (such as
# python‑telegram‑bot) will inherit this configuration.  We name the logger
# explicitly to make filtering easier when debugging.
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("zeynal-bot-core")


def _env(name: str) -> str:
    """Return the value of a required environment variable.

    If the environment variable is unset or empty, raise a ``RuntimeError``
    explaining which variable is missing.  This avoids the bot starting up
    with incomplete configuration.

    Args:
        name: The name of the environment variable to look up.

    Returns:
        The value of the environment variable.

    Raises:
        RuntimeError: If the variable is not defined or empty.
    """
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return val


async def cmd_analyze(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the ``/analyze`` command.

    Users can request a pre‑match analysis by providing a league, date and
    matchup.  The syntax is ``/analyze <lig> | <YYYY‑MM‑DD> | <EvTakım> - <DepTakım>``.
    If the arguments are malformed or missing, a usage message is sent
    instead.  The analysis pipeline executes several phases:

    1. Run the FAZ‑13 pre‑match core analysis.
    2. Enrich the result with market data via FAZ‑17.
    3. Optionally run a Monte Carlo simulation using FAZ‑16 if it is available.
    4. Calibrate confidence and risk using FAZ‑22.
    5. Persist a snapshot of the analysis with FAZ‑23.

    Finally the rendered HTML result is sent back to the user.
    """
    # Ensure we have some arguments.  Without input, we cannot perform an analysis.
    if not context.args:
        await update.message.reply_text(
            "Kullanım: /analyze <lig> | <YYYY-MM-DD> | <EvTakım> - <DepTakım>"
        )
        return

    try:
        # Rejoin the arguments into a single string and split on the bar (|).
        raw = " ".join(context.args)
        parts = [p.strip() for p in raw.split("|")]
        if len(parts) != 3:
            raise ValueError("Wrong number of arguments")
        league = parts[0]
        date_str = parts[1]
        home, away = [x.strip() for x in parts[2].split("-")]
    except Exception:
        # If parsing fails, send usage information and return early.
        await update.message.reply_text(
            "Kullanım: /analyze <lig> | <YYYY-MM-DD> | <EvTakım> - <DepTakım>"
        )
        return

    # Retrieve engine instances from the bot's shared context.  The ``context``
    # argument holds references to the application instance and therefore
    # ``bot_data``.  Type annotations help static checkers but do not affect
    # runtime behaviour.
    faz13: Faz13Engine = context.application.bot_data["faz13"]
    faz17: Faz17Engine = context.application.bot_data["faz17"]
    faz16: Faz16Engine | None = context.application.bot_data.get("faz16")  # type: ignore[assignment]
    faz22: Faz22Engine = context.application.bot_data["faz22"]
    faz23: Faz23Engine = context.application.bot_data["faz23"]

    # 1) Pre‑match core analysis
    core = await faz13.run_prematch(
        PrematchRequest(0, league, date_str, home, away)
    )

    # 2) Market enrichment
    core = await faz17.enrich_with_market(core)

    # 2.5) Monte Carlo simulation (optional)
    if faz16 is not None:
        core = faz16.run_simulation(core)

    # 3) Confidence & risk calibration
    core = faz22.score_and_finalize(core)

    # 4) Persist snapshot
    await faz23.record_snapshot(core)

    # Send the rendered report back to the user.  Telegram expects HTML
    # entities to be escaped; the engines should provide safe HTML via
    # ``render_html``.
    await update.message.reply_text(
        core.render_html(),
        parse_mode=ParseMode.HTML,
    )


async def cmd_health(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Return a simple health check message.

    Responds with ``OK ✅`` and the current UTC timestamp.  This can be used
    by monitoring systems to ensure the bot is running and responsive.
    """
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    await update.message.reply_text(f"OK ✅\nUTC: {now}")


async def cmd_start(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a help/usage message to the user.

    This command welcomes users to the bot and describes the available
    commands.  It should be registered as both ``/start`` and ``/help``.
    """
    msg = (
        "<b>HoopBrain Bot</b>\n"
        "Bu bot maç öncesi analiz ve simülasyon için tasarlanmıştır.\n"
        "Bahis tavsiyesi olarak kullanılmamalıdır.\n\n"
        "<b>Komutlar</b>\n"
        "/start – Yardım ve açıklama\n"
        "/health – Botun sağlık durumunu kontrol et\n"
        "/analyze <lig> | <YYYY-MM-DD> | <EvTakım> - <DepTakım> – Tam analiz raporu\n"
        "\nÖrnek:\n/analyze NBA | 2025-12-25 | Lakers - Warriors"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


def main() -> None:
    """Program entry point.

    Configure the Telegram application, instantiate engine objects and register
    command handlers.  Once configured, the bot enters the polling loop to
    receive and process updates from Telegram.
    """
    # Load required API keys
    token = _env("TELEGRAM_BOT_TOKEN")
    api_sports_key = _env("API_SPORTS_KEY")
    odds_key = _env("ODDS_API_KEY")

    # Build the Telegram application.  We enable concurrent updates so that
    # multiple commands can be processed in parallel without blocking each other.
    app = (
        Application.builder()
        .token(token)
        .concurrent_updates(True)
        .build()
    )

    # Create engine instances and stash them on the application for later use.
    baseline_dir = os.getenv("BASELINE_DIR", "data/baselines")
    baseline_store = TeamBaselineStore(baseline_dir)
    app.bot_data["faz13"] = Faz13Engine(
        api_sports_key,
        os.getenv("API_SPORTS_BASE", "https://v1.basketball.api-sports.io"),
        baseline_store=baseline_store,
    )
    app.bot_data["faz17"] = Faz17Engine(
        odds_key,
        os.getenv("ODDS_BASE", "https://api.the-odds-api.com/v4"),
    )
    # The FAZ16 engine is optional.  If its import fails, ``Faz16Engine`` will
    # still be defined but may not be functional; the calling code defensively
    # checks for ``None``.  Here we instantiate it unconditionally; if the
    # import failed above this will propagate at startup.
    app.bot_data["faz16"] = Faz16Engine()
    app.bot_data["faz22"] = Faz22Engine()
    app.bot_data["faz23"] = Faz23Engine(
        storage_path=os.getenv("FAZ23_STORAGE", "faz23_storage.sqlite"),
    )

    # Register command handlers.  ``/start`` and ``/help`` share the same
    # implementation.
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("health", cmd_health))
    app.add_handler(CommandHandler("analyze", cmd_analyze))

    log.info("Bot starting…")
    app.run_polling(
        allowed_updates=None,
        close_loop=False,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main() 

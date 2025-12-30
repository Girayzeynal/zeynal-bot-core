"""
Main entry point for zeynal-bot-core.

This file:
- Starts Telegram bot (single instance)
- Starts Dynamic Scheduler in the same event loop
- Initializes FAZ-13, FAZ-16, FAZ-17, FAZ-22, FAZ-23 engines
- Is fully compatible with Fly.io
- Is NOT a demo file
"""

import os
import asyncio
import logging
from typing import Optional

from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)
from telegram.constants import ParseMode

from faz13_engine import Faz13Engine, PrematchRequest
from faz17_engine import Faz17Engine
from faz22_engine import Faz22Engine
from faz23_engine import Faz23Engine
from faz16_engine import faz16_run_simulation
from baseline.team_baseline_store import TeamBaselineStore

# Optional dynamic scheduler (must NOT create a second bot)
try:
    import dynamic_scheduler
except Exception:
    dynamic_scheduler = None


# -------------------------------------------------------------------
# LOGGING
# -------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("zeynal-bot-core")


# -------------------------------------------------------------------
# ENV HELPERS
# -------------------------------------------------------------------
def _env(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return val


# Backward compatibility:
# Some parts still expect TELEGRAM_TOKEN
if "TELEGRAM_TOKEN" not in os.environ and "TELEGRAM_BOT_TOKEN" in os.environ:
    os.environ["TELEGRAM_TOKEN"] = os.environ["TELEGRAM_BOT_TOKEN"]


# -------------------------------------------------------------------
# TELEGRAM COMMANDS
# -------------------------------------------------------------------
async def cmd_analyze(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            "Kullanım:\n/analyze <Lig> | <YYYY-MM-DD> | <EvTakım> - <DepTakım>"
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
            "Kullanım:\n/analyze <Lig> | <YYYY-MM-DD> | <EvTakım> - <DepTakım>"
        )
        return

    faz13: Faz13Engine = context.application.bot_data["faz13"]
    faz17: Faz17Engine = context.application.bot_data["faz17"]
    faz22: Faz22Engine = context.application.bot_data["faz22"]
    faz23: Faz23Engine = context.application.bot_data["faz23"]

    # 1) FAZ-13 core
    core = await faz13.run_prematch(
        PrematchRequest(
            fixture_id=0,
            league=league,
            date_str=date_str,
            home=home,
            away=away,
        )
    )

    # 2) FAZ-17 market enrichment
    core = await faz17.enrich_with_market(core)

    # 3) FAZ-16 simulation (best-effort)
    try:
        base_total = float(getattr(core, "market_total", 180.0))
        vol = float(getattr(core, "market_vol", 15.0))
        sim = faz16_run_simulation(base_total, vol)
        core.faz16_simulation = sim
    except Exception as exc:
        log.exception("FAZ-16 simulation failed: %s", exc)

    # 4) FAZ-22 scoring
    core = faz22.score_and_finalize(core)

    # 5) FAZ-23 snapshot
    await faz23.record_snapshot(core)

    await update.message.reply_text(
        core.render_html(),
        parse_mode=ParseMode.HTML,
    )


async def cmd_health(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("OK ✅")


async def cmd_start(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Zeynal Core AI aktif.\n"
        "/analyze <Lig> | <YYYY-MM-DD> | <EvTakım> - <DepTakım>"
    )


# -------------------------------------------------------------------
# ASYNC STARTUP
# -------------------------------------------------------------------
async def _start_dynamic_scheduler(app: Application) -> None:
    if dynamic_scheduler is None:
        log.info("Dynamic Scheduler not available.")
        return

    if not hasattr(dynamic_scheduler, "scheduler_loop"):
        log.info("Dynamic Scheduler has no scheduler_loop().")
        return

    log.info("🚀 Dynamic Scheduler started.")
    await dynamic_scheduler.scheduler_loop(app)


async def main_async() -> None:
    token = _env("TELEGRAM_BOT_TOKEN")

    app = Application.builder().token(token).build()

    # Baseline store
    baseline_dir = os.getenv("BASELINE_DIR", "data/baselines")
    baseline_store = TeamBaselineStore(baseline_dir)

    # Engines
    app.bot_data["faz13"] = Faz13Engine(
        api_sports_key=_env("API_SPORTS_KEY"),
        api_sports_base=os.getenv(
            "API_SPORTS_BASE",
            "https://v1.basketball.api-sports.io",
        ),
        baseline_store=baseline_store,
    )

    app.bot_data["faz17"] = Faz17Engine(
        odds_api_key=_env("ODDS_API_KEY"),
        odds_base=os.getenv(
            "ODDS_BASE",
            "https://api.the-odds-api.com/v4",
        ),
    )

    app.bot_data["faz22"] = Faz22Engine()

    app.bot_data["faz23"] = Faz23Engine(
        storage_path=os.getenv(
            "FAZ23_STORAGE",
            "faz23_storage.sqlite",
        )
    )

    # Handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("health", cmd_health))
    app.add_handler(CommandHandler("analyze", cmd_analyze))

    # Start app
    await app.initialize()
    await app.start()
    await app.bot.initialize()
    await app.updater.start_polling()

    # Start scheduler (same loop)
    await _start_dynamic_scheduler(app)

    log.info("🤖 Telegram Bot & Scheduler running.")

    await asyncio.Event().wait()


# -------------------------------------------------------------------
# ENTRYPOINT
# -------------------------------------------------------------------
def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main() 

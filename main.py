"""
Main entry point for the HoopBrain Telegram bot.

This module wires together several underlying engines (FAZ13, FAZ16, FAZ17, FAZ22 and FAZ23) to deliver pre-match analysis, market enrichment,
Monte Carlo simulations, risk calibration and snapshot persistence.

FAZ16 was originally expected to provide a Faz16Engine class. However,
the faz16_engine package in this repository does not define such a class
(only faz16_run_simulation exists). To avoid import errors, this version
imports faz16_run_simulation directly and bypasses Faz16Engine altogether.
"""

import logging
import os
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode

from faz13_engine import Faz13Engine, PrematchRequest
from baseline.team_baseline_store import TeamBaselineStore
from faz17_engine import Faz17Engine
from faz16_engine import faz16_run_simulation  # direct import
from faz22_engine import Faz22Engine
from faz23_engine import Faz23Engine

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("zeynal-bot-core")

def _env(name: str) -> str:
    """Fetch a required environment variable, raising a RuntimeError if missing."""
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return val

async def cmd_analyze(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /analyze command and run the full analysis pipeline."""
    if not context.args:
        await update.message.reply_text(
            "Kullanım: /analyze <lig> | <YYYY-MM-DD> | <EvTakım> - <DepTakım>"
        )
        return

    try:
        raw = " ".join(context.args)
        parts = [p.strip() for p in raw.split("|")]
        if len(parts) != 3:
            raise ValueError("Wrong number of arguments")
        league = parts[0]
        date_str = parts[1]
        home, away = [x.strip() for x in parts[2].split("-")]
    except Exception:
        await update.message.reply_text(
            "Kullanım: /analyze <lig> | <YYYY-MM-DD> | <EvTakım> - <DepTakım>"
        )
        return

    faz13: Faz13Engine = context.application.bot_data["faz13"]
    faz17: Faz17Engine = context.application.bot_data["faz17"]
    faz22: Faz22Engine = context.application.bot_data["faz22"]
    faz23: Faz23Engine = context.application.bot_data["faz23"]

    # 1. Core pre-match analysis
    core = await faz13.run_prematch(PrematchRequest(0, league, date_str, home, away))

    # 2. Market enrichment
    core = await faz17.enrich_with_market(core)

    # 3. Run heavy-tailed Monte Carlo simulation via FAZ16
    # Extract baseline stats or set defaults
    try:
        base_total = float(getattr(core, "market_total", 180.0))
        vol = float(getattr(core, "market_vol", 15.0))
        simulation_result = faz16_run_simulation(base_total, vol)
        # Attach simulation summary to core (dict or object)
        if isinstance(core, dict):
            core["faz16_simulation"] = simulation_result
        else:
            core.faz16_simulation = simulation_result
    except Exception as exc:
        log.exception("FAZ16 simulation failed: %s", exc)

    # 4. Score and finalize via FAZ22
    core = faz22.score_and_finalize(core)

    # 5. Persist snapshot via FAZ23
    await faz23.record_snapshot(core)

    await update.message.reply_text(core.render_html(), parse_mode=ParseMode.HTML)

async def cmd_health(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Simple health check endpoint."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    await update.message.reply_text(f"OK ✅\nUTC: {now}")

async def cmd_start(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a help message."""
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
    """Configure engines, register commands, and start polling."""
    token = _env("TELEGRAM_BOT_TOKEN")
    api_sports_key = _env("API_SPORTS_KEY")
    odds_key = _env("ODDS_API_KEY")

    app = (
        Application.builder()
        .token(token)
        .concurrent_updates(True)
        .build()
    )

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
    # No Faz16Engine instance stored; simulation handled via faz16_run_simulation
    app.bot_data["faz22"] = Faz22Engine()
    app.bot_data["faz23"] = Faz23Engine(
        storage_path=os.getenv("FAZ23_STORAGE", "faz23_storage.sqlite"),
    )

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

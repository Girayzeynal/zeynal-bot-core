"""
Entry point for the Zeynal Core bot.

This module wires together the various analysis engines (FAZ‑13, FAZ‑17,
FAZ‑22 and FAZ‑23) and exposes them through a Telegram bot interface.

In earlier versions the engines were constructed in a ``post_init`` callback
and a separate ``on_shutdown`` callback was used to clean up resources.
However, certain versions of ``python‑telegram‑bot`` do not expose an
``on_shutdown`` attribute on the ``ApplicationBuilder``.  To maximise
compatibility this version constructs the engines synchronously in
``main()`` and stores them in the application's ``bot_data`` dictionary.
This approach avoids reliance on unavailable callbacks while still
keeping all engine instances together for easy retrieval.

Configuration is provided via environment variables.  The following
variables are mandatory:

``TELEGRAM_BOT_TOKEN`` – Bot token obtained from BotFather on Telegram.
``API_SPORTS_KEY`` – API key for your sports data provider.
``ODDS_API_KEY`` – API key for The Odds API.

Optional variables:

``API_SPORTS_BASE`` – Base URL for the sports data API (default: https://v1.basketball.api-sports.io)
``ODDS_BASE`` – Base URL for The Odds API (default: https://api.the-odds-api.com/v4)
``FAZ23_STORAGE`` – Path to the SQLite database used by FAZ‑23 (default: faz23_storage.sqlite)
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
    telegram_bot_token: str
    api_sports_key: str
    odds_api_key: str
    api_sports_base: str = "https://v1.basketball.api-sports.io"
    odds_base: str = "https://api.the-odds-api.com/v4"
    faz23_storage: str = "faz23_storage.sqlite"


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def load_config() -> AppConfig:
    return AppConfig(
        telegram_bot_token=_require_env("TELEGRAM_BOT_TOKEN"),
        api_sports_key=_require_env("API_SPORTS_KEY"),
        odds_api_key=_require_env("ODDS_API_KEY"),
        api_sports_base=os.getenv("API_SPORTS_BASE", AppConfig.api_sports_base),
        odds_base=os.getenv("ODDS_BASE", AppConfig.odds_base),
        faz23_storage=os.getenv("FAZ23_STORAGE", AppConfig.faz23_storage),
    )


async def cmd_analyze(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the `/analyze` command.

    Syntax: /analyze <lig> | <YYYY-MM-DD> | <EvTakım> - <DepTakım>
    """
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
        home, away = [s.strip() for s in parts[2].split("-")]
    except Exception:
        await update.message.reply_text(
            "Kullanım: /analyze <lig> | <YYYY-MM-DD> | <EvTakım> - <DepTakım>"
        )
        return

    # Retrieve engines from bot_data (set in main)
    faz13: Faz13Engine = context.application.bot_data["faz13"]
    faz17: Faz17Engine = context.application.bot_data["faz17"]
    faz22: Faz22Engine = context.application.bot_data["faz22"]
    faz23: Faz23Engine = context.application.bot_data["faz23"]

    # If run_prematch isn't defined (older engine), fall back to pre_analyze
    if hasattr(faz13, "run_prematch"):
        core = await faz13.run_prematch(PrematchRequest(0, league, date_str, home, away))
    else:
        # Compute baseline data using pre_analyze
        result = faz13.pre_analyze(league, home, away)
        # Build a minimal Faz13CoreOutput; this mirrors the fields used by FAZ‑22/23
        from faz13_engine import Faz13CoreOutput, FixtureContext
        ctx = FixtureContext(league=league, date=date_str, home=home, away=away)
        # Split bands
        bands = result.get("bands", {})
        total_band = bands.get("ft") or [0, 0]
        home_band = [round(total_band[0] / 2), round(total_band[1] / 2)]
        away_band = home_band.copy()
        meta = result.get("meta", {})
        notes = result.get("notes", [])
        core = Faz13CoreOutput(
            ctx=ctx,
            home_band=home_band,
            away_band=away_band,
            total_band=total_band,
            tempo_flag=result.get("signals", {}).get("tempo_flag", "UNKNOWN"),
            blowout_risk=result.get("signals", {}).get("blowout_risk", "UNKNOWN"),
            ou_direction=result.get("signals", {}).get("alt_ust", "NO_EDGE"),
            meta=meta,
            notes=notes,
            market={},
        )

    core = await faz17.enrich_with_market(core)
    core = faz22.score_and_finalize(core)
    await faz23.record_snapshot(core)
    await update.message.reply_text(core.render_html(), parse_mode=ParseMode.HTML)


async def cmd_health(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    await update.message.reply_text(f"OK ✅\nUTC: {now}")


async def cmd_start(update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
    """Instantiate engines and run the Telegram bot."""
    cfg = load_config()
    app = (
        Application.builder()
        .token(cfg.telegram_bot_token)
        .concurrent_updates(True)
        .build()
    )
    # Instantiate engines; Faz13Engine accepts either TeamStatsAdapter or (key, base_url)
    app.bot_data["faz13"] = Faz13Engine(cfg.api_sports_key, cfg.api_sports_base)
    app.bot_data["faz17"] = Faz17Engine(cfg.odds_api_key, cfg.odds_base)
    app.bot_data["faz22"] = Faz22Engine()
    app.bot_data["faz23"] = Faz23Engine(storage_path=cfg.faz23_storage)
    # Register command handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("health", cmd_health))
    app.add_handler(CommandHandler("analyze", cmd_analyze))
    # Start polling
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("zeynal-bot-core").info("Bot starting…")
    app.run_polling(allowed_updates=None, close_loop=False, drop_pending_updates=True)


if __name__ == "__main__":
    main() 

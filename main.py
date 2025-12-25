"""
Main entrypoint for the basketball analytics Telegram bot.

This script exposes a Telegram webhook via python‑telegram‑bot.  It ties
together several analytical engines:

* Faz13Engine  – computes pre‑match team averages and a predicted points band
  using the API‑Sports basketball API.  It delivers a core prediction and
  identifies potential blowout/tempo risks.
* Faz17Engine  – enriches the prediction with real‑time betting market
  information from The Odds API.  It looks up an event, extracts the
  bookmaker totals and spreads and adjusts the core prediction when a clear
  edge exists.
* Faz22Engine  – scores the prediction for confidence and risk.  It looks
  at band width, blowout flags and market alignment to produce a 0–100
  confidence score and a LOW/MID/HIGH risk label.
* Faz23Engine  – persists snapshots of every prediction in a SQLite DB.  This
  allows for post‑mortem analysis and future calibration of league‑specific
  biases.

Environment variables required:

* TELEGRAM_BOT_TOKEN – Bot token issued by BotFather.
* API_SPORTS_KEY    – API‑Sports (basketball) key for team stats.
* ODDS_API_KEY      – The Odds API key for market data.

Optional environment variables:

* API_SPORTS_BASE – Override base URL for API‑Sports (defaults to
  https://v1.basketball.api-sports.io)
* ODDS_BASE       – Override base URL for The Odds API (defaults to
  https://api.the-odds-api.com/v4)
* FAZ23_STORAGE   – Path to SQLite file used by Faz23Engine

Note: This bot is designed for analysis and simulation.  It does not
constitute betting advice.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from typing import Optional, Tuple

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (Application, CommandHandler, ContextTypes)

from faz13_engine import Faz13Engine, PrematchRequest
from faz17_engine import Faz17Engine
from faz22_engine import Faz22Engine
from faz23_engine import Faz23Engine


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("zeynal-bot-core")


def _env(name: str, default: Optional[str] = None) -> str:
    """Helper to read a required environment variable or raise."""
    value = os.getenv(name, default)
    if value is None or value.strip() == "":
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


@dataclass(frozen=True)
class AppConfig:
    telegram_token: str
    api_sports_key: str
    odds_api_key: str
    api_sports_base: str
    odds_base: str


def load_config() -> AppConfig:
    """Load configuration from environment variables, applying defaults."""
    return AppConfig(
        telegram_token=_env("TELEGRAM_BOT_TOKEN"),
        api_sports_key=_env("API_SPORTS_KEY"),
        odds_api_key=_env("ODDS_API_KEY"),
        api_sports_base=os.getenv(
            "API_SPORTS_BASE", "https://v1.basketball.api-sports.io"
        ).rstrip("/"),
        odds_base=os.getenv(
            "ODDS_BASE", "https://api.the-odds-api.com/v4"
        ).rstrip("/"),
    )


HELP_TEXT = (
    "<b>HoopBrain Bot</b>\n"
    "Bu bot maç öncesi analiz ve simülasyon için tasarlanmıştır.\n"
    "Bahis tavsiyesi olarak kullanılmamalıdır.\n\n"
    "<b>Komutlar</b>\n"
    "/start – Yardım ve açıklama\n"
    "/health – Botun sağlık durumunu kontrol et\n"
    "/analyze <lig> | <YYYY‑MM‑DD> | <EvTakım> - <DepTakım> – Tam analiz raporu\n\n"
    "<b>Örnek</b>\n"
    "/analyze NBA | 2025-12-25 | Lakers - Warriors\n"
)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with help text when the user sends /start or /help."""
    await update.message.reply_text(HELP_TEXT, parse_mode=ParseMode.HTML)


async def cmd_health(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Health check endpoint."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    await update.message.reply_text(f"OK ✅\nUTC: {now}")


def _parse_arguments(text: str) -> Tuple[str, str, str, str]:
    """Parse arguments for the /analyze command.

    Expected format: <league> | <YYYY‑MM‑DD> | <home> - <away>
    Returns a tuple (league, date_str, home, away).  Raises ValueError on
    malformed input.
    """
    parts = [part.strip() for part in text.split("|")]
    if len(parts) != 3:
        raise ValueError(
            "Format hatalı. Örnek: NBA | 2025-12-25 | Lakers - Warriors"
        )
    league = parts[0]
    date_str = parts[1]
    teams = parts[2]
    m = re.match(r"(.+?)\s*-\s*(.+)", teams)
    if not m:
        raise ValueError("Takım ayrıştırılamadı. Örnek: Lakers - Warriors")
    home = m.group(1).strip()
    away = m.group(2).strip()
    return league, date_str, home, away


async def cmd_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Perform full analysis using all engines."""
    if not context.args:
        await update.message.reply_text(
            "Kullanım: /analyze <lig> | <YYYY‑MM‑DD> | <EvTakım> - <DepTakım>"
        )
        return
    try:
        raw = " ".join(context.args)
        league, date_str, home, away = _parse_arguments(raw)
    except ValueError as ve:
        await update.message.reply_text(str(ve))
        return

    engines = context.application.bot_data["engines"]
    faz13: Faz13Engine = engines["faz13"]
    faz17: Faz17Engine = engines["faz17"]
    faz22: Faz22Engine = engines["faz22"]
    faz23: Faz23Engine = engines["faz23"]

    msg = await update.message.reply_text(
        "Analiz başlatılıyor… (gerçek zamanlı veri çekiliyor)"
    )
    try:
        # 1) Core FAZ‑13: compute pre‑match prediction
        req = PrematchRequest(
            fixture_id=0,
            league=league,
            date_str=date_str,
            home=home,
            away=away,
        )
        core = await faz13.run_prematch(req)

        # 2) Market adjust: FAZ‑17 enrich with betting lines
        core = await faz17.enrich_with_market(core)

        # 3) Meta scoring: FAZ‑22 compute confidence and risk
        core = faz22.score_and_finalize(core)

        # 4) Snapshot: FAZ‑23 persist prediction
        await faz23.record_snapshot(core)

        await msg.edit_text(
            core.render_html(),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        log.exception("analysis failed")
        await msg.edit_text(f"Hata: {e!s}")


async def post_init(app: Application) -> None:
    """Initialize engines after the Telegram application is built."""
    cfg: AppConfig = app.bot_data["config"]
    faz13 = Faz13Engine(
        api_sports_key=cfg.api_sports_key, api_sports_base=cfg.api_sports_base
    )
    faz17 = Faz17Engine(
        odds_api_key=cfg.odds_api_key, odds_base=cfg.odds_base
    )
    faz22 = Faz22Engine()
    faz23 = Faz23Engine(
        storage_path=os.getenv("FAZ23_STORAGE", "faz23_storage.sqlite")
    )
    app.bot_data["engines"] = {
        "faz13": faz13,
        "faz17": faz17,
        "faz22": faz22,
        "faz23": faz23,
    }
    log.info("Engines initialized.")


async def on_shutdown(app: Application) -> None:
    """Cleanly close engine sessions on application shutdown."""
    engines = app.bot_data.get("engines", {})
    for eng in engines.values():
        close = getattr(eng, "aclose", None)
        if callable(close):
            try:
                await close()
            except Exception:
                log.exception("engine close failed")


def main() -> None:
    cfg = load_config()
    app = (
        Application.builder()
        .token(cfg.telegram_token)
        .concurrent_updates(True)
        .post_init(post_init)
        .build()
    )
    app.bot_data["config"] = cfg
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("health", cmd_health))
    app.add_handler(CommandHandler("analyze", cmd_analyze))
    log.info("Bot starting…")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        close_loop=False,
        drop_pending_updates=True,
        on_shutdown=on_shutdown,
    )


if __name__ == "__main__":
    main()

# ======================================================
# CLEAN + FIXED MAIN.PY (PROD READY)
# ======================================================

import os
import logging
import html
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ------------------------------------------------------
# ENV
# ------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_SPORTS_KEY = os.getenv("API_SPORTS_KEY")
API_SPORTS_BASE = os.getenv("API_SPORTS_BASE", "https://v1.basketball.api-sports.io")
BALLDONTLIE_API_KEY = os.getenv("BALLDONTLIE_API_KEY")

ODDS_API_KEY = os.getenv("ODDS_API_KEY")
ODDS_API_BASE = os.getenv("ODDS_API_BASE", "https://api.the-odds-api.com")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN eksik")

# ------------------------------------------------------
# LOGGING
# ------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("zeynal-core")

# ------------------------------------------------------
# MODULAR ENGINE IMPORTS (TEK GERÇEK KAYNAK)
# ------------------------------------------------------
from faz13_engine.faz13_engine import Faz13Engine, PrematchRequest
from faz16_engine.faz16_simulation import faz16_run_simulation
from faz17_engine.faz17_engine import Faz17Engine
from faz22_engine.faz22_engine import Faz22Engine
from faz23_engine.faz23_engine import Faz23Engine
from baseline.team_baseline_store import TeamBaselineStore

# ------------------------------------------------------
# /analyze COMMAND
# ------------------------------------------------------
async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()

    try:
        _, params = text.split(" ", 1)
    except ValueError:
        await update.message.reply_text(
            "Kullanım:\n/analyze NBA 2025-12-31 Cleveland Cavaliers vs Phoenix Suns"
        )
        return

    parts = params.split()
    if len(parts) < 4:
        await update.message.reply_text("Eksik parametre.")
        return

    league = parts[0]
    date = parts[1]
    rest = parts[2:]

    if "vs" in [p.lower() for p in rest]:
        idx = [p.lower() for p in rest].index("vs")
        home = " ".join(rest[:idx]).strip()
        away = " ".join(rest[idx + 1:]).strip()
    else:
        mid = len(rest) // 2
        home = " ".join(rest[:mid]).strip()
        away = " ".join(rest[mid:]).strip()

    logger.info(f"ANALYZE {league} {date} {home} vs {away}")

    faz13: Faz13Engine = context.application.bot_data["faz13"]
    faz17: Faz17Engine = context.application.bot_data["faz17"]
    faz22: Faz22Engine = context.application.bot_data["faz22"]
    faz23: Faz23Engine = context.application.bot_data["faz23"]

    # --------------------------------------------------
    # FAZ-13 : PREMATCH CORE
    # --------------------------------------------------
    req = PrematchRequest(
        fixture_id=0,
        league=league,
        date_str=date,
        home=home,
        away=away,
    )

    try:
        core = await faz13.run_prematch(req)
    except Exception as e:
        logger.exception("FAZ-13 error")
        await update.message.reply_text("FAZ-13 hata: " + html.escape(str(e)))
        return

    # --------------------------------------------------
    # FAZ-16 : SIMULATION (FIX #1)
    # --------------------------------------------------
    try:
        base_total = core.home_avg.points_for + core.away_avg.points_for
        vol = (core.home_avg.stdev_hint + core.away_avg.stdev_hint) / 2
        pace = (core.home_avg.pace_hint + core.away_avg.pace_hint) / 2

        simulation = faz16_run_simulation(
            base_total,
            vol,
            pace,
        )

        # simülasyon çıktısını core.meta içine yaz
        core.meta["simulation"] = simulation

    except Exception as e:
        logger.exception("FAZ-16 error")
        simulation = None

    # --------------------------------------------------
    # FAZ-17 : MARKET (FIX #2)
    # --------------------------------------------------
    try:
        # doğru method: enrich_with_market
        await faz17.enrich_with_market(core)
    except Exception as e:
        logger.exception("FAZ-17 error")
        core.market = {
            "status": "NO_MARKET",
            "reason": str(e),
            "total": None,
            "spread_home": None,
            "spread_away": None,
            "bookmaker": None,
        }

    # --------------------------------------------------
    # FAZ-22 : RISK / CONFIDENCE (FIX #3)
    # --------------------------------------------------
    try:
        final_core = faz22.score_and_finalize(core)
    except Exception as e:
        logger.exception("FAZ-22 error")
        await update.message.reply_text("FAZ-22 hata: " + html.escape(str(e)))
        return

    # --------------------------------------------------
    # FAZ-23 : SNAPSHOT
    # --------------------------------------------------
    try:
        await faz23.record_snapshot(final_core)
    except Exception:
        pass  # snapshot opsiyonel

    # --------------------------------------------------
    # OUTPUT
    # --------------------------------------------------
    try:
        msg = final_core.render_html()
    except Exception:
        msg = str(final_core)

    await update.message.reply_text(
        msg,
        disable_web_page_preview=True,
    )

# ------------------------------------------------------
# MAIN
# ------------------------------------------------------
def main():
    baseline_store = TeamBaselineStore()

    faz13 = Faz13Engine(
        api_sports_key=API_SPORTS_KEY,
        api_sports_base=API_SPORTS_BASE,
        baseline_store=baseline_store,
    )

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.bot_data["faz13"] = faz13
    application.bot_data["faz17"] = Faz17Engine(
        ODDS_API_KEY,
        ODDS_API_BASE,
    )
    application.bot_data["faz22"] = Faz22Engine()
    application.bot_data["faz23"] = Faz23Engine()

    application.add_handler(CommandHandler("analyze", analyze_command))

    logger.info("BOT STARTED — CLEAN ARCHITECTURE ACTIVE")
    application.run_polling()

if __name__ == "__main__":
    main() 

import os
import logging
import html
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from baseline.team_baseline_store import TeamBaselineStore
from faz13_engine import Faz13Engine, PrematchRequest
from faz16_engine import faz16_run_simulation
from faz17_engine import Faz17Engine
from faz22_engine import Faz22Engine
from faz23_engine import Faz23Engine

# ----------------------------
# LOGGING
# ----------------------------
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("zeynal-core")

# ----------------------------
# ENV
# ----------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

API_SPORTS_KEY = os.getenv("API_SPORTS_KEY")
API_SPORTS_BASE = os.getenv("API_SPORTS_BASE", "https://v1.basketball.api-sports.io")

BALLDONTLIE_API_KEY = os.getenv("BALLDONTLIE_API_KEY")

ODDS_API_KEY = os.getenv("ODDS_API_KEY")
ODDS_BASE = os.getenv("ODDS_BASE", "https://api.the-odds-api.com/v4")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN")


# ----------------------------
# /analyze
# ----------------------------
async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()

    try:
        _, params = text.split(" ", 1)
    except ValueError:
        await update.message.reply_text("Kullanım: /analyze NBA 2025-12-31 Cleveland Cavaliers vs Phoenix Suns")
        return

    parts = params.split()
    if len(parts) < 4:
        await update.message.reply_text("Eksik parametre.")
        return

    league = parts[0]
    date_str = parts[1]
    rest = parts[2:]

    if "vs" in [p.lower() for p in rest]:
        idx = [p.lower() for p in rest].index("vs")
        home = " ".join(rest[:idx]).strip()
        away = " ".join(rest[idx + 1:]).strip()
    else:
        mid = len(rest) // 2
        home = " ".join(rest[:mid]).strip()
        away = " ".join(rest[mid:]).strip()

    logger.info(f"ANALYZE {league} {date_str} {home} vs {away}")

    faz13: Faz13Engine = context.application.bot_data["faz13"]
    faz17: Faz17Engine = context.application.bot_data["faz17"]
    faz22: Faz22Engine = context.application.bot_data["faz22"]
    faz23: Faz23Engine = context.application.bot_data["faz23"]

    # ----------------------------
    # FAZ-13
    # ----------------------------
    req = PrematchRequest(
        fixture_id=0,
        league=league,
        date_str=date_str,
        home=home,
        away=away,
    )

    try:
        core = await faz13.run_prematch(req)
    except Exception as e:
        logger.exception("FAZ-13 error")
        await update.message.reply_text("FAZ-13 hata: " + html.escape(str(e)))
        return

    # ----------------------------
    # FAZ-17 (market)  ✅ doğru method: enrich_with_market
    # ----------------------------
    try:
        await faz17.enrich_with_market(core)
    except Exception as e:
        logger.exception("FAZ-17 error")
        core.market = {"status": "NO_MARKET", "reason": str(e)}

    # ----------------------------
    # FAZ-16 (simulation)
    # Signature: faz16_run_simulation(base_total, vol, n_iter=..., line=None)
    # ✅ burada n_iter INT veriyoruz, float değil
    # ----------------------------
    try:
        # market_total varsa onu kullan
        line = None
        if isinstance(core.market, dict):
            if isinstance(core.market.get("total"), (int, float)):
                line = float(core.market["total"])

        # base_total: band ortası (daha stabil)
        base_total = (float(core.total_band[0]) + float(core.total_band[1])) / 2.0

        # vol: core içinden türet (stdev ipucu yoksa 15)
        vol = 15.0
        try:
            vol = float((core.home_avg.stdev_hint + core.away_avg.stdev_hint) / 2.0)
        except Exception:
            vol = 15.0

        sim = faz16_run_simulation(
            base_total=base_total,
            vol=vol,
            n_iter=10_000,
            line=line,
        )

        # sim özetini meta + notlara yaz (FAZ-22 bu meta ile de yaşayabilir)
        core.meta["sim_mean"] = sim.get("mean")
        core.meta["sim_std"] = sim.get("std")
        if sim.get("p50") is not None:
            core.notes.append(f"🎲 Sim p50≈{float(sim['p50']):.1f} | mean≈{float(sim['mean']):.1f} | std≈{float(sim['std']):.1f}")

    except Exception as e:
        logger.exception("FAZ-16 error")
        core.notes.append(f"⚠️ FAZ-16 sim hata: {e}")

    # ----------------------------
    # FAZ-22 ✅ doğru imza: score_and_finalize(core)
    # ----------------------------
    try:
        core = faz22.score_and_finalize(core)
    except Exception as e:
        logger.exception("FAZ-22 error")
        await update.message.reply_text("FAZ-22 hata: " + html.escape(str(e)))
        return

    # ----------------------------
    # FAZ-23 snapshot (opsiyonel)
    # ----------------------------
    try:
        await faz23.record_snapshot(core)
    except Exception:
        pass

    # ----------------------------
    # OUTPUT
    # ----------------------------
    try:
        msg = core.render_html()
    except Exception:
        msg = str(core)

    await update.message.reply_text(msg, disable_web_page_preview=True)


def main():
    baseline_store = TeamBaselineStore("data/baselines")

    faz13 = Faz13Engine(
        api_sports_key=API_SPORTS_KEY,
        api_sports_base=API_SPORTS_BASE,
        baseline_store=baseline_store,
        min_baseline_games=6,
    )

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # engines
    app.bot_data["faz13"] = faz13
    app.bot_data["faz17"] = Faz17Engine(ODDS_API_KEY, ODDS_BASE)
    app.bot_data["faz22"] = Faz22Engine()
    app.bot_data["faz23"] = Faz23Engine()

    app.add_handler(CommandHandler("analyze", analyze_command))

    logger.info("BOT STARTED — CLEAN ARCHITECTURE ACTIVE")
    app.run_polling()


if __name__ == "__main__":
    main()

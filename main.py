from __future__ import annotations

import os
import html
import logging
import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Tuple

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from baseline.team_baseline_store import TeamBaselineStore, TeamBaselineBootstrapper
from providers.espn_adapter import ESPNAdapter

from faz13_engine import Faz13Engine, PrematchRequest
from faz22_engine import Faz22Engine
from faz23_engine import Faz23Engine

from aiohttp import web
from dynamic_scheduler import scheduler_loop
from faz17_engine import Faz17Engine

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
    raise RuntimeError("TELEGRAM_BOT_TOKEN missing")
if not API_SPORTS_KEY:
    raise RuntimeError("API_SPORTS_KEY missing")

# ============================
# HELPERS
# ============================
def parse_analyze(text: str) -> Tuple[str, str, str, str]:
    """
    /analyze NBA 2026-01-19 Atlanta Hawks vs Milwaukee Bucks
    """
    parts = text.split()
    if len(parts) < 6:
        raise ValueError("Eksik parametre")

    league = parts[1]
    date_str = parts[2]
    rest = parts[3:]

    lower = [p.lower() for p in rest]
    if "vs" not in lower:
        raise ValueError("'vs' bulunamadi")

    i = lower.index("vs")
    home = " ".join(rest[:i]).strip()
    away = " ".join(rest[i + 1 :]).strip()
    if not home or not away:
        raise ValueError("Ev sahibi ve deplasman takımı zorunludur")
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("Tarih YYYY-MM-DD biçiminde ve geçerli olmalıdır") from exc
    if home.casefold() == away.casefold():
        raise ValueError("Ev sahibi ve deplasman takımları farklı olmalıdır")
    return league, date_str, home, away

# ============================
# TELEGRAM COMMANDS
# ============================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_message:
        await update.effective_message.reply_text(
            "Zeynal Bot Core aktif. Analiz biçimi:\n"
            "/analyze NBA YYYY-MM-DD Ev Sahibi vs Deplasman\n\n"
            "Yeterli doğrulanabilir takım verisi yoksa tahmin üretilmez."
        )

# ============================
# ANALYZE COMMAND
# ============================
async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""

    try:
        league, date_str, home, away = parse_analyze(text)
    except Exception as e:
        await update.message.reply_text(
            f"Parametre hatasi: {html.escape(str(e))}",
            disable_web_page_preview=True,
        )
        return

    faz13: Faz13Engine = context.application.bot_data["faz13"]
    bootstrapper: TeamBaselineBootstrapper = context.application.bot_data["baseline_bootstrapper"]

    # Fail closed: never turn a missing team baseline into a league-average prediction.
    try:
        home_baseline = await bootstrapper.ensure_async(league=league, team_input=home, min_games=6)
        away_baseline = await bootstrapper.ensure_async(league=league, team_input=away, min_games=6)
    except Exception:
        logger.exception("Baseline bootstrap error")
        await update.message.reply_text("Veri sağlayıcısı hatası: analiz oluşturulmadı.")
        return

    now_ts = datetime.now(timezone.utc).timestamp()
    def usable(baseline):
        if baseline is None:
            return False
        try:
            return (int(baseline.n_games) >= 6
                    and 0 <= now_ts - float(baseline.updated_ts) <= 7 * 86400
                    and float(baseline.pts_for) > 0
                    and float(baseline.pts_against) > 0)
        except (ValueError, TypeError, AttributeError):
            return False

    if not (usable(home_baseline) and usable(away_baseline)):
        logger.warning("Insufficient verified baselines: league=%s home=%s away=%s", league, home, away)
        await update.message.reply_text(
            "Yetersiz veya güncelliğini yitirmiş takım verisi. "
            "LEAGUE_AVG yedeğiyle tahmin üretilmedi. "
            "Veri kaynağı ve fikstür doğrulanınca tekrar deneyin."
        )
        return

    try:
        req = PrematchRequest(
            fixture_id=0,
            league=league,
            date_str=date_str,
            home=home,
            away=away,
        )

        # 🔥 DOĞRU ÇAĞRI
        result = await faz13.run_prematch(req)

        await update.message.reply_text(
            result.render_html(),
            disable_web_page_preview=True,
        )

    except Exception as e:
        logger.error("ANALYZE ERROR", exc_info=True)
        await update.message.reply_text(
            f"Analiz hatasi: {html.escape(str(e))}",
            disable_web_page_preview=True,
        )

# ============================
# HEALTH SERVER
# ============================
async def start_health(app: Application):
    web_app = web.Application()

    async def health(_: web.Request):
        return web.json_response({"ok": True})

    web_app.router.add_get("/health", health)

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

# ============================
# BOOT
# ============================
def build_app() -> Application:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    baseline_store = TeamBaselineStore()
    bootstrapper = TeamBaselineBootstrapper(
        store=baseline_store,
        adapters=[ESPNAdapter()],
    )

    faz13 = Faz13Engine(
        api_sports_key=API_SPORTS_KEY,
        api_sports_base=API_SPORTS_BASE,
        baseline_store=baseline_store,
    )

    app.bot_data["baseline_store"] = baseline_store
    app.bot_data["baseline_bootstrapper"] = bootstrapper
    app.bot_data["faz13"] = faz13
    app.bot_data["faz22"] = Faz22Engine()
    app.bot_data["faz23"] = Faz23Engine()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("analyze", analyze_command))
    return app

async def main_async():
    app = build_app()
    await start_health(app)
    await app.initialize()
    await app.bot.delete_webhook(drop_pending_updates=True)
    await app.start()
    await app.updater.start_polling()
    logger.info("Bot polling started")
    engines = {
        "faz13": app.bot_data["faz13"],
        "faz17": Faz17Engine(os.getenv("ODDS_API_KEY"), os.getenv("ODDS_BASE")),
        "faz22": app.bot_data["faz22"],
        "faz23": app.bot_data["faz23"],
    }
    scheduler_task = asyncio.create_task(scheduler_loop(engines), name="scheduler-loop")
    try:
        await scheduler_task
    finally:
        scheduler_task.cancel()
        await asyncio.gather(scheduler_task, return_exceptions=True)
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()

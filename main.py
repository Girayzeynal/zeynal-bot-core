
import logging
import os
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode

from faz13_engine import Faz13Engine, PrematchRequest
from baseline.team_baseline_store import TeamBaselineStore
from faz17_engine import Faz17Engine
# Faz16Engine importu: önce paket kökünden dener, olmazsa alt modüle düşer
try:
    from faz16_engine import Faz16Engine  # type: ignore[attr-defined]
except ImportError:
    from faz16_engine.faz16_engine import Faz16Engine  # type: ignore[attr-defined]
from faz22_engine import Faz22Engine
from faz23_engine import Faz23Engine

os.environ.setdefault(
    "TEAM_STATS_FILE",
    os.path.join(os.path.dirname(__file__), "team_stats.json"),
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("zeynal-bot-core")

def _env(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return val

async def cmd_analyze(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... (komut parametrelerini ayrıştırma kodu değişmedi)

    faz13: Faz13Engine = context.application.bot_data["faz13"]
    faz17: Faz17Engine = context.application.bot_data["faz17"]
    faz16: Faz16Engine | None = context.application.bot_data.get("faz16")  # type: ignore[assignment]
    faz22: Faz22Engine = context.application.bot_data["faz22"]
    faz23: Faz23Engine = context.application.bot_data["faz23"]

    core = await faz13.run_prematch(PrematchRequest(0, league, date_str, home, away))
    core = await faz17.enrich_with_market(core)
    if faz16 is not None:
        core = faz16.run_simulation(core)
    core = faz22.score_and_finalize(core)
    await faz23.record_snapshot(core)
    await update.message.reply_text(core.render_html(), parse_mode=ParseMode.HTML)

# ... (cmd_health, cmd_start fonksiyonları değişmedi)

def main() -> None:
    token = _env("TELEGRAM_BOT_TOKEN")
    api_sports_key = _env("API_SPORTS_KEY")
    odds_key = _env("ODDS_API_KEY")

    app = Application.builder().token(token).concurrent_updates(True).build()

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
    app.bot_data["faz16"] = Faz16Engine()
    app.bot_data["faz22"] = Faz22Engine()
    app.bot_data["faz23"] = Faz23Engine(
        storage_path=os.getenv("FAZ23_STORAGE", "faz23_storage.sqlite")
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("health", cmd_health))
    app.add_handler(CommandHandler("analyze", cmd_analyze))

    log.info("Bot starting…")
    app.run_polling(allowed_updates=None, close_loop=False, drop_pending_updates=True)

if __name__ == "__main__":
    main()

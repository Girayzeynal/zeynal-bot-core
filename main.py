# main.py
import logging
import os
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode

from faz13_engine import Faz13Engine, PrematchRequest
from baseline.team_baseline_store import TeamBaselineStore
from faz17_engine import Faz17Engine
from faz22_engine import Faz22Engine
from faz23_engine import Faz23Engine

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("zeynal-bot-core")

def _env(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return val

# ... (cmd_analyze, cmd_start ve cmd_health fonksiyonları aynı kalır)

def main() -> None:
    token = _env("TELEGRAM_BOT_TOKEN")
    api_sports_key = _env("API_SPORTS_KEY")
    odds_key = _env("ODDS_API_KEY")

    app = (
        Application.builder()
        .token(token)
        .concurrent_updates(True)
        .build()
    )

    # Baseline deposu oluştur. BASELINE_DIR ile özelleştirilebilir.
    baseline_dir = os.getenv("BASELINE_DIR", "data/baselines")
    baseline_store = TeamBaselineStore(baseline_dir)
    app.bot_data["faz13"] = Faz13Engine(
        api_sports_key,
        os.getenv("API_SPORTS_BASE", "https://v1.basketball.api-sports.io"),
        baseline_store=baseline_store,
    )

    app.bot_data["faz17"] = Faz17Engine(
        odds_key,
        os.getenv("ODDS_BASE", "https://api.the-odds-api.com/v4")
    )
    app.bot_data["faz22"] = Faz22Engine()
    app.bot_data["faz23"] = Faz23Engine(
        storage_path=os.getenv("FAZ23_STORAGE", "faz23_storage.sqlite")
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

# main.py
import logging
import os
from telegram.ext import Application, CommandHandler
from telegram.constants import ParseMode

from faz13_engine import Faz13Engine, PrematchRequest
from faz17_engine import Faz17Engine
from faz22_engine import Faz22Engine

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("zeynal-bot-core")

def env(k: str) -> str:
    v = os.getenv(k)
    if not v:
        raise RuntimeError(f"Missing env var: {k}")
    return v

async def analyze(update, context):
    if not context.args:
        await update.message.reply_text("Kullanım: /analyze <lig> | <YYYY-MM-DD> | <EvTakım> - <DepTakım>")
        return
    try:
        raw = " ".join(context.args)
        parts = [p.strip() for p in raw.split("|")]
        if len(parts) != 3:
            raise ValueError
        league, date_str, teams = parts
        home, away = [x.strip() for x in teams.split("-")]
    except Exception:
        await update.message.reply_text("Kullanım: /analyze <lig> | <YYYY-MM-DD> | <EvTakım> - <DepTakım>")
        return

    faz13: Faz13Engine = context.bot_data["faz13"]
    faz17: Faz17Engine = context.bot_data["faz17"]
    faz22: Faz22Engine = context.bot_data["faz22"]

    core = await faz13.run_prematch(PrematchRequest(0, league, date_str, home, away))
    core = await faz17.enrich_with_market(core)
    core = faz22.score_and_finalize(core)

    await update.message.reply_text(core.render_html(), parse_mode=ParseMode.HTML)

def main():
    token = env("TELEGRAM_BOT_TOKEN")
    api_sports_key = env("API_SPORTS_KEY")
    odds_key = env("ODDS_API_KEY")

    app = Application.builder().token(token).build()

    app.bot_data["faz13"] = Faz13Engine(api_sports_key, os.getenv("API_SPORTS_BASE", "https://v1.basketball.api-sports.io"))
    app.bot_data["faz17"] = Faz17Engine(odds_key, os.getenv("ODDS_BASE", "https://api.the-odds-api.com/v4"))
    app.bot_data["faz22"] = Faz22Engine()

    app.add_handler(CommandHandler("analyze", analyze))

    log.info("Bot starting…")
    app.run_polling()

if __name__ == "__main__":
    main()

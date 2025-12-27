import logging
import os
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode

from faz13_engine import Faz13Engine, PrematchRequest
from baseline.team_baseline_store import TeamBaselineStore
from faz17_engine import Faz17Engine
# Faz16Engine importu: önce kökten, sonra eski ve yeni dosyaları dene
try:
    from faz16_engine import Faz16Engine  # type: ignore[attr-defined]
except ImportError:
    try:
        from faz16_engine.faz16_engine import Faz16Engine  # type: ignore[attr-defined]
    except ImportError:
        from faz16_engine.engine import Faz16Engine  # type: ignore[attr-defined]
from faz22_engine import Faz22Engine
from faz23_engine import Faz23Engine

# Takım istatistik dosyasının yolunu sabitle
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
        league, date_str = parts[0], parts[1]
        home, away = [x.strip() for x in parts[2].split("-")]
    except Exception:
        await update.message.reply_text(
            "Kullanım: /analyze <lig> | <YYYY-MM-DD> | <EvTakım> - <DepTakım>"
        )
        return

    faz13: Faz13Engine = context.application.bot_data["faz13"]
    faz17: Faz17Engine = context.application.bot_data["faz17"]
    faz16: Faz16Engine | None = context.application.bot_data.get("faz16")  # type: ignore[assignment]
    faz22: Faz22Engine = context.application.bot_data["faz22"]
    faz23: Faz23Engine = context.application.bot_data["faz23"]

    # 1) Pre-match core analysis
    core = await faz13.run_prematch(PrematchRequest(0, league, date_str, home, away))
    # 2) Market enrichment
    core = await faz17.enrich_with_market(core)
    # 2.5) Optional Monte Carlo simulation
    if faz16 is not None:
        core = faz16.run_simulation(core)
    # 3) Confidence & risk calibration
    core = faz22.score_and_finalize(core)
    # 4) Persist snapshot
    await faz23.record_snapshot(core)
    # Send result
    await update.message.reply_text(core.render_html(), parse_mode=ParseMode.HTML)

async def cmd_health(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    await update.message.reply_text(f"OK ✅\nUTC: {now}")

async def cmd_start(update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
        os.getenv("ODDS_BASE", "https://api.the-odds-api.com/v4")
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

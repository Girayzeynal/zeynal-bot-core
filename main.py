from __future__ import annotations

import os
import html
import logging
import asyncio
from datetime import datetime
from typing import Any, Dict, Tuple

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from baseline.team_baseline_store import TeamBaselineStore, TeamBaselineBootstrapper
from providers.espn_adapter import ESPNAdapter  # SADECE ESPN

from faz13_engine import Faz13Engine, PrematchRequest
from faz17_engine import Faz17Engine  # noqa: F401
from faz22_engine import Faz22Engine
from faz23_engine import Faz23Engine

from aiohttp import web


# ============================
# LOGGING
# ============================
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("zeynal-core")


# ============================
# ENV (Fly-safe)
# ============================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN")

ODDS_API_KEY = os.getenv("ODDS_API_KEY")
ODDS_BASE = os.getenv("ODDS_BASE", "https://api.the-odds-api.com/v4")

PORT = int(os.getenv("PORT", "8080"))

WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # örn: https://<app>.fly.dev
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/telegram")

BASELINE_DIR = os.getenv("BASELINE_DIR", "data/baselines")
FAZ23_STORAGE = os.getenv("FAZ23_STORAGE", "faz23_storage.sqlite")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN (or BOT_TOKEN)")


# ============================
# HELPERS
# ============================
def _parse_date(date_str: str) -> datetime:
    return datetime.strptime(date_str.strip(), "%Y-%m-%d")


def nba_season_string(date_str: str) -> Tuple[int, str]:
    d = _parse_date(date_str)
    start = d.year if d.month >= 10 else d.year - 1
    return start, f"{start}-{start + 1}"


def _ensure_dict(obj: Any, name: str) -> Dict[str, Any]:
    v = getattr(obj, name, None)
    if isinstance(v, dict):
        return v
    d: Dict[str, Any] = {}
    setattr(obj, name, d)
    return d


def _ensure_list(obj: Any, name: str) -> list:
    v = getattr(obj, name, None)
    if isinstance(v, list):
        return v
    lst: list = []
    setattr(obj, name, lst)
    return lst


def _inject_season(core: Any, league: str, date_str: str) -> None:
    meta = _ensure_dict(core, "meta")
    notes = _ensure_list(core, "notes")

    if league.upper() == "NBA":
        season_start, season_str = nba_season_string(date_str)
    else:
        d = _parse_date(date_str)
        season_start = d.year
        season_str = str(d.year)

    meta["season"] = season_start
    meta["season_str"] = season_str

    notes[:] = [n for n in notes if not str(n).lower().startswith("season:")]
    notes.insert(0, f"Season: {season_str}")


def _apply_degraded_mode(core: Any) -> None:
    meta = _ensure_dict(core, "meta")
    notes = _ensure_list(core, "notes")

    cov = meta.get("data_coverage") or {}
    if isinstance(cov, dict) and any(bool(v) for v in cov.values()):
        return

    meta["degraded_mode"] = True
    meta.setdefault("risk", "HIGH")
    notes.append("WARNING: DEGRADED_MODE - Kaynak veriler eksik.")


def _parse_analyze_params(raw: str) -> Tuple[str, str, str, str]:
    parts = raw.split()
    if len(parts) < 4:
        raise ValueError("Eksik parametre: /analyze <Lig> <Tarih> <Ev Sahibi> vs <Deplasman>")

    league = parts[0]
    date_str = parts[1]
    rest = parts[2:]

    lower = [p.lower() for p in rest]
    if "vs" in lower:
        i = lower.index("vs")
        home = " ".join(rest[:i])
        away = " ".join(rest[i + 1 :])
    else:
        mid = len(rest) // 2
        home = " ".join(rest[:mid])
        away = " ".join(rest[mid:])

    return league, date_str, home.strip(), away.strip()


def _format_notes(notes: Any, limit: int = 8) -> str:
    if not notes:
        return "Not found"
    if isinstance(notes, list):
        sliced = notes[:limit]
        return "\n".join(f"- {str(n)}" for n in sliced)
    return str(notes)


# ============================
# /health HTTP server (Fly)
# ============================
async def _health_app(application: Application) -> web.Application:
    app = web.Application()

    async def health(_: web.Request) -> web.Response:
        ok = True
        missing = []
        for k in ("faz13", "baseline_store", "baseline_bootstrapper"):
            if k not in application.bot_data:
                ok = False
                missing.append(k)

        payload = {
            "ok": ok,
            "missing": missing,
            "baseline_dir": BASELINE_DIR,
            "faz23_storage": FAZ23_STORAGE,
        }
        return web.json_response(payload)

    app.router.add_get("/health", health)
    app.router.add_get("/", health)
    return app


async def _run_health_server(application: Application) -> web.AppRunner:
    app = await _health_app(application)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=PORT)
    await site.start()
    logger.info(f"Health server listening on 0.0.0.0:{PORT}")
    return runner


# ============================
# /analyze
# ============================
async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()

    if not text or len(text.split()) < 4:
        await update.message.reply_text(
            "Kullanim: /analyze NBA 2026-01-04 Brooklyn Nets vs Denver Nuggets\n"
            "Lutfen tum parametreleri dogru girdiginizden emin olun.",
            disable_web_page_preview=True,
        )
        return

    try:
        _, params = text.split(" ", 1)
        league, date_str, home_raw, away_raw = _parse_analyze_params(params)
    except Exception as e:
        await update.message.reply_text(
            f"Parametre hatasi: {html.escape(str(e))}\n"
            "Ornek: /analyze NBA 2026-01-04 Brooklyn Nets vs Denver Nuggets",
            disable_web_page_preview=True,
        )
        return

    try:
        faz13: Faz13Engine = context.application.bot_data["faz13"]
    except KeyError as e:
        await update.message.reply_text(
            f"Sistem hatasi: Bot verileri eksik. {html.escape(str(e))}\n"
            "Lutfen botu yeniden baslatin.",
            disable_web_page_preview=True,
        )
        logger.error(f"Bot data eksik: {e}")
        return

    try:
        season_str = nba_season_string(date_str)[1] if league.upper() == "NBA" else str(_parse_date(date_str).year)

        request = PrematchRequest(
            league=league,
            date=date_str,
            home=home_raw,
            away=away_raw,
            season_str=season_str,
        )

        # blocking analyze -> thread'e al (event-loop kilitlenmesin)
        result = await asyncio.to_thread(faz13.analyze, request)

        _inject_season(result, league, date_str)
        _apply_degraded_mode(result)

        await update.message.reply_text(
            f"OK: {home_raw} vs {away_raw} icin analiz tamamlandi.\n"
            f"Sezon: {result.meta.get('season_str', 'Bilinmiyor')}\n"
            f"Risk: {result.meta.get('risk', 'NORMAL')}\n"
            f"Notlar:\n{_format_notes(getattr(result, 'notes', None))}",
            disable_web_page_preview=True,
        )

    except Exception as e:
        await update.message.reply_text(
            f"Analiz sirasinda hata olustu: {html.escape(str(e))}",
            disable_web_page_preview=True,
        )
        logger.error(f"Analiz hatasi: {e}", exc_info=True)


# ============================
# BOOTSTRAP
# ============================
def _build_application() -> Application:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Baseline
    baseline_store = TeamBaselineStore()
    bootstrapper = TeamBaselineBootstrapper(store=baseline_store, adapters=[])

    application.bot_data["baseline_store"] = baseline_store
    application.bot_data["baseline_bootstrapper"] = bootstrapper

    logger.info(f"BASELINE_DIR={BASELINE_DIR}")
    logger.info(f"FAZ23_STORAGE={FAZ23_STORAGE}")
    logger.info(f"ODDS_BASE={ODDS_BASE}")
    logger.info(f"ODDS_API_KEY={'SET' if bool(ODDS_API_KEY) else 'MISSING'}")

    # Adapter: ODDS_API_KEY yoksa ekleme (patlatma)
    if ODDS_API_KEY:
        if not hasattr(bootstrapper, "adapters") or bootstrapper.adapters is None:
            bootstrapper.adapters = []
        try:
            adapter = ESPNAdapter()  # imza uyumlu: parametresiz
            bootstrapper.adapters.append(adapter)
            logger.info("ESPNAdapter loaded successfully")
        except Exception as e:
            logger.warning(f"ESPNAdapter disabled: {e}")
    else:
        logger.warning("ODDS_API_KEY missing -> ESPNAdapter disabled (degraded mode likely)")

    # Engines
    application.bot_data["faz13"] = Faz13Engine(baseline_store=baseline_store)
    application.bot_data["faz17"] = Faz17Engine()
    application.bot_data["faz22"] = Faz22Engine()
    application.bot_data["faz23"] = Faz23Engine()

    application.add_handler(CommandHandler("analyze", analyze_command))
    return application


async def _run_polling_with_health(application: Application) -> None:
    runner = await _run_health_server(application)
    try:
        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        logger.info("Bot polling started.")
        await asyncio.Event().wait()
    finally:
        try:
            await application.updater.stop()
        except Exception:
            pass
        try:
            await application.stop()
        except Exception:
            pass
        try:
            await application.shutdown()
        except Exception:
            pass
        await runner.cleanup()


def main() -> None:
    application = _build_application()

    if WEBHOOK_URL:
        logger.info(f"Starting in WEBHOOK mode on port {PORT} path={WEBHOOK_PATH}")
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=WEBHOOK_PATH.lstrip("/"),
            webhook_url=WEBHOOK_URL.rstrip("/") + WEBHOOK_PATH,
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        logger.info(f"Starting in POLLING+HEALTH mode on port {PORT}")
        asyncio.run(_run_polling_with_health(application))


if __name__ == "__main__":
    main()

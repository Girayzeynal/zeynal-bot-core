from __future__ import annotations

import os
import html
import logging
import asyncio
import inspect
from datetime import datetime
from typing import Any, Dict, Tuple, Optional

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from baseline.team_baseline_store import TeamBaselineStore, TeamBaselineBootstrapper
from providers.espn_adapter import ESPNAdapter

import faz13_engine  # Faz13Engine + PrematchRequest buradan okunacak
from faz17_engine import Faz17Engine
from faz22_engine import Faz22Engine
from faz23_engine import Faz23Engine


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
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN (or BOT_TOKEN)")

API_SPORTS_KEY = os.getenv("API_SPORTS_KEY") or os.getenv("API_SPORTS_API_KEY")
API_SPORTS_BASE = os.getenv("API_SPORTS_BASE", "https://v1.basketball.api-sports.io")

ODDS_API_KEY = os.getenv("ODDS_API_KEY")
ODDS_BASE = os.getenv("ODDS_BASE", "https://api.the-odds-api.com/v4")

BASELINE_DIR = os.getenv("BASELINE_DIR", "data/baselines")
FAZ23_STORAGE = os.getenv("FAZ23_STORAGE", "faz23_storage.sqlite")


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
    try:
        setattr(obj, name, d)
    except Exception:
        pass
    return d


def _ensure_list(obj: Any, name: str) -> list:
    v = getattr(obj, name, None)
    if isinstance(v, list):
        return v
    lst: list = []
    try:
        setattr(obj, name, lst)
    except Exception:
        pass
    return lst


def _inject_season(core: Any, league: str, date_str: str) -> None:
    meta = _ensure_dict(core, "meta")
    notes = _ensure_list(core, "notes")

    if league.upper() == "NBA":
        _, season_str = nba_season_string(date_str)
    else:
        season_str = str(_parse_date(date_str).year)

    meta["season_str"] = season_str
    # eski season notlarını temizle
    notes[:] = [n for n in notes if not str(n).lower().startswith("season:")]
    notes.insert(0, f"Season: {season_str}")


def _apply_degraded_mode(core: Any) -> None:
    meta = _ensure_dict(core, "meta")
    notes = _ensure_list(core, "notes")
    meta.setdefault("risk", "HIGH")
    if "WARNING: DEGRADED_MODE" not in " ".join(str(x) for x in notes):
        notes.append("WARNING: DEGRADED_MODE - Kaynak veriler eksik.")


def _format_notes(notes: Any, limit: int = 8) -> str:
    if not notes:
        return "Not yok"
    if isinstance(notes, list):
        return "\n".join(f"- {str(n)}" for n in notes[:limit])
    return str(notes)


def _parse_analyze_params(raw: str) -> Tuple[str, str, str, str]:
    """
    /analyze <LIG> <YYYY-MM-DD> <EV> vs <DEP>
    Çok kelimeli takım adlarına dayanıklı parse.
    """
    raw = raw.strip()
    parts = raw.split(maxsplit=2)
    if len(parts) < 3:
        raise ValueError("Eksik parametre")

    league = parts[0]
    date_str = parts[1]
    teams_part = parts[2]

    lower = teams_part.lower()
    sep = " vs "
    if sep not in lower:
        raise ValueError("Takımlar 'vs' ile ayrılmalı")

    i = lower.index(sep)
    home = teams_part[:i].strip()
    away = teams_part[i + len(sep):].strip()

    if not home or not away:
        raise ValueError("Ev veya deplasman boş olamaz")

    return league, date_str, home, away


# ============================
# FAZ13 REFLECTION LAYER
# ============================
def _build_faz13_engine(baseline_store: TeamBaselineStore, bootstrapper: TeamBaselineBootstrapper):
    Faz13Engine = getattr(faz13_engine, "Faz13Engine")
    sig = inspect.signature(Faz13Engine.__init__)
    kwargs: Dict[str, Any] = {}

    # Sadece imzada olanları gönder
    if "api_sports_key" in sig.parameters:
        kwargs["api_sports_key"] = API_SPORTS_KEY
    if "api_sports_base" in sig.parameters:
        kwargs["api_sports_base"] = API_SPORTS_BASE
    if "baseline_store" in sig.parameters:
        kwargs["baseline_store"] = baseline_store
    if "bootstrapper" in sig.parameters:
        kwargs["bootstrapper"] = bootstrapper

    # Eksik zorunlu parametre varsa net uyarı
    for pname, p in sig.parameters.items():
        if pname == "self":
            continue
        if p.default is inspect._empty and pname not in kwargs:
            raise RuntimeError(f"Faz13Engine init missing required param: {pname}")

    return Faz13Engine(**kwargs)


def _build_prematch_request(league: str, date_str: str, home: str, away: str):
    PrematchRequest = getattr(faz13_engine, "PrematchRequest")
    sig = inspect.signature(PrematchRequest)
    args = []
    for pname, p in sig.parameters.items():
        # positional-only gibi davran; isimlere göre map
        if pname in ("fixture_id", "fixture", "id"):
            args.append(0)
        elif pname == "league":
            args.append(league)
        elif pname in ("date_str", "date", "date_utc"):
            args.append(date_str)
        elif pname in ("home", "home_team"):
            args.append(home)
        elif pname in ("away", "away_team"):
            args.append(away)
        else:
            # bilinmeyen zorunluysa None verip patlamayı mesajla göstereceğiz
            args.append(None)
    return PrematchRequest(*args)


async def _call_faz13(faz13: Any, req: Any):
    """
    FAZ13 bazen async, bazen sync; bazen callable, bazen run_prematch.
    Hepsini otomatik çözer.
    """
    # 1) method seç
    fn = None
    if hasattr(faz13, "run_prematch"):
        fn = faz13.run_prematch
    elif hasattr(faz13, "analyze"):
        fn = faz13.analyze
    elif callable(faz13):
        fn = faz13
    else:
        raise RuntimeError("Faz13Engine: callable / run_prematch / analyze bulunamadı")

    # 2) async mi?
    if inspect.iscoroutinefunction(fn):
        res = fn(req)
        return await res

    # 3) sync gibi çağır ama coroutine dönerse await et
    res = await asyncio.to_thread(fn, req)
    if asyncio.iscoroutine(res):
        return await res
    return res


# ============================
# /analyze
# ============================
async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()

    if not text or len(text.split()) < 4:
        await update.message.reply_text(
            "Kullanim:\n/analyze <LIG> <YYYY-MM-DD> <EV_SAHIBI> vs <DEPLASMAN>",
            disable_web_page_preview=True,
        )
        return

    try:
        _, params = text.split(" ", 1)
        league, date_str, home_raw, away_raw = _parse_analyze_params(params)
    except Exception as e:
        await update.message.reply_text(
            f"Parametre hatasi: {html.escape(str(e))}\n"
            "Format:\n/analyze <LIG> <YYYY-MM-DD> <EV_SAHIBI> vs <DEPLASMAN>",
            disable_web_page_preview=True,
        )
        return

    try:
        faz13 = context.application.bot_data["faz13"]
    except KeyError:
        await update.message.reply_text("Sistem hatasi: faz13 yuklu degil.", disable_web_page_preview=True)
        return

    try:
        req = _build_prematch_request(league, date_str, home_raw, away_raw)
        result = await _call_faz13(faz13, req)

        _inject_season(result, league, date_str)

        meta = getattr(result, "meta", {})
        notes = getattr(result, "notes", [])

        await update.message.reply_text(
            f"OK: analiz tamamlandi.\n"
            f"Sezon: {meta.get('season_str','Bilinmiyor')}\n"
            f"Risk: {meta.get('risk','NORMAL')}\n"
            f"Notlar:\n{_format_notes(notes)}",
            disable_web_page_preview=True,
        )

    except Exception as e:
        logger.error("ANALYZE ERROR", exc_info=True)
        await update.message.reply_text(
            f"Analiz hatasi: {html.escape(str(e))}",
            disable_web_page_preview=True,
        )


# ============================
# BOOTSTRAP
# ============================
def _build_application() -> Application:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    baseline_store = TeamBaselineStore(base_dir=BASELINE_DIR)
    bootstrapper = TeamBaselineBootstrapper(store=baseline_store, adapters=[])

    if ODDS_API_KEY:
        try:
            bootstrapper.adapters.append(ESPNAdapter())
            logger.info("ESPNAdapter loaded")
        except Exception as e:
            logger.warning(f"ESPNAdapter disabled: {e}")
    else:
        logger.warning("ODDS_API_KEY missing -> ESPNAdapter disabled")

    application.bot_data["baseline_store"] = baseline_store
    application.bot_data["baseline_bootstrapper"] = bootstrapper

    # FAZ13 init (reflection)
    application.bot_data["faz13"] = _build_faz13_engine(baseline_store, bootstrapper)

    application.bot_data["faz17"] = Faz17Engine()
    application.bot_data["faz22"] = Faz22Engine()
    application.bot_data["faz23"] = Faz23Engine()

    application.add_handler(CommandHandler("analyze", analyze_command))
    return application


def main() -> None:
    app = _build_application()
    logger.info("Starting bot in POLLING mode")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

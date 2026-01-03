from __future__ import annotations

import os
import html
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from baseline.team_baseline_store import TeamBaselineStore
from faz13_engine import Faz13Engine, PrematchRequest
from faz17_engine import Faz17Engine, MarketRequest
from faz22_engine import Faz22Engine
from faz23_engine import Faz23Engine
from faz7_engine.faz7_memory import faz7_memory


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
ODDS_API_KEY = os.getenv("ODDS_API_KEY")
ODDS_BASE = os.getenv("ODDS_BASE", "https://api.the-odds-api.com/v4")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN")


# ============================
# HELPERS
# ============================
def _parse_date(date_str: str) -> datetime:
    return datetime.strptime(date_str.strip(), "%Y-%m-%d")


def nba_season_string(date_str: str) -> tuple[int, str]:
    d = _parse_date(date_str)
    start = d.year if d.month >= 10 else d.year - 1
    return start, f"{start}–{start + 1}"


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


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(str(v).replace(",", ".").strip())
    except Exception:
        return None


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
    if any(bool(v) for v in cov.values()):
        return

    meta["degraded_mode"] = True
    meta.setdefault("risk", "HIGH")
    notes.append(
        "⚠️ DEGRADED_MODE: Kaynak veriler eksik. Analiz fallback ile üretildi."
    )


def _parse_analyze_params(raw: str) -> tuple[str, str, str, str]:
    parts = raw.split()
    if len(parts) < 4:
        raise ValueError("Eksik parametre")

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


# ============================
# /analyze
# ============================
async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()

    try:
        _, params = text.split(" ", 1)
        league, date_str, home, away = _parse_analyze_params(params)
    except Exception as e:
        await update.message.reply_text(
            "Kullanım: /analyze NBA 2026-01-02 Brooklyn Nets vs Houston Rockets\n"
            f"Hata: {html.escape(str(e))}"
        )
        return

    logger.info(f"ANALYZE {league} {date_str} {home} vs {away}")

    faz13: Faz13Engine = context.application.bot_data["faz13"]
    faz17: Faz17Engine = context.application.bot_data["faz17"]
    faz22: Faz22Engine = context.application.bot_data["faz22"]
    faz23: Faz23Engine = context.application.bot_data["faz23"]

    # ============================
    # FAZ-13 — ANALYTIC PREMATCH
    # ============================
    core = await faz13.run_prematch(
        PrematchRequest(0, league, date_str, home, away)
    )

    _inject_season(core, league, date_str)

    meta = _ensure_dict(core, "meta")
    notes = _ensure_list(core, "notes")
    cov = meta.setdefault("data_coverage", {})
    cov["prematch"] = True

    # ============================
    # FAZ-17 — MARKET
    # ============================
    market_total: Optional[float] = None

    try:
        mk = await faz17.fetch_market(
            MarketRequest(
                league=league,
                date_str=date_str,
                home=home,
                away=away,
            )
        )
        if isinstance(mk, dict):
            core.market = mk
            market_total = _safe_float(mk.get("total"))
    except Exception as e:
        core.market = {
            "status": "MARKET_OPTIONAL",
            "total": None,
            "reason": f"FAZ17_EXCEPTION:{e}",
        }

    meta["market_total"] = market_total
    cov["market"] = market_total is not None

    if market_total is not None:
        notes.append(f"Market total={market_total:.1f}")
    else:
        notes.append("Market unavailable → MARKET_OPTIONAL")

    # ============================
    # FAZ-7 — MEMORY TRACE
    # ============================
    try:
        faz7_memory(meta)
    except Exception:
        pass

    # ============================
    # DEGRADED MODE
    # ============================
    _apply_degraded_mode(core)

    # ============================
    # FAZ-22 — FINAL SCORE / CONFIDENCE
    # ============================
    core = faz22.score_and_finalize(core)

    # ============================
    # FAZ-23 — SNAPSHOT
    # ============================
    try:
        await faz23.record_snapshot(core)
    except Exception:
        pass

    # ============================
    # OUTPUT
    # ============================
    await update.message.reply_text(
        core.render_html(),
        disable_web_page_preview=True,
    )


# ============================
# MAIN
# ============================
def main():
    baseline_store = TeamBaselineStore("data/baselines")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # ---- engines
    app.bot_data["faz13"] = Faz13Engine(
        baseline_store=baseline_store,
    )
    app.bot_data["faz17"] = Faz17Engine(
        api_key=ODDS_API_KEY,
        base_url=ODDS_BASE,
    )
    app.bot_data["faz22"] = Faz22Engine()
    app.bot_data["faz23"] = Faz23Engine()

    # ---- handlers
    app.add_handler(CommandHandler("analyze", analyze_command))

    # ---- GRACEFUL SHUTDOWN (Telegram v20+ SAFE)
    async def _graceful_shutdown(application: Application):
        logger.info("Graceful shutdown initiated")

        try:
            faz13 = application.bot_data.get("faz13")
            if faz13:
                await faz13.aclose()
        except Exception as e:
            logger.warning(f"FAZ13 shutdown error: {e}")

        try:
            faz17 = application.bot_data.get("faz17")
            if faz17:
                await faz17.aclose()
        except Exception as e:
            logger.warning(f"FAZ17 shutdown error: {e}")

    # Telegram v20+ uyumlu
    app.shutdown = _graceful_shutdown

    logger.info("BOT STARTED — ANALYTIC CORE ACTIVE (FAZ-13/17/22/23)")
    app.run_polling()


if __name__ == "__main__":
    main() 

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
from faz16_engine import faz16_run_simulation
from faz17_engine import Faz17Engine, MarketRequest
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
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_SPORTS_KEY = os.getenv("API_SPORTS_KEY")
API_SPORTS_BASE = os.getenv("API_SPORTS_BASE", "https://v1.basketball.api-sports.io")
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
    try:
        return float(str(v).replace(",", "."))
    except Exception:
        return None


def _inject_season(core: Any, league: str, date_str: str) -> None:
    meta = _ensure_dict(core, "meta")
    notes = _ensure_list(core, "notes")

    if league.upper() == "NBA":
        s, sstr = nba_season_string(date_str)
    else:
        d = _parse_date(date_str)
        s, sstr = d.year, str(d.year)

    meta["season"] = s
    meta["season_str"] = sstr

    notes[:] = [n for n in notes if not str(n).lower().startswith("season:")]
    notes.insert(0, f"Season: {sstr}")


# ============================
# /analyze
# ============================
async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()

    try:
        _, params = text.split(" ", 1)
        parts = params.split()
        league, date_str = parts[0], parts[1]
        rest = parts[2:]
        i = rest.index("vs")
        home = " ".join(rest[:i])
        away = " ".join(rest[i + 1 :])
    except Exception as e:
        await update.message.reply_text(
            "Kullanım: /analyze NBA 2026-01-02 Team A vs Team B\n"
            f"Hata: {html.escape(str(e))}"
        )
        return

    faz13: Faz13Engine = context.application.bot_data["faz13"]
    faz17: Faz17Engine = context.application.bot_data["faz17"]
    faz22: Faz22Engine = context.application.bot_data["faz22"]
    faz23: Faz23Engine = context.application.bot_data["faz23"]

    # ---------------- FAZ-13 ----------------
    core = await faz13.run_prematch(
        PrematchRequest(0, league, date_str, home, away)
    )
    _inject_season(core, league, date_str)

    meta = _ensure_dict(core, "meta")
    notes = _ensure_list(core, "notes")
    cov = meta.setdefault("data_coverage", {})

    # ---------------- FAZ-17 MARKET (FIXED) ----------------
    market_total = None
    try:
        m = await faz17.fetch_market_total(
            MarketRequest(league, date_str, home, away)
        )
        core.market = m or {}
        market_total = _safe_float(m.get("total")) if isinstance(m, dict) else None
    except Exception as e:
        core.market = {"status": "MARKET_OPTIONAL", "reason": str(e)}

    meta["market_total"] = market_total
    cov["market"] = market_total is not None

    if market_total:
        notes.append(f"Market total={market_total:.1f}")
    else:
        notes.append("Market unavailable → MARKET_OPTIONAL")

    # ---------------- FAZ-16 SIM ----------------
    base_total = (core.total_band[0] + core.total_band[1]) / 2
    sim = faz16_run_simulation(
        base_total=base_total,
        vol=15.0,
        n_iter=10_000,
        line=market_total,
    )
    meta["sim_mean"] = sim.get("mean")
    meta["sim_std"] = sim.get("std")

    if sim.get("p50"):
        notes.append(
            f"🎲 Sim p50≈{sim['p50']:.1f} | mean≈{sim['mean']:.1f} | std≈{sim['std']:.1f}"
        )

    # ---------------- FAZ-22 ----------------
    core = faz22.score_and_finalize(core)

    # ---------------- FAZ-23 ----------------
    try:
        await faz23.record_snapshot(core)
    except Exception:
        pass

    await update.message.reply_text(
        core.render_html(),
        disable_web_page_preview=True,
    )


# ============================
# MAIN
# ============================
def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.bot_data["faz13"] = Faz13Engine(
        api_sports_key=API_SPORTS_KEY,
        api_sports_base=API_SPORTS_BASE,
        baseline_store=TeamBaselineStore("data/baselines"),
    )
    app.bot_data["faz17"] = Faz17Engine(
        api_key=ODDS_API_KEY,
        base_url=ODDS_BASE,
    )
    app.bot_data["faz22"] = Faz22Engine()
    app.bot_data["faz23"] = Faz23Engine()

    app.add_handler(CommandHandler("analyze", analyze_command))
    logger.info("BOT STARTED — MARKET REQUEST FIXED")
    app.run_polling()


if __name__ == "__main__":
    main()  

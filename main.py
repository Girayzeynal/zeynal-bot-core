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
        "⚠️ DEGRADED_MODE: Kaynak veriler eksik (team_stats / pace / market). Analiz fallback ile üretildi."
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
    # FAZ-13
    # ============================
    core = await faz13.run_prematch(
        PrematchRequest(0, league, date_str, home, away)
    )

    _inject_season(core, league, date_str)

    meta = _ensure_dict(core, "meta")
    notes = _ensure_list(core, "notes")
    cov = meta.setdefault("data_coverage", {})

    # ============================
    # FAZ-17 — MARKET (DICT MODE)
    # ============================
    market: Dict[str, Any] = {}
    market_total: Optional[float] = None

    try:
        m = await faz17.fetch_market_total({
            "league": league,
            "date_str": date_str,
            "home": home,
            "away": away,
        })
        if isinstance(m, dict):
            market = m
            market_total = _safe_float(m.get("total"))
    except Exception as e:
        market = {"status": "MARKET_OPTIONAL", "reason": str(e)}

    core.market = market
    meta["market_total"] = market_total
    cov["market"] = market_total is not None

    if market_total is not None:
        notes.append(f"Market total={market_total:.1f}")
    else:
        notes.append("Market unavailable → MARKET_OPTIONAL")

    # ============================
    # FAZ-16 — SIMULATION
    # ============================
    try:
        base_total = (
            (core.total_band[0] + core.total_band[1]) / 2
            if core.total_band
            else 220.0
        )

        sim = faz16_run_simulation(
            base_total=base_total,
            vol=15.0,
            n_iter=10_000,
            line=market_total,
        )

        meta["sim_mean"] = sim.get("mean")
        meta["sim_std"] = sim.get("std")

        if sim.get("p50") is not None:
            notes.append(
                f"🎲 Sim p50≈{sim['p50']:.1f} | mean≈{sim['mean']:.1f} | std≈{sim['std']:.1f}"
            )
    except Exception as e:
        notes.append(f"⚠️ FAZ-16 sim hata: {e}")

    # ============================
    # DEGRADED MODE
    # ============================
    _apply_degraded_mode(core)

    # ============================
    # FAZ-22 FINALIZE
    # ============================
    core = faz22.score_and_finalize(core)

    # ============================
    # FAZ-23 SNAPSHOT
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

    app.bot_data["faz13"] = Faz13Engine(
        api_sports_key=API_SPORTS_KEY,
        api_sports_base=API_SPORTS_BASE,
        baseline_store=baseline_store,
    )
    app.bot_data["faz17"] = Faz17Engine(
        api_key=ODDS_API_KEY,
        base_url=ODDS_BASE,
    )
    app.bot_data["faz22"] = Faz22Engine()
    app.bot_data["faz23"] = Faz23Engine()

    app.add_handler(CommandHandler("analyze", analyze_command))

    logger.info("BOT STARTED — MAIN PIPELINE STABLE (NO MarketRequest)")
    app.run_polling()


if __name__ == "__main__":
    main() 

from __future__ import annotations

import os
import re
import html
import logging
import inspect
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


logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("zeynal-core")


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

API_SPORTS_KEY = os.getenv("API_SPORTS_KEY")
API_SPORTS_BASE = os.getenv("API_SPORTS_BASE", "https://v1.basketball.api-sports.io")

BALLDONTLIE_API_KEY = os.getenv("BALLDONTLIE_API_KEY")

ODDS_API_KEY = os.getenv("ODDS_API_KEY")
ODDS_BASE = os.getenv("ODDS_BASE", "https://api.the-odds-api.com/v4")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN")


def _parse_date(date_str: str) -> datetime:
    return datetime.strptime(date_str.strip(), "%Y-%m-%d")


def nba_season_string(date_str: str) -> tuple[int, str]:
    d = _parse_date(date_str)
    start = d.year if d.month >= 10 else d.year - 1
    season_str = f"{start}\u2013{start + 1}"  # en dash
    return start, season_str


def _ensure_dict_attr(obj: Any, name: str) -> Dict[str, Any]:
    try:
        val = getattr(obj, name, None)
        if isinstance(val, dict):
            return val
        d: Dict[str, Any] = {}
        setattr(obj, name, d)
        return d
    except Exception:
        return {}


def _ensure_list_attr(obj: Any, name: str) -> list:
    try:
        val = getattr(obj, name, None)
        if isinstance(val, list):
            return val
        lst: list = []
        setattr(obj, name, lst)
        return lst
    except Exception:
        return []


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        s = str(v).strip().replace(",", ".")
        return float(s)
    except Exception:
        return None


def _inject_season(core: Any, league: str, date_str: str) -> None:
    meta = _ensure_dict_attr(core, "meta")
    notes = _ensure_list_attr(core, "notes")

    league_u = (league or "").upper().strip()
    if league_u == "NBA":
        season_start, season_str = nba_season_string(date_str)
    else:
        d = _parse_date(date_str)
        season_start = d.year
        season_str = str(d.year)

    meta["season"] = season_start
    meta["season_str"] = season_str

    try:
        setattr(core, "season", season_start)
    except Exception:
        pass
    try:
        setattr(core, "season_str", season_str)
    except Exception:
        pass

    try:
        new_notes = []
        replaced = False
        for n in notes:
            if isinstance(n, str) and n.strip().lower().startswith("season:"):
                new_notes.append(f"Season: {season_str}")
                replaced = True
            else:
                new_notes.append(n)
        if not replaced:
            new_notes.append(f"Season: {season_str}")
        setattr(core, "notes", new_notes)
    except Exception:
        try:
            notes.append(f"Season: {season_str}")
        except Exception:
            pass


def _apply_degraded_mode(core: Any) -> None:
    meta = _ensure_dict_attr(core, "meta")
    notes = _ensure_list_attr(core, "notes")

    cov = meta.get("data_coverage")
    if not isinstance(cov, dict):
        cov = {}

    any_true = any(bool(v) for v in cov.values()) if cov else False
    if any_true:
        return

    meta["degraded_mode"] = True
    if not meta.get("risk"):
        meta["risk"] = "HIGH"

    notes.append(
        "⚠️ DEGRADED_MODE: Kaynak veriler eksik (team_stats/pace/roster/market). Analiz fallback ile üretildi."
    )

    cp = meta.get("confidence_pct")
    try:
        if cp is None or float(cp) <= 0:
            notes.append("ℹ️ Confidence: Veri eksikliği nedeniyle güven düşürüldü (DEGRADED_MODE).")
    except Exception:
        notes.append("ℹ️ Confidence: Veri eksikliği nedeniyle güven düşürüldü (DEGRADED_MODE).")


def _set_market_optional(core: Any, reason: str) -> None:
    try:
        core.market = {"status": "MARKET_OPTIONAL", "reason": reason}
    except Exception:
        meta = _ensure_dict_attr(core, "meta")
        meta["market"] = {"status": "MARKET_OPTIONAL", "reason": reason}


def _normalize_market_status(core: Any) -> None:
    try:
        m = getattr(core, "market", None)
        if isinstance(m, dict):
            st = str(m.get("status") or "").strip().upper()
            if st == "NO_MARKET":
                m["status"] = "MARKET_OPTIONAL"
                core.market = m
    except Exception:
        pass


def _parse_analyze_params(raw: str) -> tuple[str, str, str, str]:
    params = raw.strip()
    parts = params.split()
    if len(parts) < 4:
        raise ValueError("Eksik parametre")

    league = parts[0]
    date_str = parts[1]
    rest = parts[2:]

    lower = [p.lower() for p in rest]
    if "vs" in lower:
        idx = lower.index("vs")
        home = " ".join(rest[:idx]).strip()
        away = " ".join(rest[idx + 1 :]).strip()
    else:
        mid = len(rest) // 2
        home = " ".join(rest[:mid]).strip()
        away = " ".join(rest[mid:]).strip()

    if not home or not away:
        raise ValueError("Takım isimleri parse edilemedi")

    return league, date_str, home, away


# ----------------------------
# /analyze
# ----------------------------
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

    # ----------------------------
    # FAZ-13
    # ----------------------------
    req = PrematchRequest(
        fixture_id=0,
        league=league,
        date_str=date_str,
        home=home,
        away=away,
    )

    try:
        core = await faz13.run_prematch(req)
    except Exception as e:
        logger.exception("FAZ-13 error")
        await update.message.reply_text("FAZ-13 hata: " + html.escape(str(e)))
        return

    _inject_season(core, league, date_str)

    # ----------------------------
    # FAZ-17 (market) — ✅ KESİN WIRING
    # ----------------------------
    meta = _ensure_dict_attr(core, "meta")
    notes = _ensure_list_attr(core, "notes")

    # ensure data_coverage dict exists
    cov = meta.get("data_coverage")
    if not isinstance(cov, dict):
        cov = {}
        meta["data_coverage"] = cov

    try:
        # 1) PRIMARY PATH: async fetch_market_total (en temiz yol)
        if hasattr(faz17, "fetch_market_total") and callable(getattr(faz17, "fetch_market_total")):
            m = await faz17.fetch_market_total(
                {"league": league, "date_str": date_str, "home": home, "away": away}  # fallback if MarketRequest class differs
            )
            # Some versions expect MarketRequest dataclass; try that first
        else:
            m = None

        # 1b) If the above used dict and failed silently in your version, retry with MarketRequest if available
        if not isinstance(m, dict):
            try:
                if "MarketRequest" in globals() and MarketRequest is not None:
                    m = await faz17.fetch_market_total(MarketRequest(league=league, date_str=date_str, home=home, away=away))  # type: ignore
            except Exception:
                pass

        # 2) SECONDARY PATH: enrich_with_market (sync or async), but NEVER "await sync"
        if not isinstance(m, dict):
            if hasattr(faz17, "enrich_with_market") and callable(getattr(faz17, "enrich_with_market")):
                fn = getattr(faz17, "enrich_with_market")
                try:
                    if inspect.iscoroutinefunction(fn):
                        m = await fn(MarketRequest(league=league, date_str=date_str, home=home, away=away))  # type: ignore
                    else:
                        m = fn(MarketRequest(league=league, date_str=date_str, home=home, away=away))  # type: ignore
                except TypeError:
                    # some old versions accept core directly
                    if inspect.iscoroutinefunction(fn):
                        await fn(core)  # type: ignore
                        m = getattr(core, "market", None)
                    else:
                        fn(core)  # type: ignore
                        m = getattr(core, "market", None)

        if isinstance(m, dict):
            # ✅ always attach to core.market
            try:
                core.market = m
            except Exception:
                pass

            # ✅ THE FIX: market_total MUST be copied into meta
            mt = _safe_float(m.get("total"))
            meta["market_total"] = mt

            # coverage flag (this is what your degraded_mode logic relies on)
            cov["market"] = bool(mt is not None)

        else:
            _set_market_optional(core, "FAZ17_NO_DATA")
            cov["market"] = False
            meta["market_total"] = None

    except Exception as e:
        logger.exception("FAZ-17 error")
        _set_market_optional(core, f"FAZ17_EXCEPTION: {e}")
        cov["market"] = False
        meta["market_total"] = None

    _normalize_market_status(core)

    # ----------------------------
    # FAZ-16 (simulation)
    # ----------------------------
    try:
        line = None
        mkt = getattr(core, "market", None)
        if isinstance(mkt, dict):
            line = _safe_float(mkt.get("total"))

        base_total = None
        if hasattr(core, "total_band") and isinstance(core.total_band, (list, tuple)) and len(core.total_band) >= 2:
            base_total = (float(core.total_band[0]) + float(core.total_band[1])) / 2.0
        else:
            bt = meta.get("base_total")
            base_total = float(bt) if isinstance(bt, (int, float)) else 220.0

        vol = 15.0
        try:
            ha = getattr(core, "home_avg", None)
            aa = getattr(core, "away_avg", None)
            sh = getattr(ha, "stdev_hint", None) if ha else None
            sa = getattr(aa, "stdev_hint", None) if aa else None
            if isinstance(sh, (int, float)) and isinstance(sa, (int, float)):
                vol = max(8.0, min(30.0, float((sh + sa) / 2.0)))
        except Exception:
            vol = 15.0

        sim = faz16_run_simulation(
            base_total=base_total,
            vol=vol,
            n_iter=10_000,
            line=line,
        )

        meta["sim_mean"] = sim.get("mean")
        meta["sim_std"] = sim.get("std")
        if sim.get("p50") is not None:
            notes.append(
                f"🎲 Sim p50≈{float(sim['p50']):.1f} | mean≈{float(sim['mean']):.1f} | std≈{float(sim['std']):.1f}"
            )
    except Exception as e:
        logger.exception("FAZ-16 error")
        _ensure_list_attr(core, "notes").append(f"⚠️ FAZ-16 sim hata: {e}")

    # ✅ data coverage -> DEGRADED_MODE (analiz DURMASIN)
    _apply_degraded_mode(core)

    # ----------------------------
    # FAZ-22 finalize
    # ----------------------------
    try:
        core = faz22.score_and_finalize(core)
    except Exception as e:
        logger.exception("FAZ-22 error")
        await update.message.reply_text("FAZ-22 hata: " + html.escape(str(e)))
        return

    # ----------------------------
    # FAZ-23 snapshot
    # ----------------------------
    try:
        await faz23.record_snapshot(core)
    except Exception:
        pass

    # ----------------------------
    # OUTPUT
    # ----------------------------
    try:
        msg = core.render_html()
    except Exception:
        msg = str(core)

    await update.message.reply_text(msg, disable_web_page_preview=True)


def main():
    baseline_store = TeamBaselineStore("data/baselines")

    faz13 = Faz13Engine(
        api_sports_key=API_SPORTS_KEY,
        api_sports_base=API_SPORTS_BASE,
        baseline_store=baseline_store,
        min_baseline_games=6,
    )

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.bot_data["faz13"] = faz13
    app.bot_data["faz17"] = Faz17Engine(api_key=ODDS_API_KEY, base_url=ODDS_BASE)
    app.bot_data["faz22"] = Faz22Engine()
    app.bot_data["faz23"] = Faz23Engine()

    app.add_handler(CommandHandler("analyze", analyze_command))

    logger.info("BOT STARTED — FAZ-CORE FIX ACTIVE (season auto + market hard-wire + degraded mode)")
    app.run_polling()


if __name__ == "__main__":
    main()

import asyncio
import json
import logging
import os
import sqlite3
from pathlib import Path
import aiohttp
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from typing import List

# Düzeltilmiş paket importları
from faz13_engine import Faz13Engine, PrematchRequest, Faz13CoreOutput
from faz17_engine import Faz17Engine
from faz22_engine import Faz22Engine
from faz23_engine import Faz23Engine
from baseline.team_baseline_store import TeamBaselineStore

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Globals
TZ = ZoneInfo("Europe/Istanbul")
DB_PATH = os.environ.get("SCHEDULER_DB", "scheduler_cache.sqlite")
PAUSED = False

ANALYSIS_STAGES = [
    {"offset": timedelta(hours=24), "use_odds": False},
    {"offset": timedelta(hours=2),  "use_odds": False},
    {"offset": timedelta(minutes=30), "use_odds": True},
]

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("scheduler")

# --- DATABASE & CALIBRATION HELPERS ---
def db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH)

def init_db():
    with db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS jobs(job_key TEXT PRIMARY KEY, ran_utc TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS predictions(game_id TEXT, team TEXT, predicted_total REAL, over_under INTEGER, created_utc TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS results(game_id TEXT PRIMARY KEY, actual_total REAL, over_under INTEGER, finished_utc TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS team_calibration(team TEXT PRIMARY KEY, vol_factor REAL)")
        c.execute("CREATE TABLE IF NOT EXISTS team_errors(team TEXT, error REAL, created_utc TEXT)")

def job_done(key):
    with db() as c:
        return c.execute("SELECT 1 FROM jobs WHERE job_key=?", (key,)).fetchone() is not None

def mark_job(key):
    with db() as c:
        c.execute("INSERT OR REPLACE INTO jobs VALUES (?,?)", (key, datetime.now(timezone.utc).isoformat()))

def get_vol_factor(team):
    with db() as c:
        row = c.execute("SELECT vol_factor FROM team_calibration WHERE team=?", (team,)).fetchone()
        return row[0] if row else 1.0

# --- API HELPERS (Fly.io Optimized) ---
async def fetch_games(league_id, date, session):
    url = os.getenv("API_SPORTS_BASE", "https://v1.basketball.api-sports.io") + "/games"
    headers = {"x-apisports-key": os.getenv("API_SPORTS_KEY")}
    params = {"league": league_id, "date": date, "timezone": "UTC"}
    
    try:
        async with session.get(url, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            resp.raise_for_status()
            js = await resp.json()
            if not isinstance(js, dict) or not isinstance(js.get("response"), list):
                raise ValueError("API-Sports response missing games list")
            out = []
            for g in js.get("response", []):
                try:
                    out.append({
                        "id": str(g["id"]),
                        "start": datetime.fromisoformat(g["date"].replace("Z","+00:00")),
                        "home": g["teams"]["home"]["name"],
                        "away": g["teams"]["away"]["name"],
                        "status": g["status"]["short"],
                        "scores": g.get("scores", {})
                    })
                except (KeyError, TypeError, ValueError, AttributeError):
                    log.warning("Skipping malformed API-Sports fixture", exc_info=True)
                    continue
            return out
    except Exception as e:
        log.error(f"Games fetch failed: {e}")
        return []

# --- CORE ANALYSIS PIPELINE ---
async def run_analysis(engines, league, date, home, away, use_odds, fixture_id=None):
    """Run verified PRE pipeline; FAZ-16 is LIVE-only and needs a real snapshot."""
    game_id = str(fixture_id or f"{league}:{date}:{home}-{away}")
    req = PrematchRequest(int(fixture_id or 0) if str(fixture_id or "0").isdigit() else 0, league, date, home, away)

    try:
        core = await engines["faz13"].run_prematch(req)
        if not isinstance(core, Faz13CoreOutput):
            raise TypeError(f"FAZ-13 returned unexpected type: {type(core).__name__}")
        if not isinstance(getattr(core, "meta", None), dict):
            raise TypeError("FAZ-13 output has no valid metadata dictionary")
        if not isinstance(getattr(core, "total_band", None), tuple):
            raise TypeError("FAZ-13 output has no valid total band")
        if not core.meta.get("data_quality"):
            raise ValueError("FAZ-13 output is missing data-quality provenance")

        if use_odds:
            try:
                core = await engines["faz17"].enrich_with_market(core)
            except Exception as exc:
                core.meta["market_status"] = "MARKET_OPTIONAL"
                core.meta["market_total"] = None
                core.meta["market_reason"] = f"ENRICHMENT_ERROR:{type(exc).__name__}"

        # FAZ-16 live recalibration is deliberately not called pregame.
        core.meta["faz16_status"] = "NOT_APPLICABLE_PREMATCH"
        core.meta["prematch_simulation_status"] = "NOT_RUN"

        core = engines["faz22"].score_and_finalize(core)
        await engines["faz23"].record_snapshot(core)
        log.info("[SCHEDULER] Analyzed: %s | Confidence: %s | Quality: %s | Market: %s",
                 game_id, core.meta.get("final_confidence", core.meta.get("confidence_pct")),
                 core.meta.get("data_quality"), core.meta.get("market_status", "NOT_REQUESTED"))
        return True
    except Exception:
        log.exception("[SCHEDULER] Analysis failed; job will remain retryable: %s", game_id)
        return False

# --- SCHEDULER LOOP ---
async def scheduler_loop(engines):
    init_db()
    with open("leagues.json", "r") as f: leagues = json.load(f)
    
    async with aiohttp.ClientSession() as session:
        while True:
            if PAUSED:
                await asyncio.sleep(10)
                continue
                
            now = datetime.now(timezone.utc)
            utc_dates = {now.date().isoformat(), (now.date() + timedelta(days=1)).isoformat()}
            for lg in leagues:
                league_id = lg.get("api_sports_league_id")
                if not isinstance(league_id, int) or league_id <= 0:
                    log.warning("Skipping league with invalid API-Sports league id: %s", lg.get("name"))
                    continue
                games_by_id = {}
                for utc_date in sorted(utc_dates):
                    day_games = await fetch_games(league_id, utc_date, session)
                    for game in day_games:
                        games_by_id[game["id"]] = game
                for g in games_by_id.values():
                    for st in ANALYSIS_STAGES:
                        key = f"AN:{lg['name']}:{g['id']}:{st['offset']}"
                        if g["status"] not in ("NS", "TBD") or now >= g["start"]:
                            continue
                        if not job_done(key) and now >= g["start"] - st["offset"]:
                            succeeded = await run_analysis(
                                engines, lg["name"],
                                g["start"].astimezone(TZ).date().isoformat(),
                                g["home"], g["away"], st["use_odds"], fixture_id=g["id"],
                            )
                            if succeeded:
                                mark_job(key)
            await asyncio.sleep(60)

# --- TELEGRAM COMMANDS ---
async def scheduler_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🤖 Scheduler: {'DURDURULDU' if PAUSED else 'AKTİF'}")

async def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    app = Application.builder().token(token).build()
    
    # Engine Setup
    baseline = TeamBaselineStore(os.getenv("BASELINE_DIR", "data/baselines"))
    engines = {
        'faz13': Faz13Engine(
            os.getenv("API_SPORTS_KEY"), os.getenv("API_SPORTS_BASE"),
            baseline_store=baseline,
        ),
        'faz17': Faz17Engine(os.getenv("ODDS_API_KEY"), os.getenv("ODDS_BASE")),
        'faz22': Faz22Engine(),
        'faz23': Faz23Engine(storage_path=os.getenv("FAZ23_STORAGE", "faz23_storage.sqlite"))
    }
    
    app.add_handler(CommandHandler("scheduler_status", scheduler_status))
    
    await app.initialize()
    await app.start()
    
    # Start loop in background
    asyncio.create_task(scheduler_loop(engines))
    
    log.info("Dynamic Scheduler & Bot Engine Started.")
    await app.updater.start_polling()

if __name__ == "__main__":
    asyncio.run(main())


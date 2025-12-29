import asyncio
import json
import logging
import os
import sqlite3
import aiohttp
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from typing import List

# Düzeltilmiş paket importları
from faz13_engine import Faz13Engine, PrematchRequest, Faz13CoreOutput
from faz17_engine import Faz17Engine
from faz16_engine import faz16_run_simulation
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
        async with session.get(url, params=params, headers=headers, timeout=15) as resp:
            js = await resp.json()
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
                except: continue
            return out
    except Exception as e:
        log.error(f"Games fetch failed: {e}")
        return []

# --- CORE ANALYSIS PIPELINE ---
async def run_analysis(engines, league, date, home, away, use_odds):
    game_id = f"{league}:{home}-{away}"
    req = PrematchRequest(0, league, date, home, away)
    
    # 1. FAZ-13 (Düzeltilmiş)
    core = await engines['faz13'].run_prematch(req)
    if not core.is_valid:
        log.warning(f"Skipping {game_id}: No baseline data")
        return

    # 2. Market Enrichment
    if use_odds:
        core = await engines['faz17'].enrich_with_market(core)

    # 3. Calibration & Simulation (FAZ-16)
    base_total = float(getattr(core, "market_total", 180.0))
    vol = float(getattr(core, "market_vol", 15.0))
    vol_home = vol * get_vol_factor(home)
    vol_away = vol * get_vol_factor(away)
    
    sim_h = faz16_run_simulation(base_total, vol_home)
    sim_a = faz16_run_simulation(base_total, vol_away)
    
    # 4. Finalize & Save
    core = engines['faz22'].score_and_finalize(core)
    await engines['faz23'].record_snapshot(core)
    log.info(f"[SCHEDULER] Analyzed: {game_id} | Confidence: {core.meta.get('confidence')}")

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
            for lg in leagues:
                date_str = now.astimezone(TZ).date().isoformat()
                games = await fetch_games(lg["api_sports_league_id"], date_str, session)
                
                for g in games:
                    for st in ANALYSIS_STAGES:
                        key = f"AN:{lg['name']}:{g['id']}:{st['offset']}"
                        if not job_done(key) and now >= g["start"] - st["offset"]:
                            await run_analysis(engines, lg["name"], date_str, g["home"], g["away"], st["use_odds"])
                            mark_job(key)
            await asyncio.sleep(60)

# --- TELEGRAM COMMANDS ---
async def scheduler_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🤖 Scheduler: {'DURDURULDU' if PAUSED else 'AKTİF'}")

async def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    app = Application.builder().token(token).build()
    
    # Engine Setup
    baseline = TeamBaselineStore("data/baselines")
    engines = {
        'faz13': Faz13Engine(os.getenv("API_SPORTS_KEY"), os.getenv("API_SPORTS_BASE"), baseline),
        'faz17': Faz17Engine(os.getenv("ODDS_API_KEY"), os.getenv("ODDS_BASE")),
        'faz22': Faz22Engine(),
        'faz23': Faz23Engine()
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


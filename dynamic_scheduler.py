"""
Dynamic Scheduler with Live Analysis and Telegram Status

This script schedules basketball match analyses at multiple offsets before
the game start, performs a live re-analysis during the match, and
exposes a `/scheduler_status` command via Telegram to monitor its
progress.  It reads league information from a `leagues.json` file in
JSON format (same directory) and respects API usage limits by
minimising calls.

Features:

* Schedules analyses 24h, 2h, and 30m before each game (configurable
  via ANALYSIS_STAGES).
* Runs a lightweight live analysis during the match window (start to
  start+3h) that re-runs FAZ‑16 simulation and FAZ‑22 scoring.
* Stores job executions in a local SQLite database to avoid duplicate
  analyses.
* Provides a `/scheduler_status` Telegram command reporting number of
  jobs run and the timestamp of the last run.
* Runs both the scheduler loop and Telegram bot concurrently using
  asyncio.

To use:

1. Create or update `leagues.json` with your leagues and their
   api_sports_league_id values.
2. Set environment variables:
   - `API_SPORTS_KEY`: API key for api-sports.io
   - `ODDS_API_KEY`: API key for The Odds API (optional if you don't
     want market enrichment)
   - `TELEGRAM_BOT_TOKEN`: Token for your Telegram bot (for
     `/scheduler_status`)
   - Optional: `API_SPORTS_BASE`, `ODDS_BASE`, `FAZ23_STORAGE`,
     `SCHEDULE_REFRESH_HOUR_LOCAL`, `LOOKAHEAD_DAYS`
3. Install dependencies (python-telegram-bot >= v20) and run:

       python dynamic_scheduler.py

The scheduler will run indefinitely and log its activity.
"""

import asyncio
import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List
from zoneinfo import ZoneInfo

from faz13_engine import Faz13Engine, PrematchRequest
from faz17_engine import Faz17Engine
from faz16_engine import faz16_run_simulation
from faz22_engine import Faz22Engine
from faz23_engine import Faz23Engine
from baseline.team_baseline_store import TeamBaselineStore

# Telegram imports
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
TZ = ZoneInfo("Europe/Istanbul")

# Analysis stages: when to run analyses before game start, and whether to
# include market odds.  Adjust offsets or add/remove stages as needed.
ANALYSIS_STAGES = [
    {"offset": timedelta(hours=24), "use_odds": False},
    {"offset": timedelta(hours=2),  "use_odds": False},
    {"offset": timedelta(minutes=30), "use_odds": True},
]

# Live analysis window: re-check every X minutes during the match.
LIVE_RECHECK_MINUTES = 10

# SQLite database path
DB_PATH = "scheduler_cache.sqlite"

# Logging setup
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("dynamic_scheduler")

# -----------------------------------------------------------------------------
# Helper functions
# -----------------------------------------------------------------------------

def _env(name: str, default: str | None = None) -> str:
    val = os.getenv(name, default)
    if not val:
        raise RuntimeError(f"Missing env: {name}")
    return val

# SQLite job tracking
def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS jobs (job_key TEXT PRIMARY KEY, ran_utc TEXT)"
        )

def job_done(key: str) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT 1 FROM jobs WHERE job_key=?", (key,)).fetchone()
        return row is not None

def mark_job(key: str) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO jobs (job_key, ran_utc) VALUES (?, ?)",
            (key, datetime.now(timezone.utc).isoformat()),
        )

# Load leagues from leagues.json
def load_leagues(filename: str = "leagues.json") -> List[Dict[str, Any]]:
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.error("Failed to load %s: %s", filename, e)
        return []

# Fetch games for a league and date from API-Sports
async def fetch_games_for_date(league_id: int, date_str: str) -> List[Dict[str, Any]]:
    import urllib.request, urllib.parse
    url = os.getenv("API_SPORTS_BASE", "https://v1.basketball.api-sports.io") + "/games"
    params = urllib.parse.urlencode({
        "league": league_id,
        "date": date_str,
        "timezone": "UTC",
    })
    req = urllib.request.Request(
        url + "?" + params,
        headers={"x-apisports-key": _env("API_SPORTS_KEY")},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
    except Exception as exc:
        log.warning("Failed to fetch schedule: league=%s date=%s: %s", league_id, date_str, exc)
        return []
    out: List[Dict[str, Any]] = []
    for item in data.get("response", []):
        gid = item.get("id")
        dt_iso = item.get("date") or item.get("game", {}).get("date")
        teams = item.get("teams", {})
        home = (teams.get("home") or {}).get("name")
        away = (teams.get("away") or {}).get("name")
        if not (gid and dt_iso and home and away):
            continue
        try:
            start_dt = datetime.fromisoformat(dt_iso.replace("Z", "+00:00"))
        except Exception:
            continue
        out.append({"id": str(gid), "start": start_dt, "home": home, "away": away})
    return out

# Run full analysis pipeline
async def run_analysis(
    faz13: Faz13Engine,
    faz17: Faz17Engine,
    faz22: Faz22Engine,
    faz23: Faz23Engine,
    league_name: str,
    date_str: str,
    home: str,
    away: str,
    use_odds: bool,
) -> None:
    # Phase 1: pre-match core
    core = await faz13.run_prematch(
        PrematchRequest(0, league_name, date_str, home, away)
    )
    # Phase 2: market enrichment
    if use_odds:
        try:
            core = await faz17.enrich_with_market(core)
        except Exception as e:
            log.warning("Market enrichment failed for %s-%s: %s", home, away, e)
    # Phase 3: simulation
    try:
        base_total = float(getattr(core, "market_total", 180.0))
        vol = float(getattr(core, "market_vol", 15.0))
        sim = faz16_run_simulation(base_total, vol)
        if isinstance(core, dict):
            core["faz16_simulation"] = sim
        else:
            core.faz16_simulation = sim
    except Exception:
        pass
    # Phase 4: scoring
    core = faz22.score_and_finalize(core)
    # Phase 5: snapshot
    try:
        await faz23.record_snapshot(core)
    except Exception as e:
        log.warning("Failed to save snapshot for %s-%s: %s", home, away, e)
    log.info("[analysis] Completed %s | %s - %s (use_odds=%s)", league_name, home, away, use_odds)

# Run live analysis if match in progress and not yet analysed
async def run_live_analysis(
    faz13: Faz13Engine,
    faz22: Faz22Engine,
    faz23: Faz23Engine,
    league_name: str,
    date_str: str,
    home: str,
    away: str,
    game_id: str,
) -> None:
    job_key = f"LIVE:{league_name}:{game_id}"
    if job_done(job_key):
        return
    try:
        core = await faz13.run_prematch(
            PrematchRequest(0, league_name, date_str, home, away)
        )
        # Run simulation again (no market)
        try:
            base_total = float(getattr(core, "market_total", 180.0))
            vol = float(getattr(core, "market_vol", 15.0))
            sim = faz16_run_simulation(base_total, vol)
            if isinstance(core, dict):
                core["faz16_simulation_live"] = sim
            else:
                core.faz16_simulation_live = sim
        except Exception:
            pass
        core = faz22.score_and_finalize(core)
        await faz23.record_snapshot(core)
        mark_job(job_key)
        log.info("[live] Re-analysis completed for %s | %s - %s", league_name, home, away)
    except Exception as e:
        log.warning("[live] Re-analysis error for %s-%s: %s", home, away, e)

# Scheduler loop
async def scheduler_loop() -> None:
    init_db()
    leagues = load_leagues()
    if not leagues:
        log.error("No leagues loaded. Ensure leagues.json exists.")
        return
    # Initialise engines
    baseline_store = TeamBaselineStore(os.getenv("BASELINE_DIR", "data/baselines"))
    faz13 = Faz13Engine(
        os.getenv("API_SPORTS_KEY"),
        os.getenv("API_SPORTS_BASE", "https://v1.basketball.api-sports.io"),
        baseline_store=baseline_store,
    )
    faz17 = Faz17Engine(
        os.getenv("ODDS_API_KEY"),
        os.getenv("ODDS_BASE", "https://api.the-odds-api.com/v4"),
    )
    faz22 = Faz22Engine()
    faz23 = Faz23Engine(
        storage_path=os.getenv("FAZ23_STORAGE", "faz23_storage.sqlite"),
    )
    # Determine refresh schedule
    refresh_hour = int(os.getenv("SCHEDULE_REFRESH_HOUR_LOCAL", "8"))
    lookahead_days = int(os.getenv("LOOKAHEAD_DAYS", "2"))

    while True:
        now_utc = datetime.now(timezone.utc)
        now_local = now_utc.astimezone(TZ)
        # Daily schedule refresh
        refresh_target = now_local.replace(hour=refresh_hour, minute=0, second=0, microsecond=0)
        refresh_key = f"REFRESH:{refresh_target.date()}"
        if now_local >= refresh_target and not job_done(refresh_key):
            for d in range(lookahead_days):
                day_local = now_local + timedelta(days=d)
                date_str_local = day_local.date().isoformat()
                for lg in leagues:
                    if lg.get("api_sports_league_id", 0) <= 0:
                        continue
                    games = await fetch_games_for_date(lg["api_sports_league_id"], date_str_local)
                    for game in games:
                        # Schedule analysis stages
                        for stage in ANALYSIS_STAGES:
                            job_key = f"AN:{lg['name']}:{game['id']}:{int(stage['offset'].total_seconds())}"
                            if job_done(job_key):
                                continue
                            run_at = game["start"] - stage["offset"]
                            if run_at <= now_utc:
                                # It's time to run immediately
                                await run_analysis(
                                    faz13, faz17, faz22, faz23,
                                    lg["name"],
                                    date_str_local,
                                    game["home"],
                                    game["away"],
                                    stage["use_odds"],
                                )
                                mark_job(job_key)
                    log.info("Refreshed schedule for %s: %d games", date_str_local, len(games))
            mark_job(refresh_key)
        # Check live matches and run live analysis if within window
        for lg in leagues:
            date_str_today = now_local.date().isoformat()
            if lg.get("api_sports_league_id", 0) > 0:
                todays_games = await fetch_games_for_date(lg["api_sports_league_id"], date_str_today)
                for game in todays_games:
                    start = game["start"]
                    if start <= now_utc <= start + timedelta(hours=3):
                        # run live analysis periodically
                        live_key_time = f"LIVE_TIME:{lg['name']}:{game['id']}"
                        # throttle using job_done by minutes
                        last_live_ts = None
                        with sqlite3.connect(DB_PATH) as conn:
                            row = conn.execute(
                                "SELECT ran_utc FROM jobs WHERE job_key = ?",
                                (live_key_time,),
                            ).fetchone()
                            if row:
                                last_live_ts = datetime.fromisoformat(row[0])
                        if (
                            last_live_ts is None
                            or now_utc - last_live_ts > timedelta(minutes=LIVE_RECHECK_MINUTES)
                        ):
                            # run live analysis
                            await run_live_analysis(
                                faz13, faz22, faz23,
                                lg["name"], date_str_today,
                                game["home"], game["away"],
                                game["id"],
                            )
                            # mark time for throttle
                            mark_job(live_key_time)
        # Sleep 30 seconds
        await asyncio.sleep(30)

# Telegram status command
async def scheduler_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        last_row = conn.execute(
            "SELECT ran_utc FROM jobs ORDER BY ran_utc DESC LIMIT 1"
        ).fetchone()
    last_ts = last_row[0] if last_row else "N/A"
    msg = (
        "\uD83D\uDCCA *Scheduler Status*\n\n"
        f"\u2705 İşlenen job sayısı: `{count}`\n"
        f"\u23F3 Son job zaman damgası: `{last_ts}`\n"
        f"\u23F1 Canlı tekrar aralığı: {LIVE_RECHECK_MINUTES} dakika\n"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

# Run Telegram bot and scheduler concurrently
async def run_scheduler_and_bot() -> None:
    # Start scheduler loop as a background task
    scheduler_task = asyncio.create_task(scheduler_loop())
    # Configure Telegram bot
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        log.warning("TELEGRAM_BOT_TOKEN not set; scheduler_status command will be disabled")
        await scheduler_task
        return
    application = Application.builder().token(bot_token).build()
    application.add_handler(CommandHandler("scheduler_status", scheduler_status))
    # Run both concurrently
    await application.initialize()
    await application.start()
    # Start polling and run until stopped
    polling = asyncio.create_task(application.updater.start_polling())
    try:
        await scheduler_task
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()
        await polling

def main() -> None:
    log.info("Dynamic scheduler with live analysis starting…")
    asyncio.run(run_scheduler_and_bot())

if __name__ == "__main__":
    main()

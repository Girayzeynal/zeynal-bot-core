"""
Dynamic Scheduler with Live Analysis, Pause/Resume, Run-Now and Telegram Status

Bu sürüm:
- 24h, 2h ve 30dk öncesi analiz yapar (ANALYSIS_STAGES)
- Maç başladıktan sonra 3 saat boyunca belirli aralıklarla canlı yeniden analiz yapar
- /scheduler_status komutuyla kaç job çalıştığını ve son job zamanını raporlar
- /scheduler_pause komutuyla zamanlayıcıyı durdurur/yeniden başlatır
- /scheduler_run_now <Lig> | <YYYY-MM-DD> | <Ev> - <Dep> komutuyla anlık analiz başlatır
- leagues.json dosyasından ligleri okur
- Fly.io 512 MB free tier ve Python-telegram-bot v20+ ile uyumludur
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

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
TZ = ZoneInfo("Europe/Istanbul")

ANALYSIS_STAGES = [
    {"offset": timedelta(hours=24), "use_odds": False},
    {"offset": timedelta(hours=2),  "use_odds": False},
    {"offset": timedelta(minutes=30), "use_odds": True},
]

LIVE_RECHECK_MINUTES = 10
DB_PATH = "scheduler_cache.sqlite"

# Scheduler state: paused or not
PAUSED = False

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("dynamic_scheduler")

# -----------------------------------------------------------------------------
# Helper functions and DB utilities
# -----------------------------------------------------------------------------
def _env(name: str, default: str | None = None) -> str:
    val = os.getenv(name, default)
    if not val:
        raise RuntimeError(f"Missing env: {name}")
    return val

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

def load_leagues(filename: str = "leagues.json") -> List[Dict[str, Any]]:
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.error("Failed to load %s: %s", filename, e)
        return []

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
    core = await faz13.run_prematch(
        PrematchRequest(0, league_name, date_str, home, away)
    )
    if use_odds:
        try:
            core = await faz17.enrich_with_market(core)
        except Exception as e:
            log.warning("Market enrichment failed for %s-%s: %s", home, away, e)
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
    core = faz22.score_and_finalize(core)
    try:
        await faz23.record_snapshot(core)
    except Exception as e:
        log.warning("Failed to save snapshot for %s-%s: %s", home, away, e)
    log.info("[analysis] Completed %s | %s - %s (use_odds=%s)", league_name, home, away, use_odds)

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

# -----------------------------------------------------------------------------
# Scheduler loop
# -----------------------------------------------------------------------------
async def scheduler_loop() -> None:
    init_db()
    leagues = load_leagues()
    if not leagues:
        log.error("No leagues loaded. Ensure leagues.json exists.")
        return
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
    refresh_hour = int(os.getenv("SCHEDULE_REFRESH_HOUR_LOCAL", "8"))
    lookahead_days = int(os.getenv("LOOKAHEAD_DAYS", "2"))

    while True:
        global PAUSED
        now_utc = datetime.now(timezone.utc)
        now_local = now_utc.astimezone(TZ)

        if PAUSED:
            # Scheduler paused; skip work
            await asyncio.sleep(30)
            continue

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
                        for stage in ANALYSIS_STAGES:
                            job_key = f"AN:{lg['name']}:{game['id']}:{int(stage['offset'].total_seconds())}"
                            if job_done(job_key):
                                continue
                            run_at = game["start"] - stage["offset"]
                            if run_at <= now_utc:
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

        # Live analyses
        for lg in leagues:
            date_str_today = now_local.date().isoformat()
            if lg.get("api_sports_league_id", 0) > 0:
                todays_games = await fetch_games_for_date(lg["api_sports_league_id"], date_str_today)
                for game in todays_games:
                    start = game["start"]
                    if start <= now_utc <= start + timedelta(hours=3):
                        live_key_time = f"LIVE_TIME:{lg['name']}:{game['id']}"
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
                            await run_live_analysis(
                                faz13, faz22, faz23,
                                lg["name"], date_str_today,
                                game["home"], game["away"],
                                game["id"],
                            )
                            mark_job(live_key_time)
        await asyncio.sleep(30)

# -----------------------------------------------------------------------------
# Telegram command handlers
# -----------------------------------------------------------------------------
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
        f"\u23F2 Scheduler durumu: {'PAUSE' if PAUSED else 'RUN'}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def scheduler_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global PAUSED
    PAUSED = not PAUSED
    state = "durduruldu" if PAUSED else "devam ediyor"
    await update.message.reply_text(
        f"\u23F8 Scheduler {state}.", parse_mode="Markdown"
    )

async def scheduler_run_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            "Kullanım: /scheduler_run_now <Lig> | <YYYY-MM-DD> | <Ev> - <Dep>",
            parse_mode="Markdown"
        )
        return
    try:
        raw = " ".join(context.args)
        parts = [p.strip() for p in raw.split("|")]
        if len(parts) != 3:
            raise ValueError
        league = parts[0]
        date_str = parts[1]
        home, away = [x.strip() for x in parts[2].split("-")]
    except Exception:
        await update.message.reply_text(
            "Kullanım: /scheduler_run_now <Lig> | <YYYY-MM-DD> | <Ev> - <Dep>",
            parse_mode="Markdown"
        )
        return

    # Find league config
    leagues = load_leagues()
    lg_cfg = next((l for l in leagues if l["name"].lower() == league.lower()), None)
    if not lg_cfg:
        await update.message.reply_text(
            f"Lig bulunamadı: {league}", parse_mode="Markdown"
        )
        return
    # Initialise engines (short-lived)
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

    await run_analysis(
        faz13, faz17, faz22, faz23,
        lg_cfg["name"], date_str, home, away, True
    )
    await update.message.reply_text(
        f"Anlık analiz başlatıldı: {league} | {date_str} | {home}-{away}",
        parse_mode="Markdown"
    )

# -----------------------------------------------------------------------------
# Run Telegram bot and scheduler concurrently
# -----------------------------------------------------------------------------
async def run_scheduler_and_bot() -> None:
    scheduler_task = asyncio.create_task(scheduler_loop())
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        log.warning("TELEGRAM_BOT_TOKEN not set; Telegram commands disabled")
        await scheduler_task
        return
    application = Application.builder().token(bot_token).build()
    application.add_handler(CommandHandler("scheduler_status", scheduler_status))
    application.add_handler(CommandHandler("scheduler_pause", scheduler_pause))
    application.add_handler(CommandHandler("scheduler_run_now", scheduler_run_now))
    await application.initialize()
    await application.start()
    polling = asyncio.create_task(application.updater.start_polling())
    try:
        await scheduler_task
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()
        await polling

def main() -> None:
    log.info("Dynamic scheduler with live analysis, pause/run-now starting…")
    asyncio.run(run_scheduler_and_bot())

if __name__ == "__main__":
    main()

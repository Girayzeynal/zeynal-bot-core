"""
dynamic_scheduler.py – TEAM ERROR CURVE & REPORTS

Bu sürüm:
- 24h/2h/30dk analiz
- Canlı yeniden analiz
- Takım bazlı kalibrasyon ve hata kaydı
- Telegram komutları: /scheduler_status, /scheduler_pause, /scheduler_run_now,
  /scheduler_calibration, /scheduler_errors <Takım> [N]
- Yalnızca API‑Sports’ın ücretsiz games endpoint’i kullanılır.

"""

import asyncio
import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import List

from faz13_engine import Faz13Engine, PrematchRequest
from faz17_engine import Faz17Engine
from faz16_engine import faz16_run_simulation
from faz22_engine import Faz22Engine
from faz23_engine import Faz23Engine
from baseline.team_baseline_store import TeamBaselineStore

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Globals and configuration
TZ = ZoneInfo("Europe/Istanbul")
DB_PATH = "scheduler_cache.sqlite"
PAUSED = False

ANALYSIS_STAGES = [
    {"offset": timedelta(hours=24), "use_odds": False},
    {"offset": timedelta(hours=2),  "use_odds": False},
    {"offset": timedelta(minutes=30), "use_odds": True},
]

LIVE_RECHECK_MINUTES = 10

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("scheduler")

# Database helpers
def db():
    return sqlite3.connect(DB_PATH)

def init_db():
    with db() as c:
        c.execute("""
        CREATE TABLE IF NOT EXISTS jobs(
            job_key TEXT PRIMARY KEY,
            ran_utc TEXT
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS predictions(
            game_id TEXT,
            team TEXT,
            predicted_total REAL,
            over_under INTEGER,
            created_utc TEXT
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS results(
            game_id TEXT PRIMARY KEY,
            actual_total REAL,
            over_under INTEGER,
            finished_utc TEXT
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS team_calibration(
            team TEXT PRIMARY KEY,
            vol_factor REAL
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS team_errors(
            team TEXT,
            error REAL,
            created_utc TEXT
        )
        """)

def job_done(key):
    with db() as c:
        return c.execute("SELECT 1 FROM jobs WHERE job_key=?", (key,)).fetchone() is not None

def mark_job(key):
    with db() as c:
        c.execute("INSERT OR REPLACE INTO jobs VALUES (?,?)",
                  (key, datetime.now(timezone.utc).isoformat()))

def get_vol_factor(team):
    with db() as c:
        row = c.execute("SELECT vol_factor FROM team_calibration WHERE team=?", (team,)).fetchone()
        return row[0] if row else 1.0

def update_vol_factor(team, error):
    # Hata kaydı
    with db() as c:
        c.execute("INSERT INTO team_errors VALUES (?,?,?)",
                  (team, error, datetime.now(timezone.utc).isoformat()))
        # Kalibrasyon ayarı (lineer)
        adj = min(max(error / 20.0, 0.85), 1.15)
        c.execute("INSERT OR REPLACE INTO team_calibration(team, vol_factor) VALUES (?,?)",
                  (team, adj))

def get_all_calibrations():
    with db() as c:
        return c.execute("SELECT team, vol_factor FROM team_calibration").fetchall()

def get_last_errors(team, n):
    with db() as c:
        return c.execute(
            "SELECT error, created_utc FROM team_errors WHERE team=? ORDER BY created_utc DESC LIMIT ?",
            (team, n)
        ).fetchall()

# Utility
def _env(name, default=None):
    v = os.getenv(name, default)
    if not v:
        raise RuntimeError(f"Missing env {name}")
    return v

def load_leagues():
    with open("leagues.json", "r", encoding="utf-8") as f:
        return json.load(f)

# API-Sports (free) – get games and scores
async def fetch_games(league_id, date):
    import urllib.request, urllib.parse
    url = _env("API_SPORTS_BASE") + "/games"
    q = urllib.parse.urlencode({"league": league_id, "date": date, "timezone": "UTC"})
    req = urllib.request.Request(
        url + "?" + q,
        headers={"x-apisports-key": _env("API_SPORTS_KEY")}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            js = json.loads(r.read().decode())
    except:
        return []
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
        except:
            pass
    return out

# Analysis
async def run_analysis(faz13, faz17, faz22, faz23,
                       league, date, home, away, use_odds):
    game_id = f"{league}:{home}-{away}"
    core = await faz13.run_prematch(PrematchRequest(0, league, date, home, away))
    if use_odds:
        try:
            core = await faz17.enrich_with_market(core)
        except:
            pass
    base_total = float(getattr(core, "market_total", 180))
    vol = float(getattr(core, "market_vol", 15))
    vol_home = vol * get_vol_factor(home)
    vol_away = vol * get_vol_factor(away)
    sim_home = faz16_run_simulation(base_total, vol_home)
    sim_away = faz16_run_simulation(base_total, vol_away)
    predicted_total = (sim_home["mean"] + sim_away["mean"]) / 2.0
    over_under = 1 if predicted_total > base_total else 0
    with db() as c:
        c.execute(
            "INSERT INTO predictions VALUES (?,?,?,?,?)",
            (game_id, home, predicted_total, over_under, datetime.now(timezone.utc).isoformat())
        )
    core = faz22.score_and_finalize(core)
    await faz23.record_snapshot(core)

# Live and result handler
async def handle_live_and_result(faz13, faz22, faz23,
                                 league, game, date):
    gid = f"{league}:{game['id']}"
    home = game["home"]
    away = game["away"]
    # Final score
    if game["status"] == "FT":
        if job_done("RES:"+gid):
            return
        scores = game["scores"]
        try:
            actual_total = scores["home"]["total"] + scores["away"]["total"]
        except:
            return
        over_under = 1 if actual_total > scores["home"]["total"] + scores["away"]["total"] else 0
        with db() as c:
            c.execute("INSERT OR REPLACE INTO results VALUES (?,?,?,?)",
                      (gid, actual_total, over_under, datetime.now(timezone.utc).isoformat()))
            preds = c.execute(
                "SELECT predicted_total, team FROM predictions WHERE game_id=? ORDER BY created_utc DESC LIMIT 2",
                (f"{league}:{home}-{away}",)
            ).fetchall()
        for pred_total, team in preds:
            err = abs(pred_total - actual_total)
            update_vol_factor(team, err)
        mark_job("RES:"+gid)
        log.info(f"[RESULT] {gid} = {actual_total}")
        return
    # Live analysis
    if game["status"] in ("Q1","Q2","Q3","Q4","HT"):
        lk = "LIVE:"+gid
        if job_done(lk):
            return
        try:
            core = await faz13.run_prematch(PrematchRequest(0, league, date, home, away))
            sim = faz16_run_simulation(
                float(getattr(core, "market_total", 180)),
                float(getattr(core, "market_vol", 15))
            )
            core = faz22.score_and_finalize(core)
            await faz23.record_snapshot(core)
            mark_job(lk)
        except:
            pass

# Scheduler loop
async def scheduler():
    init_db()
    leagues = load_leagues()
    baseline = TeamBaselineStore("data/baselines")
    faz13 = Faz13Engine(_env("API_SPORTS_KEY"), _env("API_SPORTS_BASE"), baseline)
    faz17 = Faz17Engine(_env("ODDS_API_KEY"), _env("ODDS_BASE"))
    faz22 = Faz22Engine()
    faz23 = Faz23Engine()
    while True:
        if PAUSED:
            await asyncio.sleep(30)
            continue
        now = datetime.now(timezone.utc)
        for lg in leagues:
            date = now.astimezone(TZ).date().isoformat()
            games = await fetch_games(lg["api_sports_league_id"], date)
            for g in games:
                for st in ANALYSIS_STAGES:
                    key = f"AN:{lg['name']}:{g['id']}:{st['offset']}"
                    if not job_done(key) and now >= g["start"] - st["offset"]:
                        await run_analysis(
                            faz13, faz17, faz22, faz23,
                            lg["name"], date,
                            g["home"], g["away"],
                            st["use_odds"]
                        )
                        mark_job(key)
                await handle_live_and_result(
                    faz13, faz22, faz23,
                    lg["name"], g, date
                )
        await asyncio.sleep(30)

# Telegram commands
async def scheduler_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    with db() as c:
        jobs = c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    await update.message.reply_text(
        f"Scheduler Durumu: {'PAUSE' if PAUSED else 'RUN'}\nToplam job: {jobs}"
    )

async def scheduler_pause(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global PAUSED
    PAUSED = not PAUSED
    await update.message.reply_text(
        "Scheduler durdu." if PAUSED else "Scheduler devam ediyor."
    )

async def scheduler_run_now(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Kullanım: /scheduler_run_now <Lig> | <Tarih> | <Ev> - <Dep>")
        return
    try:
        raw = " ".join(ctx.args)
        parts = [p.strip() for p in raw.split("|")]
        league, date_str = parts[0], parts[1]
        home, away = [x.strip() for x in parts[2].split("-")]
    except Exception:
        await update.message.reply_text("Kullanım: /scheduler_run_now <Lig> | <Tarih> | <Ev> - <Dep>")
        return
    leagues = load_leagues()
    lg_cfg = next((l for l in leagues if l["name"].lower() == league.lower()), None)
    if not lg_cfg:
        await update.message.reply_text(f"Lig bulunamadı: {league}")
        return
    baseline = TeamBaselineStore("data/baselines")
    faz13 = Faz13Engine(_env("API_SPORTS_KEY"), _env("API_SPORTS_BASE"), baseline)
    faz17 = Faz17Engine(_env("ODDS_API_KEY"), _env("ODDS_BASE"))
    faz22 = Faz22Engine()
    faz23 = Faz23Engine()
    await run_analysis(faz13, faz17, faz22, faz23, league, date_str, home, away, True)
    await update.message.reply_text("Anlık analiz başlatıldı.")

async def scheduler_calibration(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rows = get_all_calibrations()
    if not rows:
        await update.message.reply_text("Kalibrasyon verisi yok.")
        return
    msg = "🔧 *Kalibrasyon Katsayıları* (Takım:Volatilite)\n"
    for team, factor in rows:
        msg += f"{team}: {factor:.2f}\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def scheduler_errors(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Kullanım: /scheduler_errors <Takım> [N]")
        return
    team = ctx.args[0]
    n = int(ctx.args[1]) if len(ctx.args) > 1 else 10
    rows = get_last_errors(team, n)
    if not rows:
        await update.message.reply_text("Hata verisi bulunamadı.")
        return
    msg = f"📈 *{team} Hata Eğrisi* (son {len(rows)} kayıt)\n"
    total_err = 0.0
    for idx, (err, ts) in enumerate(rows, 1):
        msg += f"{idx}. {err:.2f} (UTC {ts})\n"
        total_err += err
    avg_err = total_err / len(rows)
    msg += f"\nOrtalama hata: {avg_err:.2f}"
    await update.message.reply_text(msg, parse_mode="Markdown")

# Main
async def main():
    app = Application.builder().token(_env("TELEGRAM_BOT_TOKEN")).build()
    app.add_handler(CommandHandler("scheduler_status", scheduler_status))
    app.add_handler(CommandHandler("scheduler_pause", scheduler_pause))
    app.add_handler(CommandHandler("scheduler_run_now", scheduler_run_now))
    app.add_handler(CommandHandler("scheduler_calibration", scheduler_calibration))
    app.add_handler(CommandHandler("scheduler_errors", scheduler_errors))
    await app.initialize()
    await app.start()
    asyncio.create_task(scheduler())
    await app.updater.start_polling()

if __name__ == "__main__":
    asyncio.run(main())

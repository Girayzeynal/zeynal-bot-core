# dynamic_scheduler.py
# Fly.io 512MB + Free API quota-aware dynamic match-time scheduler
# Repo root: zeynal-bot-core/dynamic_scheduler.py

import asyncio
import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any, Optional

# --- Engines (repo içi)
from faz13_engine import Faz13Engine, PrematchRequest
from faz17_engine import Faz17Engine
from faz16_engine import faz16_run_simulation
from faz22_engine import Faz22Engine
from faz23_engine import Faz23Engine
from baseline.team_baseline_store import TeamBaselineStore

# -----------------------------
# LOG
# -----------------------------
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("dynamic-scheduler")

TR_TZ = ZoneInfo("Europe/Istanbul")

# -----------------------------
# CONFIG
# -----------------------------
def _env(name: str, default: Optional[str] = None) -> str:
    val = os.getenv(name, default)
    if val is None or val == "":
        raise RuntimeError(f"Missing required environment variable: {name}")
    return val


@dataclass(frozen=True)
class LeagueCfg:
    name: str
    api_sports_league_id: int          # API-Sports league id
    odds_sport_key: Optional[str]      # TheOddsAPI sport key (örn basketball_nba)
    enabled_odds: bool = True          # market enrich açık mı?
    enabled_schedule: bool = True      # fikstür çekimi açık mı?


# ELİT LİGLER — SEN BU ID’LERİ DOLDURACAKSIN
# Çünkü API-Sports league id’leri hesabına/endpoint’e göre değişebiliyor.
# (Burada doğru id yoksa bile scheduler çalışır; sadece fikstür çekemez.)
DEFAULT_LEAGUES: list[LeagueCfg] = [
    # NBA
    LeagueCfg("NBA", api_sports_league_id=12, odds_sport_key="basketball_nba", enabled_odds=True),

    # Avrupa turnuvaları (ID’leri senin API-Sports dashboard’undan doğrula)
    LeagueCfg("EuroLeague", api_sports_league_id=0, odds_sport_key="basketball_euroleague", enabled_odds=True),
    LeagueCfg("EuroCup", api_sports_league_id=0, odds_sport_key=None, enabled_odds=False),  # odds yoksa kapat
    LeagueCfg("BCL", api_sports_league_id=0, odds_sport_key=None, enabled_odds=False),

    # Ulusal elit ligler
    LeagueCfg("Spain ACB", api_sports_league_id=0, odds_sport_key=None, enabled_odds=False),
    LeagueCfg("Italy Serie A", api_sports_league_id=0, odds_sport_key=None, enabled_odds=False),
    LeagueCfg("Turkey BSL", api_sports_league_id=0, odds_sport_key=None, enabled_odds=False),
    LeagueCfg("Greece A1", api_sports_league_id=0, odds_sport_key=None, enabled_odds=False),
    LeagueCfg("Germany BBL", api_sports_league_id=0, odds_sport_key=None, enabled_odds=False),
    LeagueCfg("France Pro A", api_sports_league_id=0, odds_sport_key=None, enabled_odds=False),
]


def load_leagues() -> list[LeagueCfg]:
    """
    İstersen LEAGUES_JSON env ile tamamen dışarıdan ver:
    [
      {"name":"NBA","api_sports_league_id":12,"odds_sport_key":"basketball_nba","enabled_odds":true},
      ...
    ]
    """
    raw = os.getenv("LEAGUES_JSON")
    if not raw:
        return DEFAULT_LEAGUES

    data = json.loads(raw)
    leagues: list[LeagueCfg] = []
    for item in data:
        leagues.append(
            LeagueCfg(
                name=str(item["name"]),
                api_sports_league_id=int(item["api_sports_league_id"]),
                odds_sport_key=item.get("odds_sport_key"),
                enabled_odds=bool(item.get("enabled_odds", True)),
                enabled_schedule=bool(item.get("enabled_schedule", True)),
            )
        )
    return leagues


# -----------------------------
# FREE QUOTA GUARD (basit)
# -----------------------------
class TokenBucket:
    """
    Basit rate limiter:
    - capacity: bucket kapasitesi
    - refill_every: saniye cinsinden dolum periyodu
    - refill_amount: periyotta eklenecek token
    """
    def __init__(self, capacity: int, refill_every: float, refill_amount: int):
        self.capacity = capacity
        self.refill_every = refill_every
        self.refill_amount = refill_amount
        self.tokens = capacity
        self.updated = asyncio.get_event_loop().time()
        self.lock = asyncio.Lock()

    async def acquire(self, n: int = 1) -> None:
        async with self.lock:
            while True:
                now = asyncio.get_event_loop().time()
                elapsed = now - self.updated
                if elapsed >= self.refill_every:
                    steps = int(elapsed // self.refill_every)
                    self.tokens = min(self.capacity, self.tokens + steps * self.refill_amount)
                    self.updated = self.updated + steps * self.refill_every

                if self.tokens >= n:
                    self.tokens -= n
                    return

                await asyncio.sleep(max(0.25, self.refill_every / 2))


# Free plan “dakika” limitlerini kaba şekilde uygula:
# BallDontLie free: 5 req/min  → 1 token/12s
BALDONTLIE_LIMITER = TokenBucket(capacity=5, refill_every=12.0, refill_amount=1)

# API-Sports free: 10 req/min varsayımı → 1 token/6s
APISPORTS_LIMITER = TokenBucket(capacity=10, refill_every=6.0, refill_amount=1)

# Odds API: hız limiti yüksek ama “kredi” önemli → rate limiter değil “call budget” daha önemli.
# Burada sadece aynı anda spam engelliyoruz.
ODDS_LIMITER = TokenBucket(capacity=10, refill_every=1.0, refill_amount=10)


# -----------------------------
# SQLITE CACHE (çok hafif)
# -----------------------------
DB_PATH = os.getenv("SCHEDULER_DB", "scheduler_cache.sqlite")

def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn

def init_db() -> None:
    with db() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS games (
            game_id TEXT PRIMARY KEY,
            league TEXT NOT NULL,
            start_utc TEXT NOT NULL,
            home TEXT NOT NULL,
            away TEXT NOT NULL
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            job_key TEXT PRIMARY KEY,
            ran_utc TEXT NOT NULL
        )
        """)

def upsert_game(game_id: str, league: str, start_utc: str, home: str, away: str) -> None:
    with db() as conn:
        conn.execute("""
        INSERT INTO games(game_id, league, start_utc, home, away)
        VALUES(?,?,?,?,?)
        ON CONFLICT(game_id) DO UPDATE SET
            league=excluded.league,
            start_utc=excluded.start_utc,
            home=excluded.home,
            away=excluded.away
        """, (game_id, league, start_utc, home, away))

def list_games_between(start_utc: datetime, end_utc: datetime) -> list[dict[str, str]]:
    with db() as conn:
        cur = conn.execute("""
        SELECT game_id, league, start_utc, home, away
        FROM games
        WHERE start_utc >= ? AND start_utc <= ?
        ORDER BY start_utc ASC
        """, (start_utc.isoformat(), end_utc.isoformat()))
        out = []
        for r in cur.fetchall():
            out.append({"game_id": r[0], "league": r[1], "start_utc": r[2], "home": r[3], "away": r[4]})
        return out

def job_ran(job_key: str) -> bool:
    with db() as conn:
        cur = conn.execute("SELECT 1 FROM jobs WHERE job_key = ? LIMIT 1", (job_key,))
        return cur.fetchone() is not None

def mark_job(job_key: str) -> None:
    with db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO jobs(job_key, ran_utc) VALUES(?,?)",
            (job_key, datetime.now(timezone.utc).isoformat()),
        )


# -----------------------------
# API-Sports schedule fetch (quota-aware)
# -----------------------------
async def api_sports_get(url: str, headers: dict[str, str], params: dict[str, str]) -> dict[str, Any]:
    """
    requests yerine standard library ile yapmak mümkün ama pratik değil.
    Burada requests yok; urllib kullanarak çok hafif gidiyoruz.
    """
    import urllib.parse
    import urllib.request

    await APISPORTS_LIMITER.acquire(1)

    full = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw)

def parse_api_sports_games(payload: dict[str, Any], league_name: str) -> list[dict[str, Any]]:
    """
    API-Sports Basketball response genelde:
    { "response": [ { "id":..., "date":..., "teams": {"home": {"name":...}, "away": {...}} }, ... ] }
    Ama farklı olabilir. Burayı gerektiğinde 5 dakikada uyarlarsın.
    """
    games = payload.get("response") or payload.get("results") or []
    out: list[dict[str, Any]] = []

    for g in games:
        gid = str(g.get("id") or g.get("game", {}).get("id") or "")
        if not gid:
            continue

        # start time
        date_str = (
            g.get("date")
            or g.get("time")
            or g.get("game", {}).get("date")
            or g.get("game", {}).get("time")
        )
        if not date_str:
            continue

        # ISO parse (bazıları Z, bazıları +00:00 vs)
        try:
            start_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            # Son çare: sadece "YYYY-MM-DD" gelirse 20:00 UTC gibi saçma bir şey olmaması için skip
            continue

        teams = g.get("teams") or g.get("game", {}).get("teams") or {}
        home = (teams.get("home") or {}).get("name") or (teams.get("home") or {}).get("team_name") or ""
        away = (teams.get("away") or {}).get("name") or (teams.get("away") or {}).get("team_name") or ""

        if not home or not away:
            # Bazı endpointlerde home/away farklı key olabilir
            home = g.get("home") or ""
            away = g.get("away") or ""
        if not home or not away:
            continue

        out.append({
            "game_id": f"apisports:{gid}",
            "league": league_name,
            "start_utc": start_dt,
            "home": home,
            "away": away,
        })

    return out

async def refresh_schedule_for_day(leagues: list[LeagueCfg], day_local: datetime) -> None:
    """
    Günde 1 kez (veya istersen 2 kez) çağır.
    Free kota korumak için: sadece bugün+yarın.
    """
    api_key = _env("API_SPORTS_KEY")
    base = os.getenv("API_SPORTS_BASE", "https://v1.basketball.api-sports.io")
    url = base.rstrip("/") + "/games"
    headers = {"x-apisports-key": api_key}

    date_param = day_local.date().isoformat()

    for lg in leagues:
        if not lg.enabled_schedule:
            continue
        if lg.api_sports_league_id <= 0:
            # ID yoksa çekme (boşuna kota yakma)
            continue

        params = {"league": str(lg.api_sports_league_id), "date": date_param}
        try:
            payload = await api_sports_get(url, headers=headers, params=params)
            parsed = parse_api_sports_games(payload, lg.name)
            for item in parsed:
                upsert_game(
                    game_id=item["game_id"],
                    league=item["league"],
                    start_utc=item["start_utc"].isoformat(),
                    home=item["home"],
                    away=item["away"],
                )
            log.info(f"[schedule] {lg.name} {date_param} -> {len(parsed)} game cached")
        except Exception as e:
            log.warning(f"[schedule] fetch failed {lg.name} {date_param}: {e}")


# -----------------------------
# ANALYSIS (quota-aware)
# -----------------------------
ANALYSIS_OFFSETS = [
    timedelta(hours=2),      # T-2h (core)
    timedelta(minutes=30),   # T-30m (core + market)  -> Odds kredisi burada yensin
]

async def run_pipeline(
    faz13: Faz13Engine,
    faz17: Faz17Engine,
    faz22: Faz22Engine,
    faz23: Faz23Engine,
    league: str,
    date_str: str,
    home: str,
    away: str,
    allow_odds: bool,
) -> None:
    # 1) Core
    core = await faz13.run_prematch(PrematchRequest(0, league, date_str, home, away))

    # 2) Market (kredi yiyor olabilir) -> sadece allow_odds True ise
    if allow_odds:
        await ODDS_LIMITER.acquire(1)
        core = await faz17.enrich_with_market(core)

    # 3) FAZ16 sim (lokal, kota yok)
    try:
        base_total = float(getattr(core, "market_total", getattr(core, "total", 180.0)))
        vol = float(getattr(core, "market_vol", getattr(core, "vol", 15.0)))
        sim = faz16_run_simulation(base_total, vol)

        if isinstance(core, dict):
            core["faz16_simulation"] = sim
        else:
            setattr(core, "faz16_simulation", sim)
    except Exception:
        pass

    # 4) Risk/Confidence
    core = faz22.score_and_finalize(core)

    # 5) Snapshot
    await faz23.record_snapshot(core)

    # hafif log
    log.info(f"[OK] {league} | {home}-{away} | allow_odds={allow_odds}")


# -----------------------------
# MAIN LOOP (dynamic triggers)
# -----------------------------
async def main() -> None:
    init_db()
    leagues = load_leagues()

    # Engine init (tek sefer)
    baseline_dir = os.getenv("BASELINE_DIR", "data/baselines")
    baseline_store = TeamBaselineStore(baseline_dir)

    faz13 = Faz13Engine(
        _env("API_SPORTS_KEY"),
        os.getenv("API_SPORTS_BASE", "https://v1.basketball.api-sports.io"),
        baseline_store=baseline_store,
    )
    faz17 = Faz17Engine(
        _env("ODDS_API_KEY"),
        os.getenv("ODDS_BASE", "https://api.the-odds-api.com/v4"),
    )
    faz22 = Faz22Engine()
    faz23 = Faz23Engine(storage_path=os.getenv("FAZ23_STORAGE", "faz23_storage.sqlite"))

    # Günlük fikstür çekim zamanı (İstanbul saati)
    schedule_hour = int(os.getenv("SCHEDULE_REFRESH_HOUR_LOCAL", "8"))  # 08:00
    lookahead_days = int(os.getenv("LOOKAHEAD_DAYS", "2"))  # bugün + yarın

    while True:
        now_local = datetime.now(TR_TZ)
        now_utc = now_local.astimezone(timezone.utc)

        # 1) Fikstür refresh: günde 1 kez 08:00 civarı
        # Eğer kaçırdıysan bir sonraki loop’ta yakalar.
        today_target = now_local.replace(hour=schedule_hour, minute=0, second=0, microsecond=0)
        refresh_key = f"refresh:{today_target.date().isoformat()}"
        if now_local >= today_target and not job_ran(refresh_key):
            for d in range(lookahead_days):
                day = now_local + timedelta(days=d)
                await refresh_schedule_for_day(leagues, day)
            mark_job(refresh_key)
            log.info(f"[refresh] done for {today_target.date().isoformat()}")

        # 2) Önümüzdeki 48 saatin maçlarını al (cache’den)
        horizon_end = now_utc + timedelta(hours=48)
        games = list_games_between(now_utc - timedelta(hours=1), horizon_end)

        # 3) Her maç için offset job’ları planla
        for g in games:
            try:
                start_dt = datetime.fromisoformat(g["start_utc"]).astimezone(timezone.utc)
            except Exception:
                continue

            league = g["league"]
            home = g["home"]
            away = g["away"]

            # date_str: FAZ13 prematch inputunda kullanılıyor (YYYY-MM-DD)
            date_str = start_dt.astimezone(TR_TZ).date().isoformat()

            # league config bul
            lg_cfg = next((x for x in leagues if x.name == league), None)

            for off in ANALYSIS_OFFSETS:
                run_at = start_dt - off
                if run_at < now_utc:
                    continue

                # job key: maç+offset
                job_key = f"an:{g['game_id']}:{int(off.total_seconds())}"
                if job_ran(job_key):
                    continue

                # tetik zamanı geldiyse çalıştır
                # (loop per ~30s bekliyor; küçük sapma sorun değil)
                if now_utc >= run_at - timedelta(seconds=20) and now_utc <= run_at + timedelta(seconds=60):
                    # Odds kullanımı: sadece T-30m job’unda aç (kredi koru)
                    allow_odds = False
                    if lg_cfg and lg_cfg.enabled_odds and lg_cfg.odds_sport_key:
                        allow_odds = (off <= timedelta(minutes=30))

                    try:
                        await run_pipeline(
                            faz13=faz13,
                            faz17=faz17,
                            faz22=faz22,
                            faz23=faz23,
                            league=league,
                            date_str=date_str,
                            home=home,
                            away=away,
                            allow_odds=allow_odds,
                        )
                    except Exception as e:
                        log.warning(f"[analyze] failed {league} {home}-{away}: {e}")

                    mark_job(job_key)

        # 512MB için: sık döngü yapma
        await asyncio.sleep(float(os.getenv("LOOP_SLEEP_SECONDS", "30")))


if __name__ == "__main__":
    asyncio.run(main())

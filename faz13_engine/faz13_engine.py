# faz13_engine/faz13_engine.py
from __future__ import annotations

import asyncio
import html
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from baseline.team_baseline_store import (
    TeamBaselineStore,
    TeamBaselineBootstrapper,
    TeamStatsAdapter,
    TeamBaseline,
)
from league_profiles import get_league_profile


# =========================
# DATA STRUCTURES
# =========================

@dataclass(frozen=True)
class PrematchRequest:
    fixture_id: int
    league: str
    date_str: str
    home: str
    away: str


@dataclass
class TeamAverages:
    points_for: float
    points_against: float
    pace_hint: float
    stdev_hint: float


@dataclass
class FixtureContext:
    league: str
    date: str
    home: str
    away: str


@dataclass
class Faz13CoreOutput:
    ctx: FixtureContext
    home_avg: TeamAverages
    away_avg: TeamAverages
    total_band: Tuple[int, int]
    home_band: Tuple[int, int]
    away_band: Tuple[int, int]
    ou_direction: str
    quarters: Dict[str, Tuple[int, int]]
    blowout_risk: str
    tempo_flag: str
    notes: List[str] = field(default_factory=list)
    market: Dict[str, Any] = field(default_factory=dict)
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        # baseline_store/local/statistics/games_last5/balldontlie -> valid
        return (
            self.meta.get("home_baseline_src") not in (None, "none")
            and self.meta.get("away_baseline_src") not in (None, "none")
        )

    def render_html(self) -> str:
        esc = html.escape
        lines: List[str] = []
        lines.append("FAZ-13 Ön Analiz")
        lines.append(
            f"Maç: {esc(self.ctx.home)} vs {esc(self.ctx.away)} | "
            f"Lig: {esc(self.ctx.league)} | Tarih: {esc(self.ctx.date)}"
        )
        lines.append("")
        lines.append("Dar Bant")
        lines.append(f"• Toplam: {self.total_band[0]}–{self.total_band[1]}")
        lines.append(
            f"• Ev: {self.home_band[0]}–{self.home_band[1]} | Dep: {self.away_band[0]}–{self.away_band[1]}"
        )
        lines.append(f"• Alt/Üst yönü: {esc(self.ou_direction)}")
        lines.append("")
        lines.append("Periyot Bantları")
        for k in ["1Q", "2Q", "HT", "3Q", "4Q", "FT"]:
            if k in self.quarters:
                lo, hi = self.quarters[k]
                lines.append(f"• {k}: {lo}–{hi}")
        lines.append("")
        lines.append("Risk Göstergeleri")
        lines.append(f"• Blowout riski: {esc(self.blowout_risk)}")
        lines.append(f"• Tempo flag: {esc(self.tempo_flag)}")

        if self.notes:
            lines.append("")
            lines.append("Notlar")
            for n in self.notes:
                lines.append(f"• {esc(n)}")

        if self.market:
            lines.append("")
            lines.append("Market Entegrasyonu")
            for k, v in self.market.items():
                lines.append(f"• {esc(str(k))}: {esc(str(v))}")

        if self.meta:
            lines.append("")
            lines.append("Meta Skor")
            for k, v in self.meta.items():
                lines.append(f"• {esc(str(k))}: {esc(str(v))}")

        lines.append("")
        lines.append("Bu çıktı analiz/simülasyon amaçlıdır. Bahis tavsiyesi değildir.")
        return "\n".join(lines)


# =========================
# HELPERS
# =========================

class _TTLCache:
    def __init__(self, ttl_sec: float = 25.0) -> None:
        self.ttl = ttl_sec
        self._data: Dict[str, Tuple[float, Any]] = {}

    def get(self, key: str) -> Any:
        hit = self._data.get(key)
        if not hit:
            return None
        ts, val = hit
        if time.time() - ts > self.ttl:
            self._data.pop(key, None)
            return None
        return val

    def set(self, key: str, value: Any) -> None:
        self._data[key] = (time.time(), value)


# =========================
# ENGINE
# =========================

class Faz13Engine:
    """
    PROD UYUMLU FAZ-13
    - dynamic_scheduler.py / main.py uyumlu __init__ imzası
    - NBA season fix (calendar year != NBA season year)
    - BallDontLie baseline (min 12 game) -> 90 toplam saçmalığı biter
    - baseline_store (FAZ-11 öğrenme) entegrasyonu
    - API-Sports statistics + games_last5 fallback
    """

    def __init__(
        self,
        api_sports_key: str,
        api_sports_base: str,
        baseline_store: Optional[TeamBaselineStore] = None,
        min_baseline_games: int = 6,
    ) -> None:
        self.api_key = (api_sports_key or "").strip()
        self.base = (api_sports_base or "https://v1.basketball.api-sports.io").rstrip("/")
        self.session: Optional[aiohttp.ClientSession] = None
        self.cache = _TTLCache()

        # leagues.json -> league name -> api_sports_league_id
        self._league_id_map: Dict[str, int] = self._load_league_id_map()

        # optional baseline store for learning loop
        self.baseline_store = baseline_store
        self.min_baseline_games = int(min_baseline_games) if min_baseline_games else 6

        # local stats (optional file)
        self._team_stats: Dict[str, Dict[str, Any]] = {}
        stats_path = os.environ.get("TEAM_STATS_FILE") or "team_stats.json"
        try:
            if os.path.exists(stats_path):
                with open(stats_path, "r", encoding="utf-8") as f:
                    self._team_stats = json.load(f) or {}
        except Exception:
            self._team_stats = {}

        # baseline bootstrapper adapter (local stats -> store)
        self.baseline_bootstrapper: Optional[TeamBaselineBootstrapper] = None
        if self.baseline_store is not None:

            class _LocalStatsAdapter(TeamStatsAdapter):
                def __init__(self, dataset: Dict[str, Dict[str, Any]]):
                    self.dataset = dataset

                def fetch_team_recent_aggregate(
                    self, league: str, team: str, n_games: int
                ) -> Optional[Dict[str, Any]]:
                    if not self.dataset:
                        return None
                    try:
                        season = sorted(self.dataset.keys())[-1]
                    except Exception:
                        return None
                    season_data = self.dataset.get(season, {}) or {}
                    rec = None
                    for nm, data in season_data.items():
                        if (nm or "").lower().strip() == team.lower().strip():
                            rec = data
                            break
                    if rec is None:
                        return None
                    try:
                        pf = float(rec.get("points_for", 0.0))
                        pa = float(rec.get("points_against", 0.0))
                    except Exception:
                        return None
                    pace = rec.get("pace")
                    if pace is None:
                        pace = (pf + pa) / 180.0 if (pf + pa) > 0 else 1.0
                    stdev_total = rec.get("stdev")
                    if stdev_total is None:
                        stdev_total = 9.0
                    return {
                        "n_games": int(rec.get("games", n_games)),
                        "pts_for": pf,
                        "pts_against": pa,
                        "pace": float(pace),
                        "stdev_total": float(stdev_total),
                    }

            self.baseline_bootstrapper = TeamBaselineBootstrapper(
                self.baseline_store, _LocalStatsAdapter(self._team_stats)
            )

        # BallDontLie (NBA)
        self._bdl_team_map: Optional[Dict[str, int]] = None

    # =========================
    # NBA SEASON FIX
    # =========================
    def _season_for_league(self, league: str, date_str: str) -> str:
        """
        NBA season rule:
          - Oct-Dec: season = year
          - Jan-Sep: season = year-1
        Others: season = year
        """
        try:
            y = int(str(date_str)[:4])
            m = int(str(date_str)[5:7])
        except Exception:
            return str(date_str).split("-")[0]

        profile = get_league_profile(league)
        if profile.name.upper() == "NBA":
            season_year = y if m >= 10 else (y - 1)
            return str(season_year)
        return str(y)

    # =========================
    # sessions
    # =========================
    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session and not self.session.closed:
            return self.session
        self.session = aiohttp.ClientSession()
        return self.session

    async def aclose(self) -> None:
        if self.session and not self.session.closed:
            await self.session.close()

    # =========================
    # league id map
    # =========================
    def _load_league_id_map(self) -> Dict[str, int]:
        """
        leagues.json beklenen format:
          [ {"name":"NBA","api_sports_league_id":12}, ...]
        """
        candidates = [
            "leagues.json",
            os.path.join(os.path.dirname(__file__), "..", "..", "leagues.json"),
            os.path.join(os.path.dirname(__file__), "..", "leagues.json"),
        ]
        for p in candidates:
            p = os.path.normpath(p)
            try:
                if os.path.exists(p):
                    with open(p, "r", encoding="utf-8") as f:
                        arr = json.load(f)
                    out: Dict[str, int] = {}
                    if isinstance(arr, list):
                        for item in arr:
                            if not isinstance(item, dict):
                                continue
                            name = (item.get("name") or "").strip().upper()
                            lid = item.get("api_sports_league_id")
                            if name and isinstance(lid, int):
                                out[name] = lid
                    if out:
                        return out
            except Exception:
                continue
        return {}

    def _league_to_id(self, league: str) -> Optional[int]:
        s = (league or "").strip()
        if not s:
            return None
        if s.isdigit():
            return int(s)
        return self._league_id_map.get(s.upper())

    # =========================
    # API-Sports GET
    # =========================
    async def _api_get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        key = f"{path}?{json.dumps(params, sort_keys=True)}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached

        s = await self._get_session()
        headers = {"x-apisports-key": self.api_key}

        for attempt in range(4):
            try:
                async with s.get(
                    f"{self.base}{path}",
                    params=params,
                    headers=headers,
                    timeout=15,
                ) as resp:
                    data = await resp.json()
                    if resp.status >= 500:
                        raise RuntimeError(f"API-Sports error {resp.status}")
                    self.cache.set(key, data)
                    return data
            except Exception:
                await asyncio.sleep(0.3 * (2**attempt))

        raise RuntimeError("API-Sports request failed")

    @staticmethod
    def _dig(obj: Any, path: List[str]) -> Optional[float]:
        cur = obj
        for p in path:
            if not isinstance(cur, dict) or p not in cur:
                return None
            cur = cur[p]
        try:
            return float(cur)
        except Exception:
            return None

    # =========================
    # BallDontLie helpers
    # =========================
    async def _bdl_get(self, url: str, params: Dict[str, Any]) -> Dict[str, Any]:
        api_key = (os.getenv("BALLDONTLIE_API_KEY") or "").strip()
        if not api_key:
            raise RuntimeError("BALLDONTLIE_API_KEY missing")
        s = await self._get_session()
        headers = {"Authorization": api_key}
        async with s.get(url, params=params, headers=headers, timeout=20) as resp:
            data = await resp.json()
            if resp.status >= 400:
                raise RuntimeError(f"BallDontLie error {resp.status}: {data}")
            return data

    async def _bdl_load_team_map(self) -> Dict[str, int]:
        if self._bdl_team_map is not None:
            return self._bdl_team_map
        js = await self._bdl_get("https://api.balldontlie.io/nba/v1/teams", {"per_page": 100})
        out: Dict[str, int] = {}
        for t in js.get("data", []) or []:
            if not isinstance(t, dict):
                continue
            tid = t.get("id")
            if not isinstance(tid, int):
                continue
            full_name = (t.get("full_name") or "").strip().lower()
            name = (t.get("name") or "").strip().lower()
            if full_name:
                out[full_name] = tid
            if name:
                out[name] = tid
        self._bdl_team_map = out
        return out

    async def _bdl_team_baseline(
        self, team: str, season: str, profile_name: str
    ) -> Optional[Tuple[float, float, float, float, int]]:
        """
        NBA baseline from BallDontLie /games.
        ✅ FIX:
          - games listesi tarihe göre sıralanır
          - en güncel tamamlanmış maçlardan min 12 örnek alınır
        """
        if profile_name.upper() != "NBA":
            return None

        try:
            team_map = await self._bdl_load_team_map()
        except Exception:
            return None

        tid = team_map.get(team.strip().lower())
        if not tid:
            return None

        try:
            year = int(season)
        except Exception:
            return None

        try:
            js = await self._bdl_get(
                "https://api.balldontlie.io/nba/v1/games",
                {"seasons[]": year, "team_ids[]": tid, "per_page": 100},
            )
        except Exception:
            return None

        games = js.get("data") or []
        if not isinstance(games, list) or not games:
            return None

        # ✅ newest first
        games = sorted(games, key=lambda g: str((g or {}).get("date") or ""), reverse=True)

        scored: List[float] = []
        allowed: List[float] = []
        totals: List[float] = []

        need_n = max(self.min_baseline_games, 12)

        for g in games:
            if not isinstance(g, dict):
                continue
            hs = g.get("home_team_score")
            vs = g.get("visitor_team_score")
            if hs is None or vs is None:
                continue

            ht = g.get("home_team") or {}
            vt = g.get("visitor_team") or {}
            hid = ht.get("id")
            vid = vt.get("id")
            if hid is None or vid is None:
                continue

            if hid == tid:
                scored.append(float(hs))
                allowed.append(float(vs))
            elif vid == tid:
                scored.append(float(vs))
                allowed.append(float(hs))
            else:
                continue

            totals.append(float(hs) + float(vs))

            if len(scored) >= need_n:
                break

        if len(scored) < need_n:
            return None

        pf = sum(scored) / len(scored)
        pa = sum(allowed) / len(allowed)
        pace = (pf + pa) / 180.0 if (pf + pa) > 0 else 1.0
        pace = max(0.70, min(1.35, pace))

        mean_total = sum(totals) / len(totals)
        var = sum((x - mean_total) ** 2 for x in totals) / max(1, (len(totals) - 1))
        stdev_total = var ** 0.5

        return pf, pa, pace, stdev_total, len(scored)

    # =========================
    # baseline chain
    # =========================
    async def _team_baseline(self, team: str, league: str, season: str) -> Tuple[TeamAverages, str, int]:
        profile = get_league_profile(league)

        # 1) baseline_store (varsa)
        if self.baseline_store is not None:
            try:
                bl = self.baseline_store.get(league, team)
            except Exception:
                bl = None

            if bl and getattr(bl, "n_games", 0) >= self.min_baseline_games:
                stdev = float(getattr(bl, "stdev_total", 9.0))
                stdev = max(profile.volatility_floor, min(profile.volatility_ceil, stdev))
                pace = float(getattr(bl, "pace", 1.0))
                pace = max(0.70, min(1.35, pace * profile.pace_scale))
                return TeamAverages(float(bl.pts_for), float(bl.pts_against), pace, stdev), "baseline_store", int(bl.n_games)

            # store boşsa bootstrapper ile doldurmaya çalış
            if self.baseline_bootstrapper is not None:
                try:
                    new_bl = self.baseline_bootstrapper.ensure(
                        league, team, min_games=self.min_baseline_games
                    )
                except Exception:
                    new_bl = None

                if new_bl and getattr(new_bl, "n_games", 0) >= self.min_baseline_games:
                    stdev = float(getattr(new_bl, "stdev_total", 9.0))
                    stdev = max(profile.volatility_floor, min(profile.volatility_ceil, stdev))
                    pace = float(getattr(new_bl, "pace", 1.0))
                    pace = max(0.70, min(1.35, pace * profile.pace_scale))
                    return TeamAverages(float(new_bl.pts_for), float(new_bl.pts_against), pace, stdev), "baseline_store", int(new_bl.n_games)

        # 2) local stats (varsa)
        local = self._team_stats.get(season)
        if isinstance(local, dict) and local:
            for nm, rec in local.items():
                if (nm or "").lower().strip() == team.lower().strip():
                    try:
                        pf = float(rec.get("points_for", 0.0))
                        pa = float(rec.get("points_against", 0.0))
                    except Exception:
                        pf = pa = 0.0
                    pace = rec.get("pace")
                    if pace is None:
                        pace = max(0.70, min(1.35, (pf + pa) / 180.0)) if (pf + pa) > 0 else 1.0
                    stdev = 9.0
                    if isinstance(rec.get("stdev"), (int, float)):
                        stdev = float(rec["stdev"])
                    stdev = max(profile.volatility_floor, min(profile.volatility_ceil, stdev))
                    return TeamAverages(pf, pa, float(pace), stdev), "local", int(rec.get("games", 0))

        # 3) API-Sports statistics (league id şart)
        league_id = self._league_to_id(league)
        team_id = None

        try:
            res = await self._api_get("/teams", {"search": team})
            t_resp = res.get("response") or []
            if t_resp:
                for t in t_resp:
                    nm = (t.get("name") or "").strip().lower()
                    if nm == team.lower().strip():
                        team_id = int(t.get("id"))
                        break
                if team_id is None:
                    team_id = int(t_resp[0]["id"])
        except Exception:
            team_id = None

        if team_id is not None and league_id is not None:
            try:
                stats = await self._api_get("/statistics", {"team": team_id, "league": league_id, "season": season})
                r = stats.get("response") or {}
                pf = self._dig(r, ["points", "for", "average", "total"])
                pa = self._dig(r, ["points", "against", "average", "total"])
                if pf is not None and pa is not None:
                    pace = max(0.85, min(1.20, (pf + pa) / 180.0))
                    pace = max(0.70, min(1.35, pace * profile.pace_scale))
                    stdev = max(profile.volatility_floor, min(profile.volatility_ceil, 9.0))
                    return TeamAverages(pf, pa, pace, stdev), "statistics", 0
            except Exception:
                pass

        # 4) API-Sports last5/lastN
        if team_id is not None:
            try:
                games = await self._api_get("/games", {"team": team_id, "last": 10})
                resp = games.get("response") or []
                scored: List[float] = []
                allowed: List[float] = []
                totals: List[float] = []
                for g in resp:
                    s = g.get("scores") or {}
                    h = s.get("home") or {}
                    a = s.get("away") or {}
                    ht = h.get("total")
                    at = a.get("total")
                    if ht is None or at is None:
                        continue
                    teams = g.get("teams") or {}
                    hn = ((teams.get("home") or {}).get("name") or "").strip().lower()
                    an = ((teams.get("away") or {}).get("name") or "").strip().lower()

                    if hn == team.lower().strip():
                        scored.append(float(ht)); allowed.append(float(at))
                    elif an == team.lower().strip():
                        scored.append(float(at)); allowed.append(float(ht))
                    else:
                        continue
                    totals.append(float(ht) + float(at))
                    if len(scored) >= max(self.min_baseline_games, 8):
                        break

                if scored and allowed and len(scored) >= max(4, min(self.min_baseline_games, 8)):
                    pf = sum(scored) / len(scored)
                    pa = sum(allowed) / len(allowed)
                    pace = max(0.85, min(1.20, (pf + pa) / 180.0))
                    pace = max(0.70, min(1.35, pace * profile.pace_scale))

                    stdev = 9.0
                    if len(totals) >= 4:
                        mean_total = sum(totals) / len(totals)
                        var = sum((x - mean_total) ** 2 for x in totals) / max(1, (len(totals) - 1))
                        stdev = var ** 0.5
                    stdev = max(profile.volatility_floor, min(profile.volatility_ceil, stdev))
                    return TeamAverages(pf, pa, pace, stdev), "games_lastN", len(scored)
            except Exception:
                pass

        # 5) BallDontLie fallback (NBA)
        bdl = await self._bdl_team_baseline(team=team, season=season, profile_name=profile.name)
        if bdl is not None:
            pf, pa, pace, stdev_total, n_games = bdl
            stdev_total = max(profile.volatility_floor, min(profile.volatility_ceil, stdev_total))
            pace = max(0.70, min(1.35, pace * profile.pace_scale))
            return TeamAverages(pf, pa, pace, stdev_total), "balldontlie", n_games

        # 6) none -> neutral baseline
        return TeamAverages(0.0, 0.0, 1.0, 9.0), "none", 0

    # =========================
    # prematch runner
    # =========================
    async def run_prematch(self, req: PrematchRequest) -> Faz13CoreOutput:
        profile = get_league_profile(req.league)
        season = self._season_for_league(req.league, req.date_str)

        (h_avg, h_src, h_n), (a_avg, a_src, a_n) = await asyncio.gather(
            self._team_baseline(req.home, req.league, season),
            self._team_baseline(req.away, req.league, season),
        )

        home_mu = (h_avg.points_for + a_avg.points_against) / 2
        away_mu = (a_avg.points_for + h_avg.points_against) / 2
        total_mu = home_mu + away_mu

        sigma = (h_avg.stdev_hint + a_avg.stdev_hint) / 2
        sigma = max(profile.volatility_floor, min(profile.volatility_ceil, sigma))

        pace = (h_avg.pace_hint + a_avg.pace_hint) / 2
        tempo_flag = "NORMAL"
        if pace > 1.12 and sigma < 9.0:
            tempo_flag = "FAKE_TEMPO_RISK"
        elif pace > 1.05:
            tempo_flag = "FAST"
        elif pace < 0.95:
            tempo_flag = "SLOW"

        gap = abs(home_mu - away_mu)
        blowout = "HIGH" if gap >= 12 else "MID" if gap >= 7 else "LOW"

        hw_total = profile.band_hw_total
        hw_team = profile.band_hw_team

        total_band = (int(round(total_mu - hw_total)), int(round(total_mu + hw_total)))
        home_band = (int(round(home_mu - hw_team)), int(round(home_mu + hw_team)))
        away_band = (int(round(away_mu - hw_team)), int(round(away_mu + hw_team)))

        ou_dir = "NO_EDGE"
        if tempo_flag in {"SLOW", "FAKE_TEMPO_RISK"} and blowout in {"MID", "HIGH"}:
            ou_dir = "ALT"
        elif tempo_flag == "FAST" and blowout == "LOW":
            ou_dir = "UST"

        quarters = self._quarter_bands(total_mu, hw_total)

        notes = [
            f"Profile: {profile.name}",
            f"Season: {season}",
            f"Baseline(home)={h_src} n={h_n} | Baseline(away)={a_src} n={a_n}",
            f"μ(total)≈{total_mu:.1f}, σ≈{sigma:.1f}, pace≈{pace:.2f}",
            f"gap≈{gap:.1f} → blowout={blowout}",
        ]
        if h_src == "none" or a_src == "none":
            notes.append("UYARI: Team baseline alınamadı → neutral baseline (0/0) kullanıldı.")
        if profile.name.upper() == "NBA" and (h_src == "balldontlie" or a_src == "balldontlie"):
            notes.append("Bilgi: NBA için BallDontLie baseline devrede.")

        ctx = FixtureContext(req.league, req.date_str, req.home, req.away)
        meta = {
            "league_profile": profile.name,
            "season": season,
            "home_baseline_src": h_src,
            "home_baseline_n": h_n,
            "away_baseline_src": a_src,
            "away_baseline_n": a_n,
        }

        return Faz13CoreOutput(
            ctx=ctx,
            home_avg=h_avg,
            away_avg=a_avg,
            total_band=total_band,
            home_band=home_band,
            away_band=away_band,
            ou_direction=ou_dir,
            quarters=quarters,
            blowout_risk=blowout,
            tempo_flag=tempo_flag,
            notes=notes,
            market={},
            meta=meta,
        )

    @staticmethod
    def _quarter_bands(total_mu: float, hw_total: int) -> Dict[str, Tuple[int, int]]:
        splits = {"1Q": 0.24, "2Q": 0.26, "3Q": 0.25, "4Q": 0.25}
        out: Dict[str, Tuple[int, int]] = {}
        for k, w in splits.items():
            mu = total_mu * w
            hw = max(2, int(round(hw_total * w)))
            out[k] = (int(round(mu - hw)), int(round(mu + hw)))
        out["HT"] = (out["1Q"][0] + out["2Q"][0], out["1Q"][1] + out["2Q"][1])
        out["FT"] = (int(round(total_mu - hw_total)), int(round(total_mu + hw_total)))
        return out

    # =========================================================
    # ✅ FAZ-11 LEARNING HOOKS (baseline_store update)
    # =========================================================
    def faz11_build_feedback_event(
        self,
        league: str,
        date_str: str,
        home: str,
        away: str,
        final_home: int,
        final_away: int,
        prematch: Optional[Faz13CoreOutput] = None,
    ) -> Dict[str, Any]:
        """
        FAZ-11’in tüketebileceği net bir olay paketi.
        (Bu fonksiyon sadece veri paketler; FAZ-11 motoru ister loglar ister store’a yazar.)
        """
        season = self._season_for_league(league, date_str)
        event = {
            "phase": "FAZ11_FEEDBACK",
            "league": league,
            "season": season,
            "date": date_str,
            "home": home,
            "away": away,
            "final_home": int(final_home),
            "final_away": int(final_away),
            "final_total": int(final_home) + int(final_away),
            "ts": time.time(),
        }
        if prematch is not None:
            event["prematch_meta"] = dict(prematch.meta or {})
            event["prematch_total_band"] = list(prematch.total_band)
            event["prematch_home_band"] = list(prematch.home_band)
            event["prematch_away_band"] = list(prematch.away_band)
        return event

    def faz11_update_baseline_store(
        self,
        league: str,
        team: str,
        pts_for: float,
        pts_against: float,
        pace: float,
        stdev_total: float,
        n_games_add: int = 1,
    ) -> bool:
        """
        baseline_store varsa: takım baseline’ını günceller.
        Bu “gerçek öğrenme” kısmı: maç sonu gerçek skorlar geldikçe store iyileşir.

        Not: TeamBaselineStore implementasyonları değişebilir.
        Bu yüzden set/upsert/save gibi yöntemleri best-effort dener.
        """
        if self.baseline_store is None:
            return False

        # mevcut baseline çek
        try:
            cur = self.baseline_store.get(league, team)
        except Exception:
            cur = None

        # yeni değerleri “running average” olarak birleştir
        if cur and hasattr(cur, "n_games") and int(getattr(cur, "n_games", 0)) > 0:
            n0 = int(getattr(cur, "n_games", 0))
            n1 = max(1, int(n_games_add))
            n = n0 + n1

            pf0 = float(getattr(cur, "pts_for", getattr(cur, "pts_for", 0.0)))
            pa0 = float(getattr(cur, "pts_against", getattr(cur, "pts_against", 0.0)))
            pace0 = float(getattr(cur, "pace", 1.0))
            st0 = float(getattr(cur, "stdev_total", 9.0))

            pf = (pf0 * n0 + float(pts_for) * n1) / n
            pa = (pa0 * n0 + float(pts_against) * n1) / n
            pace_new = (pace0 * n0 + float(pace) * n1) / n
            st_new = (st0 * n0 + float(stdev_total) * n1) / n
            n_games = n
        else:
            pf = float(pts_for)
            pa = float(pts_against)
            pace_new = float(pace)
            st_new = float(stdev_total)
            n_games = max(1, int(n_games_add))

        # store’a yaz (best effort)
        try:
            # TeamBaseline dataclass ise direkt oluştur
            new_bl = TeamBaseline(
                league=league,
                team=team,
                pts_for=pf,
                pts_against=pa,
                pace=pace_new,
                stdev_total=st_new,
                n_games=n_games,
            )
        except Exception:
            # farklı imza varsa dict ile dene
            new_bl = {
                "league": league,
                "team": team,
                "pts_for": pf,
                "pts_against": pa,
                "pace": pace_new,
                "stdev_total": st_new,
                "n_games": n_games,
            }

        # olası metod isimleri: set / upsert / save / put
        for method_name in ("set", "upsert", "save", "put"):
            fn = getattr(self.baseline_store, method_name, None)
            if callable(fn):
                try:
                    fn(new_bl)  # bazı store’lar objeyi tek parametre ister
                    return True
                except TypeError:
                    try:
                        fn(league, team, new_bl)  # bazıları ayrı parametre ister
                        return True
                    except Exception:
                        pass
                except Exception:
                    pass

        return False

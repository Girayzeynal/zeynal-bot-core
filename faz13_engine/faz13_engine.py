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
        return (
            self.meta.get("home_baseline_src") not in (None, "none")
            and self.meta.get("away_baseline_src") not in (None, "none")
        )

    def render_html(self) -> str:
        esc = html.escape
        lines: List[str] = []
        lines.append("FAZ-13 Ön Analiz")
        lines.append(
            f"Maç: {esc(self.ctx.home)} vs {esc(self.ctx.away)} | Lig: {esc(self.ctx.league)} | Tarih: {esc(self.ctx.date)}"
        )
        lines.append("")
        lines.append("Dar Bant")
        lines.append(f"• Toplam: {self.total_band[0]}–{self.total_band[1]}")
        lines.append(f"• Ev: {self.home_band[0]}–{self.home_band[1]} | Dep: {self.away_band[0]}–{self.away_band[1]}")
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


class Faz13Engine:
    """
    Baseline zinciri:
      1) baseline_store
      2) local team_stats.json
      3) API-Sports /statistics
      4) API-Sports /games lastN
      5) BallDontLie fallback (NBA)
      6) none -> neutral baseline
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

        self._league_id_map: Dict[str, int] = self._load_league_id_map()

        self._team_stats: Dict[str, Dict[str, Any]] = {}
        stats_path = os.environ.get("TEAM_STATS_FILE") or "team_stats.json"
        try:
            if os.path.exists(stats_path):
                with open(stats_path, "r", encoding="utf-8") as f:
                    self._team_stats = json.load(f)
        except Exception:
            self._team_stats = {}

        self.baseline_store = baseline_store
        self.min_baseline_games = int(min_baseline_games) if min_baseline_games else 6
        self.baseline_bootstrapper: Optional[TeamBaselineBootstrapper] = None

        if self.baseline_store is not None:
            class _LocalStatsAdapter(TeamStatsAdapter):
                def __init__(self, dataset: Dict[str, Dict[str, Any]]):
                    self.dataset = dataset

                def fetch_team_recent_aggregate(self, league: str, team: str, n_games: int) -> Optional[Dict[str, Any]]:
                    if not self.dataset:
                        return None
                    season = sorted(self.dataset.keys())[-1]
                    season_data = self.dataset.get(season, {})
                    rec = None
                    for nm, data in season_data.items():
                        if (nm or "").lower().strip() == team.lower().strip():
                            rec = data
                            break
                    if rec is None:
                        return None

                    pf = float(rec.get("points_for", 0.0))
                    pa = float(rec.get("points_against", 0.0))
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

            self.baseline_adapter = _LocalStatsAdapter(self._team_stats)
            self.baseline_bootstrapper = TeamBaselineBootstrapper(self.baseline_store, self.baseline_adapter)

        self._bdl_team_map: Optional[Dict[str, int]] = None  # name->id

    # -----------------------------
    # NBA SEASON FIX (2025–26)
    # -----------------------------
    def _season_for_league(self, league: str, date_str: str) -> str:
        """
        NBA season:
          Oct-Dec -> season = year
          Jan-Sep -> season = year-1
        """
        try:
            y = int(date_str[:4])
            m = int(date_str[5:7])
        except Exception:
            return date_str.split("-")[0]

        if (league or "").upper() == "NBA":
            return str(y if m >= 10 else (y - 1))
        return str(y)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session and not self.session.closed:
            return self.session
        self.session = aiohttp.ClientSession()
        return self.session

    def _load_league_id_map(self) -> Dict[str, int]:
        candidates = [
            "leagues.json",
            os.path.join(os.path.dirname(__file__), "..", "..", "leagues.json"),
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

    async def _api_get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        key = f"{path}?{json.dumps(params, sort_keys=True)}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached

        s = await self._get_session()
        headers = {"x-apisports-key": self.api_key}

        for attempt in range(4):
            try:
                async with s.get(f"{self.base}{path}", params=params, headers=headers, timeout=15) as resp:
                    data = await resp.json()
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

    # -----------------------------
    # BallDontLie helpers
    # -----------------------------
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

    async def _bdl_team_baseline(self, team: str, season: str, profile_name: str) -> Optional[Tuple[float, float, float, float, int]]:
        if profile_name.upper() != "NBA":
            return None

        team_map = await self._bdl_load_team_map()
        tid = team_map.get(team.strip().lower())
        if not tid:
            return None

        year = int(season)
        js = await self._bdl_get(
            "https://api.balldontlie.io/nba/v1/games",
            {"seasons[]": year, "team_ids[]": tid, "per_page": 100},
        )
        games = js.get("data") or []
        if not isinstance(games, list) or not games:
            return None

        # ✅ newest first
        games = sorted(games, key=lambda g: str((g or {}).get("date") or ""), reverse=True)

        scored: List[float] = []
        allowed: List[float] = []
        totals: List[float] = []

        need_n = max(self.min_baseline_games, 12)  # ✅ NBA için min 12

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

    # -----------------------------
    # Baseline chain (kısaltılmış)
    # -----------------------------
    async def _team_baseline(self, team: str, league: str, season: str) -> Tuple[TeamAverages, str, int]:
        profile = get_league_profile(league)

        # 1) baseline_store
        if self.baseline_bootstrapper is not None and self.baseline_store is not None:
            bl = self.baseline_store.get(league, team)
            if bl and bl.n_games >= self.min_baseline_games:
                stdev = max(profile.volatility_floor, min(profile.volatility_ceil, bl.stdev_total))
                return TeamAverages(bl.pts_for, bl.pts_against, bl.pace, stdev), "baseline_store", bl.n_games

        # 2) local stats
        local = self._team_stats.get(season)
        if local:
            for nm, rec in local.items():
                if (nm or "").lower().strip() == team.lower().strip():
                    pf = float(rec.get("points_for", 0.0))
                    pa = float(rec.get("points_against", 0.0))
                    pace = rec.get("pace") or 1.0
                    stdev = float(rec.get("stdev", 9.0))
                    stdev = max(profile.volatility_floor, min(profile.volatility_ceil, stdev))
                    return TeamAverages(pf, pa, float(pace), stdev), "local", int(rec.get("games", 0))

        # 3) API-Sports statistics
        league_id = self._league_to_id(league)
        team_id = None

        try:
            res = await self._api_get("/teams", {"search": team})
            t_resp = res.get("response") or []
            if t_resp:
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
                    stdev = max(profile.volatility_floor, min(profile.volatility_ceil, 9.0))
                    return TeamAverages(pf, pa, pace, stdev), "statistics", 5
            except Exception:
                pass

        # 4) BallDontLie fallback (NBA)
        bdl = await self._bdl_team_baseline(team=team, season=season, profile_name=profile.name)
        if bdl is not None:
            pf, pa, pace, stdev_total, n_games = bdl
            stdev_total = max(profile.volatility_floor, min(profile.volatility_ceil, stdev_total))
            pace = max(0.70, min(1.35, pace * profile.pace_scale))
            return TeamAverages(pf, pa, pace, stdev_total), "balldontlie", n_games

        return TeamAverages(0.0, 0.0, 1.0, 9.0), "none", 0

    # -----------------------------
    # MAIN RUN (Prematch)
    # -----------------------------
    async def run_prematch(self, req: PrematchRequest) -> Faz13CoreOutput:
        profile = get_league_profile(req.league)
        season = self._season_for_league(req.league, req.date_str)  # ✅ NBA season fix

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
        else:
            if h_src == "balldontlie" or a_src == "balldontlie":
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

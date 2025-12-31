from __future__ import annotations

import asyncio
import html
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from baseline.team_baseline_store import TeamBaselineStore, TeamBaselineBootstrapper
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

    def render_html(self) -> str:
        esc = html.escape
        out: List[str] = []
        out.append("FAZ-13 Ön Analiz")
        out.append(
            f"Maç: {esc(self.ctx.home)} vs {esc(self.ctx.away)} | "
            f"Lig: {esc(self.ctx.league)} | Tarih: {esc(self.ctx.date)}"
        )
        out.append("")
        out.append("Dar Bant")
        out.append(f"• Toplam: {self.total_band[0]}–{self.total_band[1]}")
        out.append(
            f"• Ev: {self.home_band[0]}–{self.home_band[1]} | "
            f"Dep: {self.away_band[0]}–{self.away_band[1]}"
        )
        out.append(f"• Alt/Üst yönü: {esc(self.ou_direction)}")
        out.append("")
        out.append("Risk Göstergeleri")
        out.append(f"• Blowout riski: {esc(self.blowout_risk)}")
        out.append(f"• Tempo flag: {esc(self.tempo_flag)}")

        if self.notes:
            out.append("")
            out.append("Notlar")
            for n in self.notes:
                out.append(f"• {esc(n)}")

        if self.market:
            out.append("")
            out.append("Market Entegrasyonu")
            for k, v in self.market.items():
                out.append(f"• {esc(str(k))}: {esc(str(v))}")

        if self.meta:
            out.append("")
            out.append("Meta Skor")
            for k, v in self.meta.items():
                out.append(f"• {esc(str(k))}: {esc(str(v))}")

        out.append("")
        out.append("Bu çıktı analiz/simülasyon amaçlıdır. Bahis tavsiyesi değildir.")
        return "\n".join(out)


class _TTLCache:
    def __init__(self, ttl_sec: float = 30.0) -> None:
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

        self.baseline_store = baseline_store
        self.min_baseline_games = int(min_baseline_games)
        self.baseline_bootstrapper: Optional[TeamBaselineBootstrapper] = None

        if self.baseline_store is not None:
            # ❗ TeamStatsAdapter takes no args; None passed
            self.baseline_bootstrapper = TeamBaselineBootstrapper(self.baseline_store, None)

        self._bdl_team_map: Optional[Dict[str, int]] = None

    @staticmethod
    def resolve_nba_season(date_str: str) -> str:
        try:
            y = int(date_str[:4])
            m = int(date_str[5:7])
        except Exception:
            return date_str[:4]
        # 🎯 NBA: Ekim → sezon = next year
        if m >= 10:
            return str(y + 1)
        return str(y)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session and not self.session.closed:
            return self.session
        self.session = aiohttp.ClientSession()
        return self.session

    async def _bdl_get(self, url: str, params: Dict[str, Any]) -> Dict[str, Any]:
        api_key = (os.getenv("BALLDONTLIE_API_KEY") or "").strip()
        if not api_key:
            raise RuntimeError("BALLDONTLIE_API_KEY missing")

        s = await self._get_session()
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        }
        async with s.get(url, params=params, headers=headers, timeout=20) as resp:
            ct = resp.headers.get("Content-Type", "")
            if "application/json" not in ct:
                text = await resp.text()
                raise RuntimeError(
                    f"BallDontLie unauthorized or invalid response "
                    f"(status={resp.status}, content-type={ct}): {text[:200]}"
                )
            data = await resp.json()
            if resp.status >= 400:
                raise RuntimeError(f"BallDontLie error {resp.status}: {data}")
            return data

    async def _bdl_load_team_map(self) -> Dict[str, int]:
        if self._bdl_team_map is not None:
            return self._bdl_team_map
        js = await self._bdl_get("https://api.balldontlie.io/nba/v1/teams", {"per_page": 100})
        out: Dict[str, int] = {}
        for t in js.get("data", []):
            tid = t.get("id")
            if not isinstance(tid, int):
                continue
            full = (t.get("full_name") or "").lower().strip()
            short = (t.get("name") or "").lower().strip()
            if full:
                out[full] = tid
            if short:
                out[short] = tid
        self._bdl_team_map = out
        return out

    async def _bdl_team_baseline(self, team: str, season: str) -> Optional[Tuple[float, float, float, float, int]]:
        team_map = await self._bdl_load_team_map()
        tid = team_map.get(team.lower().strip())
        if not tid:
            return None
        year = int(season)
        js = await self._bdl_get(
            "https://api.balldontlie.io/nba/v1/games",
            {"seasons[]": year, "team_ids[]": tid, "per_page": 100},
        )
        games = sorted(js.get("data", []), key=lambda g: g.get("date", ""), reverse=True)
        scored, allowed, totals = [], [], []
        need_n = max(12, self.min_baseline_games)
        for g in games:
            hs = g.get("home_team_score")
            vs = g.get("visitor_team_score")
            if hs is None or vs is None:
                continue
            hid = g["home_team"]["id"]
            vid = g["visitor_team"]["id"]
            if hid == tid:
                scored.append(hs)
                allowed.append(vs)
            elif vid == tid:
                scored.append(vs)
                allowed.append(hs)
            else:
                continue
            totals.append(hs + vs)
            if len(scored) >= need_n:
                break
        if len(scored) < need_n:
            return None
        pf = sum(scored) / len(scored)
        pa = sum(allowed) / len(allowed)
        pace = max(0.8, min(1.3, (pf + pa) / 180.0))
        mean_total = sum(totals) / len(totals)
        var = sum((x - mean_total) ** 2 for x in totals) / max(1, len(totals) - 1)
        stdev = var ** 0.5
        return pf, pa, pace, stdev, len(scored)

    async def run_prematch(self, req: PrematchRequest) -> Faz13CoreOutput:
        profile = get_league_profile(req.league)

        if req.league.upper() == "NBA":
            season = self.resolve_nba_season(req.date_str)
        else:
            season = req.date_str[:4]

        h = await self._bdl_team_baseline(req.home, season)
        a = await self._bdl_team_baseline(req.away, season)

        if h:
            h_avg = TeamAverages(h[0], h[1], h[2], h[3])
            h_src, h_n = "balldontlie", h[4]
        else:
            h_avg = TeamAverages(0, 0, 1, 9)
            h_src, h_n = "none", 0

        if a:
            a_avg = TeamAverages(a[0], a[1], a[2], a[3])
            a_src, a_n = "balldontlie", a[4]
        else:
            a_avg = TeamAverages(0, 0, 1, 9)
            a_src, a_n = "none", 0

        home_mu = (h_avg.points_for + a_avg.points_against) / 2
        away_mu = (a_avg.points_for + h_avg.points_against) / 2
        total_mu = home_mu + away_mu

        hw = profile.band_hw_total
        total_band = (int(total_mu - hw), int(total_mu + hw))
        home_band = (int(home_mu - profile.band_hw_team), int(home_mu + profile.band_hw_team))
        away_band = (int(away_mu - profile.band_hw_team), int(away_mu + profile.band_hw_team))

        notes = [
            f"Season: {season}",
            f"Baseline(home)={h_src} n={h_n} | Baseline(away)={a_src} n={a_n}",
            f"μ(total)≈{total_mu:.1f}",
        ]

        ctx = FixtureContext(req.league, req.date_str, req.home, req.away)
        meta = {
            "season": season,
            "home_baseline_src": h_src,
            "away_baseline_src": a_src,
        }

        return Faz13CoreOutput(
            ctx=ctx,
            home_avg=h_avg,
            away_avg=a_avg,
            total_band=total_band,
            home_band=home_band,
            away_band=away_band,
            ou_direction="NO_EDGE",
            quarters={},
            blowout_risk="LOW",
            tempo_flag="NORMAL",
            notes=notes,
            market={},
            meta=meta,
            ) 

# faz13_engine.py
from __future__ import annotations

import asyncio
import time
import json
from dataclasses import dataclass
from typing import Dict, Tuple, Optional, List

import aiohttp


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
    notes: List[str]
    market: Dict
    meta: Dict

    def render_html(self) -> str:
        lines = []
        lines.append("<b>FAZ-13 Ön Analiz</b>")
        lines.append(f"Maç: {self.ctx.home} vs {self.ctx.away} | Lig: {self.ctx.league} | Tarih: {self.ctx.date}")
        lines.append("")
        lines.append("<b>Dar Bant</b>")
        lines.append(f"• Toplam: {self.total_band[0]}–{self.total_band[1]}")
        lines.append(f"• Ev: {self.home_band[0]}–{self.home_band[1]} | Dep: {self.away_band[0]}–{self.away_band[1]}")
        lines.append(f"• Alt/Üst yönü: {self.ou_direction}")
        lines.append("")
        lines.append("<b>Periyot Bantları</b>")
        for k, v in self.quarters.items():
            lines.append(f"• {k}: {v[0]}–{v[1]}")
        lines.append("")
        lines.append("<b>Risk Göstergeleri</b>")
        lines.append(f"• Blowout riski: {self.blowout_risk}")
        lines.append(f"• Tempo flag: {self.tempo_flag}")
        lines.append("")
        lines.append("<b>Notlar</b>")
        for n in self.notes:
            lines.append(f"• {n}")
        lines.append("")
        lines.append("<i>Bu çıktı analiz/simülasyon amaçlıdır. Bahis tavsiyesi değildir.</i>")
        return "\n".join(lines)


class _TTLCache:
    def __init__(self, ttl=30):
        self.ttl = ttl
        self.data = {}

    def get(self, k):
        v = self.data.get(k)
        if not v:
            return None
        t, val = v
        if time.time() - t > self.ttl:
            del self.data[k]
            return None
        return val

    def set(self, k, v):
        self.data[k] = (time.time(), v)


class Faz13Engine:
    def __init__(self, api_sports_key: str, api_sports_base: str):
        self.key = api_sports_key
        self.base = api_sports_base.rstrip("/")
        self.cache = _TTLCache()
        self.session: Optional[aiohttp.ClientSession] = None

    async def _session(self):
        if not self.session:
            self.session = aiohttp.ClientSession()
        return self.session

    async def _api_get(self, path: str, params: Dict):
        cache_key = f"{path}:{json.dumps(params, sort_keys=True)}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached
        s = await self._session()
        headers = {"x-apisports-key": self.key}
        async with s.get(f"{self.base}{path}", params=params, headers=headers) as r:
            data = await r.json()
            self.cache.set(cache_key, data)
            return data

    async def _team_stats(self, team: str, league: str, season: str) -> TeamAverages:
        # 1️⃣ statistics endpoint
        try:
            stats = await self._api_get(
                "/statistics",
                {"team": team, "league": league, "season": season}
            )
            pts_for = stats["response"]["points"]["for"]["average"]["total"]
            pts_against = stats["response"]["points"]["against"]["average"]["total"]
            pace = max(0.85, min(1.20, (pts_for + pts_against) / 180))
            return TeamAverages(pts_for, pts_against, pace, 9.0)
        except Exception:
            pass

        # 2️⃣ games fallback (son 5 maç)
        try:
            games = await self._api_get("/games", {"team": team, "last": 5})
            scored, allowed = [], []
            for g in games["response"]:
                s = g["scores"]
                if s["home"]["total"] is not None and s["away"]["total"] is not None:
                    scored.append(s["home"]["total"])
                    allowed.append(s["away"]["total"])
            pf = sum(scored) / len(scored)
            pa = sum(allowed) / len(allowed)
            pace = max(0.85, min(1.20, (pf + pa) / 180))
            return TeamAverages(pf, pa, pace, 9.0)
        except Exception:
            pass

        # 3️⃣ lig fallback (SON ÇARE)
        return TeamAverages(80.0, 80.0, 0.95, 9.0)

    async def run_prematch(self, req: PrematchRequest) -> Faz13CoreOutput:
        season = req.date_str.split("-")[0]
        home_avg, away_avg = await asyncio.gather(
            self._team_stats(req.home, req.league, season),
            self._team_stats(req.away, req.league, season)
        )

        home_mu = (home_avg.points_for + away_avg.points_against) / 2
        away_mu = (away_avg.points_for + home_avg.points_against) / 2
        total_mu = home_mu + away_mu

        hw = 6
        total_band = (round(total_mu - hw), round(total_mu + hw))
        home_band = (round(home_mu - 4), round(home_mu + 4))
        away_band = (round(away_mu - 4), round(away_mu + 4))

        tempo = "SLOW" if home_avg.pace_hint < 0.95 else "FAST"
        blowout = "LOW"

        quarters = {
            "1Q": (round(total_mu * 0.24) - 2, round(total_mu * 0.24) + 2),
            "2Q": (round(total_mu * 0.26) - 2, round(total_mu * 0.26) + 2),
            "HT": (home_band[0], home_band[1]),
            "3Q": (round(total_mu * 0.25) - 2, round(total_mu * 0.25) + 2),
            "4Q": (round(total_mu * 0.25) - 2, round(total_mu * 0.25) + 2),
            "FT": total_band,
        }

        notes = [
            f"μ(total)≈{total_mu:.1f}, pace≈{home_avg.pace_hint:.2f}",
            f"Skor yönü: ALT"
        ]

        return Faz13CoreOutput(
            ctx=FixtureContext(req.league, req.date_str, req.home, req.away),
            home_avg=home_avg,
            away_avg=away_avg,
            total_band=total_band,
            home_band=home_band,
            away_band=away_band,
            ou_direction="ALT",
            quarters=quarters,
            blowout_risk=blowout,
            tempo_flag=tempo,
            notes=notes,
            market={},
            meta={}
        )

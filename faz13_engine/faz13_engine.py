# faz13_engine/faz13_engine.py

from __future__ import annotations
import asyncio
import html
import json
import time
import os
import aiohttp
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from baseline.team_baseline_store import (
    TeamBaselineStore,
    TeamBaselineBootstrapper,
    TeamStatsAdapter,
    TeamBaseline,
)
from league_profiles import get_league_profile

@dataclass
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
class Faz13CoreOutput:
    ctx: Any
    home_avg: Any
    away_avg: Any
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
    is_valid: bool = True

    def render_html(self) -> str:
        esc = html.escape
        if not self.is_valid:
            return f"⚠️ <b>ANALİZ HATASI</b>\nMaç: {esc(self.ctx.home)} vs {esc(self.ctx.away)}\n<i>Nedeni: Baseline verisi bulunamadı.</i>"
        
        lines = [
            "<b>FAZ-13 Ön Analiz</b>",
            f"Maç: {esc(self.ctx.home)} vs {esc(self.ctx.away)} | Lig: {esc(self.ctx.league)}",
            f"• Toplam: {self.total_band[0]}–{self.total_band[1]}",
            f"• Alt/Üst yönü: {esc(self.ou_direction)}",
            f"• Risk: {esc(self.blowout_risk)}",
            "\n".join([f"• {esc(n)}" for n in self.notes])
        ]
        return "\n".join(lines)

class Faz13Engine:
    def __init__(self, api_sports_key: str, api_sports_base: str, baseline_store=None, min_baseline_games=6):
        self.api_key = api_sports_key
        self.base = api_sports_base.rstrip("/")
        self.session = None
        self._team_stats = self._load_stats()
        self.baseline_store = baseline_store
        self.min_baseline_games = min_baseline_games

    def _load_stats(self):
        path = os.environ.get("TEAM_STATS_FILE", "team_stats.json")
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f: return json.load(f)
        except: return {}
        return {}

    async def _team_baseline(self, team, league, season):
        t_clean = team.lower().strip()
        local_data = self._team_stats.get(season, {})
        for nm, rec in local_data.items():
            nm_clean = nm.lower().strip()
            if t_clean in nm_clean or nm_clean in t_clean:
                pf = float(rec.get("points_for", 0.0))
                pa = float(rec.get("points_against", 0.0))
                if pf == 0: continue
                return TeamAverages(pf, pa, rec.get("pace", 1.0), 9.0), "local", int(rec.get("games", 0))
        return None, "none", 0

    async def run_prematch(self, req: PrematchRequest) -> Faz13CoreOutput:
        season = req.date_str.split("-")[0]
        h_res, a_res = await asyncio.gather(
            self._team_baseline(req.home, req.league, season),
            self._team_baseline(req.away, req.league, season)
        )
        
        h_avg, h_src, h_n = h_res
        a_avg, a_src, a_n = a_res

        if not h_avg or not a_avg:
            return Faz13CoreOutput(ctx=req, home_avg=None, away_avg=None, total_band=(0,0), 
                                  home_band=(0,0), away_band=(0,0), ou_direction="ERR", 
                                  quarters={}, blowout_risk="N/A", tempo_flag="N/A", is_valid=False)

        # Hesaplamalar
        h_mu = (h_avg.points_for + a_avg.points_against) / 2
        a_mu = (a_avg.points_for + h_avg.points_against) / 2
        total_mu = h_mu + a_mu

        return Faz13CoreOutput(
            ctx=req,
            home_avg=h_avg,
            away_avg=a_avg,
            total_band=(int(total_mu-5), int(total_mu+5)),
            home_band=(int(h_mu-3), int(h_mu+3)),
            away_band=(int(a_mu-3), int(a_mu+3)),
            ou_direction="NEUTRAL",
            quarters={},
            blowout_risk="LOW",
            tempo_flag="NORMAL",
            notes=[f"Source: H:{h_src}({h_n}) A:{a_src}({a_n})"],
            meta={"home_baseline_src": h_src, "away_baseline_src": a_src, "home_baseline_n": h_n, "away_baseline_n": a_n},
            is_valid=True
        )


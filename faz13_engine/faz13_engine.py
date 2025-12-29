from __future__ import annotations
import asyncio
import html
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

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
    ctx: PrematchRequest
    home_avg: Optional[TeamAverages]
    away_avg: Optional[TeamAverages]
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
            return f"⚠️ <b>ANALİZ HATASI</b>\nMaç: {esc(self.ctx.home)} vs {esc(self.ctx.away)}\n<i>Nedeni: Takım verileri bulunamadı.</i>"
        
        lines = [
            "<b>🏀 FAZ-13 Analiz Raporu</b>",
            f"Maç: {esc(self.ctx.home)} vs {esc(self.ctx.away)}",
            f"Bant: {self.total_band[0]} – {self.total_band[1]}",
            f"Yön: {esc(self.ou_direction)} | Risk: {esc(self.blowout_risk)}"
        ]
        return "\n".join(lines)

class Faz13Engine:
    def __init__(self, api_sports_key: str, api_sports_base: str, baseline_store=None):
        self.api_key = api_sports_key
        self.base = api_sports_base.rstrip("/")
        self._team_stats = self._load_stats()

    def _load_stats(self) -> Dict:
        path = os.environ.get("TEAM_STATS_FILE", "team_stats.json")
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except: return {}
        return {}

    async def _team_baseline(self, team: str, season: str) -> Tuple[Optional[TeamAverages], str, int]:
        t_clean = team.lower().strip()
        local_data = self._team_stats.get(season, {})
        for nm, rec in local_data.items():
            if t_clean in nm.lower() or nm.lower() in t_clean:
                avg = TeamAverages(
                    points_for=float(rec.get("points_for", 0)),
                    points_against=float(rec.get("points_against", 0)),
                    pace_hint=float(rec.get("pace", 1)),
                    stdev_hint=9.0
                )
                return avg, "local", int(rec.get("games", 0))
        return None, "none", 0

    async def run_prematch(self, req: PrematchRequest) -> Faz13CoreOutput:
        season = req.date_str.split("-")[0]
        h_res, a_res = await asyncio.gather(
            self._team_baseline(req.home, season),
            self._team_baseline(req.away, season)
        )
        
        h_avg, h_src, h_n = h_res
        a_avg, a_src, a_n = a_res

        if not h_avg or not a_avg:
            return Faz13CoreOutput(
                ctx=req, home_avg=None, away_avg=None, total_band=(0,0),
                home_band=(0,0), away_band=(0,0), ou_direction="DATA_ERR",
                quarters={}, blowout_risk="N/A", tempo_flag="N/A", is_valid=False
            )

        # Hesaplama Mantığı
        h_mu = (h_avg.points_for + a_avg.points_against) / 2
        a_mu = (a_avg.points_for + h_avg.points_against) / 2
        total_mu = h_mu + a_mu

        # DÜZELTİLMİŞ RETURN (Sözdizimi hatası giderildi)
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
            notes=[f"Veri: H-{h_src} A-{a_src}"],
            meta={"h_n": h_n, "a_n": a_n},
            is_valid=True
        )


from __future__ import annotations
import asyncio
import html
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

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
            return f"⚠️ <b>ANALİZ HATASI</b>\nMaç: {esc(self.ctx.home)} vs {esc(self.ctx.away)}\n<i>Nedeni: Takım verileri (Baseline) bulunamadı.</i>"
        
        lines = [
            "<b>FAZ-13 Ön Analiz</b>",
            f"Maç: {esc(self.ctx.home)} vs {esc(self.ctx.away)} | Lig: {esc(self.ctx.league)}",
            f"• Tahmin Bandı: {self.total_band[0]} – {self.total_band[1]}",
            f"• Yön: {esc(self.ou_direction)}",
            f"• Risk Durumu: {esc(self.blowout_risk)}",
            ""
        ]
        if self.notes:
            lines.append("<b>Notlar:</b>")
            lines.extend([f"• {esc(n)}" for n in self.notes])
            
        return "\n".join(lines)

class Faz13Engine:
    def __init__(self, api_sports_key: str, api_sports_base: str, baseline_store=None, min_baseline_games=6):
        self.api_key = api_sports_key
        self.base = api_sports_base.rstrip("/")
        self._team_stats = self._load_stats()
        self.min_baseline_games = min_baseline_games

    def _load_stats(self) -> Dict:
        path = os.environ.get("TEAM_STATS_FILE", "team_stats.json")
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            print(f"Stats load error: {e}")
        return {}

    async def _team_baseline(self, team: str, season: str) -> Tuple[Optional[TeamAverages], str, int]:
        t_clean = team.lower().strip()
        local_data = self._team_stats.get(season, {})
        
        # Esnek eşleşme (Portland Trail Blazers -> portland)
        for nm, rec in local_data.items():
            nm_clean = nm.lower().strip()
            if t_clean in nm_clean or nm_clean in t_clean:
                pf = float(rec.get("points_for", 0.0))
                pa = float(rec.get("points_against", 0.0))
                if pf == 0: continue
                
                avg = TeamAverages(
                    points_for=pf,
                    points_against=pa,
                    pace_hint=float(rec.get("pace", 1.0)),
                    stdev_hint=float(rec.get("stdev", 9.0))
                )
                return avg, "local", int(rec.get("games", 0))
        
        return None, "none", 0

    async def run_prematch(self, req: PrematchRequest) -> Faz13CoreOutput:
        # Tarihten sezonu çek (2025-12-29 -> 2025)
        season = req.date_str.split("-")[0]
        
        h_res, a_res = await asyncio.gather(
            self._team_baseline(req.home, season),
            self._team_baseline(req.away, season)
        )
        
        h_avg, h_src, h_n = h_res
        a_avg, a_src, a_n = a_res

        # EĞER VERİ YOKSA:
        if not h_avg or not a_avg:
            return Faz13CoreOutput(
                ctx=req, home_avg=None, away_avg=None,
                total_band=(0,0), home_band=(0,0), away_band=(0,0),
                ou_direction="DATA_MISSING", quarters={},
                blowout_risk="N/A", tempo_flag="N/A", is_valid=False
            )

        # HESAPLAMALAR
        # Ev sahibi hücum gücü + Deplasman savunma zafiyeti / 2
        h_predicted = (h_avg.points_for + a_avg.points_against) / 2
        a_predicted = (a_avg.points_for + h_avg.points_against) / 2
        total_predicted = h_predicted + a_predicted

        return Faz13CoreOutput(
            ctx=req,
            home_avg=h_avg,
            away_avg=a_avg,
            total_band=(int(total_predicted - 4), int(total_predicted + 4)),
            home_band=(int(h_predicted - 3), int(h_predicted + 3)),
            away_band=(int(a_predicted - 3), int(a_predicted + 3)),
            ou_direction="UNDER" if total_predicted < 210 else "OVER", # Örnek mantık
            quarters={},
            blowout_risk="MEDIUM" if abs(h_predicted - a_predicted) > 12 else "LOW",
            tempo_flag="NORMAL",
            is_valid=True,
            notes=[f"Veri: {h_src}({h_n}) vs {a_src}({a_n})"],
            meta={
                "home_baseline_src": h_src, "home_baseline_n": h_n,
                "away_baseline_src": a_src, "away_baseline_n": a_n
            }
        )
 

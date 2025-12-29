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
    is_valid: bool = True  # Yeni: Veri geçerliliğini kontrol eder

    def render_html(self) -> str:
        esc = html.escape
        if not self.is_valid:
            return f"⚠️ <b>ANALİZ HATASI</b>\nMaç: {esc(self.ctx.home)} vs {esc(self.ctx.away)}\n<i>Nedeni: Takım istatistik verileri (Baseline) bulunamadı.</i>"
        
        lines = [
            "<b>FAZ-13 Ön Analiz</b>",
            f"Maç: {esc(self.ctx.home)} vs {esc(self.ctx.away)} | Lig: {esc(self.ctx.league)} | Tarih: {esc(self.ctx.date)}",
            "", "<b>Dar Bant</b>",
            f"• Toplam: {self.total_band[0]}–{self.total_band[1]}",
            f"• Ev: {self.home_band[0]}–{self.home_band[1]} | Dep: {self.away_band[0]}–{self.away_band[1]}",
            f"• Alt/Üst yönü: {esc(self.ou_direction)}",
            "", "<b>Periyot Bantları</b>"
        ]
        for k in ["1Q", "2Q", "HT", "3Q", "4Q", "FT"]:
            if k in self.quarters:
                lo, hi = self.quarters[k]
                lines.append(f"• {k}: {lo}–{hi}")
        lines.extend(["", "<b>Risk Göstergeleri", f"• Blowout riski: {esc(self.blowout_risk)}", f"• Tempo flag: {esc(self.tempo_flag)}"])
        if self.notes:
            lines.extend(["", "<b>Notlar</b>"] + [f"• {esc(n)}" for n in self.notes])
        lines.append("\n<i>Bu çıktı analiz amaçlıdır. Bahis tavsiyesi değildir.</i>")
        return "\n".join(lines)

class Faz13Engine:
    def __init__(self, api_sports_key, api_sports_base, baseline_store=None, min_baseline_games=6):
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
        profile = get_league_profile(league)
        t_clean = team.lower().strip()
        
        # 1. Local Search with Fuzzy Match
        local_data = self._team_stats.get(season, {})
        for nm, rec in local_data.items():
            nm_clean = nm.lower().strip()
            if t_clean in nm_clean or nm_clean in t_clean: # Esnek eşleşme
                pf = float(rec.get("points_for", 0.0))
                pa = float(rec.get("points_against", 0.0))
                if pf == 0 or pa == 0: continue
                pace = rec.get("pace", (pf + pa) / 180.0)
                return {"pf": pf, "pa": pa, "pace": pace, "stdev": float(rec.get("stdev", 9.0))}, "local", int(rec.get("games", 0))

        # 2. API/Remote kısımları (Kısaltıldı, mantık aynı)
        return None, "none", 0

    async def run_prematch(self, req) -> Faz13CoreOutput:
        season = req.date_str.split("-")[0]
        h_res, a_res = await asyncio.gather(
            self._team_baseline(req.home, req.league, season),
            self._team_baseline(req.away, req.league, season)
        )
        
        if not h_res[0] or not a_res[0]:
            return Faz13CoreOutput(ctx=req, home_avg=None, away_avg=None, total_band=(0,0), home_band=(0,0), 
                                  away_band=(0,0), ou_direction="ERROR", quarters={}, blowout_risk="N/A", 
                                  tempo_flag="N/A", is_valid=False)

        # Hesaplamalar (h_res[0]['pf'] vb. üzerinden devam eder...)
        # [Mevcut matematiksel formüller buraya gelecek]
        # Örnek dönüş:
        return Faz13CoreOutput(ctx=req, ..., is_valid=True)


from __future__ import annotations

import asyncio
import html
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from core.aggregate_engine import aggregate_baseline
from league_profiles import get_league_profile

try:
    from providers.espn_adapter import ESPNAdapter
except Exception:
    ESPNAdapter = None


# =========================
# DATA MODELS
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
    pace: float
    stdev: float


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
        out.append(f"Toplam Bant: {self.total_band[0]}–{self.total_band[1]}")
        out.append(
            f"Ev: {self.home_band[0]}–{self.home_band[1]} | "
            f"Dep: {self.away_band[0]}–{self.away_band[1]}"
        )
        out.append(f"Alt/Üst: {self.ou_direction}")
        out.append(f"Tempo: {self.tempo_flag}")
        out.append("")

        for n in self.notes:
            out.append(f"• {esc(n)}")

        out.append("")
        out.append("Bu çıktı analiz/simülasyon amaçlıdır. Bahis tavsiyesi değildir.")
        return "\n".join(out)


# =========================
# ENGINE
# =========================

class Faz13Engine:
    def __init__(
        self,
        api_sports_key: str,
        api_sports_base: str,
        **kwargs,
    ) -> None:
        self.api_key = api_sports_key
        self.api_base = api_sports_base
        self.espn = ESPNAdapter() if ESPNAdapter else None

    # ---------------------

    @staticmethod
    def _tempo_flag(pace: float) -> str:
        if pace >= 102:
            return "FAST"
        if pace <= 97:
            return "SLOW"
        return "NORMAL"

    # ---------------------
    # MANUAL BASELINE LOADER (KESİN ÇÖZÜM)
    # ---------------------

    def _load_manual_baseline(self, league: str, team: str) -> Optional[Dict[str, Any]]:
        path = f"data/baselines/series/{league}/{team}.json"
        if not os.path.exists(path):
            return None

        try:
            with open(path, "r", encoding="utf-8") as f:
                j = json.load(f)
        except Exception:
            return None

        return {
            "pts_for": float(j["pts_for"]),
            "pts_against": float(j["pts_against"]),
            "pace": float(j.get("pace", 99.5)),
            "confidence": 0.90,
            "sources": ["MANUAL_BASELINE"],
        }

    # ---------------------

    async def _espn_rows(self, league: str, team: str) -> List[Dict[str, Any]]:
        if league.upper() != "NBA" or not self.espn:
            return []

        try:
            games = await asyncio.wait_for(
                self.espn.fetch_team_recent_games("NBA", team, 5),
                timeout=2.0,
            )
        except Exception:
            return []

        rows: List[Dict[str, Any]] = []
        for g in games or []:
            rows.append(
                {
                    "pts_for": g["pts_for"],
                    "pts_against": g["pts_against"],
                    "pace": g.get("pace"),
                    "confidence": 0.6,
                    "source": "ESPN_LAST5",
                }
            )
        return rows

    # ---------------------

    async def run_prematch(self, req: PrematchRequest) -> Faz13CoreOutput:
        profile = get_league_profile(req.league)

        home_rows: List[Dict[str, Any]] = []
        away_rows: List[Dict[str, Any]] = []

        # 1️⃣ MANUAL BASELINE (PRIMARY)
        h_manual = self._load_manual_baseline(req.league, req.home)
        a_manual = self._load_manual_baseline(req.league, req.away)

        if h_manual:
            home_rows.append(h_manual)
        if a_manual:
            away_rows.append(a_manual)

        # 2️⃣ ESPN (SECONDARY)
        home_rows += await self._espn_rows(req.league, req.home)
        away_rows += await self._espn_rows(req.league, req.away)

        # 3️⃣ AGGREGATE
        home_base = aggregate_baseline(home_rows)
        away_base = aggregate_baseline(away_rows)

        # 4️⃣ FAILSAFE (SON ÇARE – AMA ARTIK DÜŞMEZ)
        if not home_base or not away_base:
            pf = pa = 113.5 if req.league.upper() == "NBA" else 80.0
            pace = 99.5 if req.league.upper() == "NBA" else 95.0

            home_base = home_base or {
                "pts_for": pf,
                "pts_against": pa,
                "pace": pace,
                "confidence": 0.2,
                "sources": ["LEAGUE_AVG"],
            }
            away_base = away_base or {
                "pts_for": pf,
                "pts_against": pa,
                "pace": pace,
                "confidence": 0.2,
                "sources": ["LEAGUE_AVG"],
            }

        h_pf = home_base["pts_for"]
        h_pa = home_base["pts_against"]
        a_pf = away_base["pts_for"]
        a_pa = away_base["pts_against"]

        home_mu = (h_pf + a_pa) / 2
        away_mu = (a_pf + h_pa) / 2
        total_mu = home_mu + away_mu

        total_band = (
            int(total_mu - profile.band_hw_total),
            int(total_mu + profile.band_hw_total),
        )
        home_band = (
            int(home_mu - profile.band_hw_team),
            int(home_mu + profile.band_hw_team),
        )
        away_band = (
            int(away_mu - profile.band_hw_team),
            int(away_mu + profile.band_hw_team),
        )

        pace_mean = (home_base.get("pace", 99.5) + away_base.get("pace", 99.5)) / 2
        tempo_flag = self._tempo_flag(pace_mean)

        ctx = FixtureContext(req.league, req.date_str, req.home, req.away)

        return Faz13CoreOutput(
            ctx=ctx,
            home_avg=TeamAverages(h_pf, h_pa, home_base.get("pace", 99.5), 10.0),
            away_avg=TeamAverages(a_pf, a_pa, away_base.get("pace", 99.5), 10.0),
            total_band=total_band,
            home_band=home_band,
            away_band=away_band,
            ou_direction="NO_EDGE",
            quarters={},
            blowout_risk="LOW",
            tempo_flag=tempo_flag,
            notes=[
                f"Home sources: {','.join(home_base.get('sources', []))}",
                f"Away sources: {','.join(away_base.get('sources', []))}",
            ],
            meta={
                "confidence": min(home_base["confidence"], away_base["confidence"]),
                "expected_total": round(total_mu, 2),
                "pace_mean": round(pace_mean, 2),
                "engine": "FAZ-13 FINAL (MANUAL BASELINE)",
                "generated_at": int(time.time()),
            },
        )

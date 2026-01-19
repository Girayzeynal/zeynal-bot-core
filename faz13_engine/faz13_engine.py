from __future__ import annotations

import html
import os
import time
import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from baseline.team_baseline_store import TeamBaselineStore
from league_profiles import get_league_profile

# =====================================================
# OPTIONAL DEPENDENCIES (SAFE IMPORT)
# =====================================================

try:
    from providers import ESPNAdapter  # type: ignore
except Exception:
    ESPNAdapter = None  # type: ignore

try:
    from faz17_engine.faz17_engine import Faz17Engine, MarketRequest  # type: ignore
except Exception:
    Faz17Engine = None  # type: ignore
    MarketRequest = None  # type: ignore


# =====================================================
# DATA MODELS
# =====================================================

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

        def fmt(v: Any) -> str:
            if isinstance(v, (list, tuple, set)):
                return ", ".join(map(str, v))
            return str(v)

        out: List[str] = []
        out.append("FAZ-13 ÖN ANALİZ")
        out.append(f"{esc(self.ctx.home)} vs {esc(self.ctx.away)} | {esc(self.ctx.league)} | {esc(self.ctx.date)}")
        out.append("")
        out.append(f"Toplam Bant: {self.total_band[0]} – {self.total_band[1]}")
        out.append(f"Ev: {self.home_band[0]} – {self.home_band[1]}")
        out.append(f"Dep: {self.away_band[0]} – {self.away_band[1]}")
        out.append(f"Alt/Üst: {self.ou_direction}")
        out.append(f"Tempo: {self.tempo_flag}")
        out.append(f"Blowout: {self.blowout_risk}")

        if self.quarters:
            out.append("")
            out.append("Periyotlar:")
            for k, v in self.quarters.items():
                out.append(f"{k}: {v[0]} – {v[1]}")

        if self.notes:
            out.append("")
            out.append("Notlar:")
            for n in self.notes:
                out.append(f"- {esc(n)}")

        if self.meta:
            out.append("")
            out.append("Meta:")
            for k, v in self.meta.items():
                out.append(f"{esc(str(k))}: {esc(fmt(v))}")

        out.append("")
        out.append("Bu çıktı analiz/simülasyon amaçlıdır. Bahis tavsiyesi değildir.")
        return "\n".join(out)


# =====================================================
# AGGREGATION CORE
# =====================================================

def aggregate_baseline(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not rows:
        return None

    conf_sum = sum(float(r.get("confidence", 0.0)) for r in rows)
    if conf_sum <= 0:
        return None

    pf = sum(r["pts_for"] * r["confidence"] for r in rows) / conf_sum
    pa = sum(r["pts_against"] * r["confidence"] for r in rows) / conf_sum

    pace_vals = [r.get("pace") for r in rows if r.get("pace") is not None]
    pace = sum(pace_vals) / len(pace_vals) if pace_vals else None

    return {
        "pts_for": pf,
        "pts_against": pa,
        "pace": pace,
        "confidence": conf_sum / len(rows),
        "sources": [r["source"] for r in rows if r.get("source")],
    }


# =====================================================
# FAZ-13 ENGINE (FINAL ARCHITECTURE)
# =====================================================

class Faz13Engine:
    def __init__(
        self,
        api_sports_key: str,
        api_sports_base: str,
        baseline_store: Optional[TeamBaselineStore] = None,
    ) -> None:
        self.api_key = api_sports_key
        self.base = api_sports_base
        self.baseline_store = baseline_store
        self.session: Optional[aiohttp.ClientSession] = None
        self.faz17 = Faz17Engine() if Faz17Engine else None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session and not self.session.closed:
            return self.session
        self.session = aiohttp.ClientSession()
        return self.session

    # -------------------------------------------------

    @staticmethod
    def _tempo_flag(pace: float) -> str:
        if pace >= 102:
            return "FAST"
        if pace <= 97:
            return "SLOW"
        return "NORMAL"

    # -------------------------------------------------

    async def run_prematch(self, req: PrematchRequest) -> Faz13CoreOutput:
        profile = get_league_profile(req.league)

        notes: List[str] = ["FAZ-13 FINAL ENGINE", "TEAM-FIRST MODE"]
        home_rows: List[Dict[str, Any]] = []
        away_rows: List[Dict[str, Any]] = []

        # ---------- BASELINE STORE (PRIMARY FALLBACK)
        if self.baseline_store:
            try:
                h = self.baseline_store.get(req.league, req.home)
                a = self.baseline_store.get(req.league, req.away)
                if h:
                    home_rows.append({
                        "pts_for": h.pts_for,
                        "pts_against": h.pts_against,
                        "pace": h.pace,
                        "confidence": 0.75,
                        "source": "BASELINE_STORE",
                    })
                if a:
                    away_rows.append({
                        "pts_for": a.pts_for,
                        "pts_against": a.pts_against,
                        "pace": a.pace,
                        "confidence": 0.75,
                        "source": "BASELINE_STORE",
                    })
            except Exception:
                notes.append("Baseline store error")

        # ---------- ESPN (SECONDARY)
        if req.league.upper() == "NBA" and ESPNAdapter:
            try:
                espn = ESPNAdapter()
                for side, name, rows in (
                    ("home", req.home, home_rows),
                    ("away", req.away, away_rows),
                ):
                    r = await espn.fetch_team_baseline(name)  # type: ignore
                    if r:
                        rows.append(r)
            except Exception:
                notes.append("ESPN fetch failed")

        home_base = aggregate_baseline(home_rows)
        away_base = aggregate_baseline(away_rows)

        ctx = FixtureContext(req.league, req.date_str, req.home, req.away)

        if not home_base or not away_base:
            return Faz13CoreOutput(
                ctx=ctx,
                home_avg=TeamAverages(0, 0, 100, 10),
                away_avg=TeamAverages(0, 0, 100, 10),
                total_band=(0, 0),
                home_band=(0, 0),
                away_band=(0, 0),
                ou_direction="NO_PLAY",
                quarters={},
                blowout_risk="UNKNOWN",
                tempo_flag="UNKNOWN",
                notes=notes + ["BASELINE_NOT_AVAILABLE"],
                meta={"degraded_mode": True},
            )

        pace_home = home_base.get("pace") or 100.0
        pace_away = away_base.get("pace") or 100.0
        pace_mean = (pace_home + pace_away) / 2.0

        h_mu = (home_base["pts_for"] + away_base["pts_against"]) / 2
        a_mu = (away_base["pts_for"] + home_base["pts_against"]) / 2
        total_mu = h_mu + a_mu

        total_band = (
            int(total_mu - profile.band_hw_total),
            int(total_mu + profile.band_hw_total),
        )

        home_band = (
            int(h_mu - profile.band_hw_team),
            int(h_mu + profile.band_hw_team),
        )

        away_band = (
            int(a_mu - profile.band_hw_team),
            int(a_mu + profile.band_hw_team),
        )

        tempo_flag = self._tempo_flag(pace_mean)

        quarters = {
            "1Q": (int(total_mu * 0.24) - 3, int(total_mu * 0.24) + 3),
            "2Q": (int(total_mu * 0.26) - 3, int(total_mu * 0.26) + 3),
            "3Q": (int(total_mu * 0.25) - 3, int(total_mu * 0.25) + 3),
            "4Q": (int(total_mu * 0.25) - 3, int(total_mu * 0.25) + 3),
        }

        return Faz13CoreOutput(
            ctx=ctx,
            home_avg=TeamAverages(home_base["pts_for"], home_base["pts_against"], pace_home, 10),
            away_avg=TeamAverages(away_base["pts_for"], away_base["pts_against"], pace_away, 10),
            total_band=total_band,
            home_band=home_band,
            away_band=away_band,
            ou_direction="NO_EDGE",
            quarters=quarters,
            blowout_risk="LOW",
            tempo_flag=tempo_flag,
            notes=notes,
            meta={
                "confidence": min(home_base["confidence"], away_base["confidence"]),
                "sources_home": home_base["sources"],
                "sources_away": away_base["sources"],
                "expected_total": round(total_mu, 2),
                "pace_mean": round(pace_mean, 2),
                "degraded_mode": False,
                "engine": "FAZ-13 FINAL",
                "timestamp": int(time.time()),
            },
        )

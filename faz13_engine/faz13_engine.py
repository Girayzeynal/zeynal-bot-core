# faz13_engine/faz13_engine.py

from __future__ import annotations

import html
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from league_profiles import get_league_profile

from core.aggregate_engine import aggregate_baseline
from faz17_engine.faz17_engine import Faz17Engine, MarketRequest
from providers.espn_adapter import ESPNAdapter
from providers.sportsdataio_adapter import SportsDataIOAdapter


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

        def _fmt(v: Any) -> str:
            if isinstance(v, (list, tuple, set)):
                return ", ".join(str(x) for x in v)
            return str(v)

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
                out.append(f"• {esc(str(n))}")

        if self.market:
            out.append("")
            out.append("Market Entegrasyonu")
            for k, v in self.market.items():
                out.append(f"• {esc(str(k))}: {esc(_fmt(v))}")

        if self.meta:
            out.append("")
            out.append("Meta Skor")
            for k, v in self.meta.items():
                out.append(f"• {esc(str(k))}: {esc(_fmt(v))}")

        out.append("")
        out.append("Bu çıktı analiz/simülasyon amaçlıdır. Bahis tavsiyesi değildir.")
        return "\n".join(out)


# =====================================================
# ENGINE
# =====================================================

class Faz13Engine:
    """
    Production-grade FAZ-13:
      - Real providers only (ESPN + SportsDataIO), API-Sports is NOT used here
      - Market total required, fetched via FAZ-17 engine (Odds API). If missing => NO_PLAY: MARKET_MISSING
      - Injury data required (SportsDataIO + ESPN). If missing => NO_PLAY: INJURY_DATA_MISSING
      - Edge computed from expected_total - market_total
      - NO_EDGE only when |edge| < threshold (never due to missing data)
      - Evidence fields: sources, fetched_at, data_coverage, missing_fields
    """

    def __init__(self) -> None:
        self.espn = ESPNAdapter()
        self.sd = SportsDataIOAdapter()
        self.faz17 = Faz17Engine()

    @staticmethod
    def resolve_nba_season(date_str: str) -> str:
        try:
            y = int(date_str[:4])
            m = int(date_str[5:7])
        except Exception:
            return date_str[:4]
        return str(y) if m >= 10 else str(y - 1)

    @staticmethod
    def _edge_threshold(confidence_raw: float, band_hw_total: int) -> float:
        base = max(1.5, float(band_hw_total) * 0.25)
        c = max(0.0, min(1.0, confidence_raw))
        if c >= 0.9:
            factor = 0.85
        elif c <= 0.5:
            factor = 1.10
        else:
            factor = 1.10 + (c - 0.5) * (0.85 - 1.10) / (0.9 - 0.5)
        return base * factor

    @staticmethod
    def _risk_label(confidence_pct: float, abs_edge: float, edge_threshold: float) -> str:
        if confidence_pct >= 80:
            c_score = 0.15
        elif confidence_pct >= 65:
            c_score = 0.35
        elif confidence_pct >= 50:
            c_score = 0.55
        else:
            c_score = 0.75

        if edge_threshold <= 0:
            e_score = 1.0
        else:
            ratio = abs_edge / edge_threshold
            if ratio >= 2.0:
                e_score = 0.20
            elif ratio >= 1.0:
                e_score = 0.50
            else:
                e_score = 0.90

        score = 0.6 * c_score + 0.4 * e_score
        if score <= 0.35:
            return "LOW"
        if score <= 0.60:
            return "MEDIUM"
        return "HIGH"

    @staticmethod
    def _injury_penalty(injuries: List[Dict[str, Any]]) -> float:
        """
        Purely data-driven on injury statuses. No fake player baselines.
        Returns points penalty to apply to expected_total (negative reduces total).
        """
        if not injuries:
            return 0.0

        w = 0.0
        for it in injuries:
            st = str(it.get("status", "") or "").lower()
            if not st:
                continue
            if "out" in st or "injured" in st:
                w += 2.0
            elif "doubt" in st:
                w += 1.5
            elif "question" in st or "day-to-day" in st:
                w += 0.8
            elif "probable" in st:
                w += 0.3
        return -w

    async def run_prematch(self, req: PrematchRequest) -> Faz13CoreOutput:
        profile = get_league_profile(req.league)
        season = self.resolve_nba_season(req.date_str) if req.league.upper() == "NBA" else req.date_str[:4]
        ctx = FixtureContext(req.league, req.date_str, req.home, req.away)

        fetched_at = int(time.time())
        data_coverage = {
            "team_stats": False,
            "injuries": False,
            "roster": False,
            "pace": False,
            "market": False,
        }
        missing_fields: List[str] = []
        notes: List[str] = [f"Season: {season}", "TEAM-FIRST mode (MULTI-SOURCE)"]

        # ---- Market total (required)
        market = await self.faz17.fetch_market_total(
            MarketRequest(league=req.league, date_str=req.date_str, home=req.home, away=req.away)
        )
        if not market or market.get("total") is None:
            missing_fields.append("market_total")
            return Faz13CoreOutput(
                ctx=ctx,
                home_avg=TeamAverages(0, 0, 1, 9),
                away_avg=TeamAverages(0, 0, 1, 9),
                total_band=(0, 0),
                home_band=(0, 0),
                away_band=(0, 0),
                ou_direction="NO_PLAY",
                quarters={},
                blowout_risk="UNKNOWN",
                tempo_flag="UNKNOWN",
                notes=notes + ["NO_PLAY: MARKET_MISSING"],
                market={"status": "MISSING"},
                meta={
                    "season": season,
                    "team_first": True,
                    "baseline_missing": True,
                    "risk": "NO_PLAY",
                    "confidence_pct": 0.0,
                    "confidence_raw": 0.0,
                    "fetched_at": fetched_at,
                    "data_coverage": data_coverage,
                    "missing_fields": missing_fields,
                    "sources_home": [],
                    "sources_away": [],
                    "sources_inj_home": [],
                    "sources_inj_away": [],
                },
            )

        market_total = float(market["total"])
        data_coverage["market"] = True

        # ---- Resolve ESPN team keys
        home_abbr = await self.espn._espn_resolve_abbr(req.home)  # type: ignore[attr-defined]
        away_abbr = await self.espn._espn_resolve_abbr(req.away)  # type: ignore[attr-defined]
        notes.append(f"ESPN abbr: home={home_abbr} away={away_abbr}")

        if not home_abbr:
            missing_fields.append("home_team_key")
        if not away_abbr:
            missing_fields.append("away_team_key")
        if missing_fields:
            return Faz13CoreOutput(
                ctx=ctx,
                home_avg=TeamAverages(0, 0, 1, 9),
                away_avg=TeamAverages(0, 0, 1, 9),
                total_band=(0, 0),
                home_band=(0, 0),
                away_band=(0, 0),
                ou_direction="NO_PLAY",
                quarters={},
                blowout_risk="UNKNOWN",
                tempo_flag="UNKNOWN",
                notes=notes + ["NO_PLAY: DATA_MISSING"],
                market=market,
                meta={
                    "season": season,
                    "team_first": True,
                    "baseline_missing": True,
                    "risk": "NO_PLAY",
                    "confidence_pct": 0.0,
                    "confidence_raw": 0.0,
                    "fetched_at": fetched_at,
                    "data_coverage": data_coverage,
                    "missing_fields": missing_fields,
                    "sources_home": [],
                    "sources_away": [],
                    "sources_inj_home": [],
                    "sources_inj_away": [],
                },
            )

        # ---- Team baseline from real providers
        home_rows: List[Dict[str, Any]] = []
        away_rows: List[Dict[str, Any]] = []

        espn_home = await self.espn.fetch_team_baseline(home_abbr)  # type: ignore[attr-defined]
        espn_away = await self.espn.fetch_team_baseline(away_abbr)  # type: ignore[attr-defined]
        if espn_home:
            home_rows.append(espn_home)
        if espn_away:
            away_rows.append(espn_away)

        sd_home = await self.sd.fetch_team_baseline(home_abbr.upper(), str(season))
        sd_away = await self.sd.fetch_team_baseline(away_abbr.upper(), str(season))
        if sd_home:
            home_rows.append(sd_home)
        if sd_away:
            away_rows.append(sd_away)

        home_base = aggregate_baseline(home_rows)
        away_base = aggregate_baseline(away_rows)

        if not home_base:
            missing_fields.append("home_team_stats")
        if not away_base:
            missing_fields.append("away_team_stats")
        if missing_fields:
            return Faz13CoreOutput(
                ctx=ctx,
                home_avg=TeamAverages(0, 0, 1, 9),
                away_avg=TeamAverages(0, 0, 1, 9),
                total_band=(0, 0),
                home_band=(0, 0),
                away_band=(0, 0),
                ou_direction="NO_PLAY",
                quarters={},
                blowout_risk="UNKNOWN",
                tempo_flag="UNKNOWN",
                notes=notes + ["NO_PLAY: DATA_MISSING"],
                market=market,
                meta={
                    "season": season,
                    "team_first": True,
                    "baseline_missing": True,
                    "risk": "NO_PLAY",
                    "confidence_pct": 0.0,
                    "confidence_raw": 0.0,
                    "fetched_at": fetched_at,
                    "data_coverage": data_coverage,
                    "missing_fields": missing_fields,
                    "sources_home": home_base.get("sources", []) if home_base else [],
                    "sources_away": away_base.get("sources", []) if away_base else [],
                    "sources_inj_home": [],
                    "sources_inj_away": [],
                },
            )

        data_coverage["team_stats"] = True

        sources_home = home_base.get("sources", [])
        sources_away = away_base.get("sources", [])

        notes.append(f"Sources(home)={', '.join(sources_home)}")
        notes.append(f"Sources(away)={', '.join(sources_away)}")

        # ---- Injury data (required) from SportsDataIO + ESPN
        inj_sources_home: List[str] = []
        inj_sources_away: List[str] = []

        sd_inj_home = await self.sd.fetch_team_injuries(home_abbr.upper())
        sd_inj_away = await self.sd.fetch_team_injuries(away_abbr.upper())
        if sd_inj_home is not None:
            inj_sources_home.append("SPORTSDATAIO")
        if sd_inj_away is not None:
            inj_sources_away.append("SPORTSDATAIO")

        espn_inj_home = await self.espn.fetch_team_injuries(home_abbr)  # type: ignore[attr-defined]
        espn_inj_away = await self.espn.fetch_team_injuries(away_abbr)  # type: ignore[attr-defined]
        if espn_inj_home is not None:
            inj_sources_home.append("ESPN")
        if espn_inj_away is not None:
            inj_sources_away.append("ESPN")

        # Require at least one injury source per team (NBA)
        if not inj_sources_home:
            missing_fields.append("home_injury_data")
        if not inj_sources_away:
            missing_fields.append("away_injury_data")
        if missing_fields:
            return Faz13CoreOutput(
                ctx=ctx,
                home_avg=TeamAverages(0, 0, 1, 9),
                away_avg=TeamAverages(0, 0, 1, 9),
                total_band=(0, 0),
                home_band=(0, 0),
                away_band=(0, 0),
                ou_direction="NO_PLAY",
                quarters={},
                blowout_risk="UNKNOWN",
                tempo_flag="UNKNOWN",
                notes=notes + ["NO_PLAY: INJURY_DATA_MISSING"],
                market=market,
                meta={
                    "season": season,
                    "team_first": True,
                    "baseline_missing": True,
                    "risk": "NO_PLAY",
                    "confidence_pct": 0.0,
                    "confidence_raw": 0.0,
                    "fetched_at": fetched_at,
                    "data_coverage": data_coverage,
                    "missing_fields": missing_fields,
                    "sources_home": sources_home,
                    "sources_away": sources_away,
                    "sources_inj_home": inj_sources_home,
                    "sources_inj_away": inj_sources_away,
                },
            )

        data_coverage["injuries"] = True

        # ---- Injury penalty (data-driven) from SportsDataIO injuries list (primary)
        home_inj_list = (sd_inj_home or {}).get("injuries", []) if sd_inj_home else []
        away_inj_list = (sd_inj_away or {}).get("injuries", []) if sd_inj_away else []
        inj_penalty = self._injury_penalty(home_inj_list) + self._injury_penalty(away_inj_list)

        # ---- Expected totals from baseline
        h_pf = float(home_base["pts_for"])
        h_pa = float(home_base["pts_against"])
        a_pf = float(away_base["pts_for"])
        a_pa = float(away_base["pts_against"])

        home_mu = (h_pf + a_pa) / 2.0
        away_mu = (a_pf + h_pa) / 2.0
        expected_total_raw = home_mu + away_mu
        expected_total = expected_total_raw + inj_penalty  # injury-adjusted expectation

        total_band = (int(expected_total - profile.band_hw_total), int(expected_total + profile.band_hw_total))
        home_band = (int(home_mu - profile.band_hw_team), int(home_mu + profile.band_hw_team))
        away_band = (int(away_mu - profile.band_hw_team), int(away_mu + profile.band_hw_team))

        # ---- Confidence (consistent)
        conf_raw = min(float(home_base.get("confidence", 0.0)), float(away_base.get("confidence", 0.0)))
        confidence_pct = round(conf_raw * 100.0, 1)

        # ---- Edge
        edge_value = expected_total - market_total
        edge_threshold = self._edge_threshold(conf_raw, profile.band_hw_total)

        if edge_value >= edge_threshold:
            ou_direction = "ÜST"
        elif edge_value <= -edge_threshold:
            ou_direction = "ALT"
        else:
            ou_direction = "NO_EDGE"

        # ---- Risk (consistent with confidence + edge clarity)
        risk = self._risk_label(confidence_pct, abs(edge_value), edge_threshold)

        notes.append(f"Model E[total]={expected_total:.1f} | Market total={market_total:.1f} | Edge={edge_value:+.1f} | Thr={edge_threshold:.1f}")
        if inj_penalty != 0.0:
            notes.append(f"Injury penalty applied: {inj_penalty:+.1f} (SportsDataIO)")

        meta = {
            "season": season,
            "team_first": True,
            "baseline_missing": False,
            "fetched_at": fetched_at,
            "data_coverage": data_coverage,
            "missing_fields": missing_fields,
            "sources_home": sources_home,
            "sources_away": sources_away,
            "sources_inj_home": inj_sources_home,
            "sources_inj_away": inj_sources_away,
            "confidence_pct": confidence_pct,
            "confidence_raw": round(conf_raw, 3),
            "risk": risk,
            "expected_total": round(expected_total, 3),
            "expected_total_raw": round(expected_total_raw, 3),
            "injury_penalty": round(inj_penalty, 3),
            "market_total": round(market_total, 3),
            "edge_value": round(edge_value, 3),
            "edge_threshold": round(edge_threshold, 3),
        }

        return Faz13CoreOutput(
            ctx=ctx,
            home_avg=TeamAverages(h_pf, h_pa, 1.0, 10.0),
            away_avg=TeamAverages(a_pf, a_pa, 1.0, 10.0),
            total_band=total_band,
            home_band=home_band,
            away_band=away_band,
            ou_direction=ou_direction,
            quarters={},
            blowout_risk="LOW",
            tempo_flag="NORMAL",
            notes=notes,
            market=market,
            meta=meta,
        )

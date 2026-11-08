from __future__ import annotations

import asyncio
import html
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
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
        home_n = self.meta.get("home_baseline_games")
        away_n = self.meta.get("away_baseline_games")
        if isinstance(home_n, int) and isinstance(away_n, int):
            out.append(f"Örneklem: Ev {home_n} maç | Dep {away_n} maç")
        out.append(
            f"Takım ortalamaları (atılan/yenilen): "
            f"Ev {self.home_avg.points_for:.1f}/{self.home_avg.points_against:.1f} | "
            f"Dep {self.away_avg.points_for:.1f}/{self.away_avg.points_against:.1f}"
        )
        home_mu = (self.home_avg.points_for + self.away_avg.points_against) / 2
        away_mu = (self.away_avg.points_for + self.home_avg.points_against) / 2
        total_mu = home_mu + away_mu
        out.append(
            f"Hesap: Ev ({self.home_avg.points_for:.1f}+{self.away_avg.points_against:.1f})/2"
            f"={home_mu:.2f} | Dep ({self.away_avg.points_for:.1f}+{self.home_avg.points_against:.1f})/2"
            f"={away_mu:.2f} | Toplam={total_mu:.2f}"
        )
        out.append(
            "Bant: Lig profilindeki sabit yarı genişlik; istatistiksel güven aralığı değildir."
        )
        out.append("Model: Son maç skor ortalamaları; kadro, sakatlık, piyasa ve Monte Carlo dahil değil.")
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
    def __init__(self, api_sports_key: str, api_sports_base: str, **kwargs) -> None:
        self.api_key = api_sports_key
        self.api_base = api_sports_base
        self.espn = ESPNAdapter() if ESPNAdapter else None
        self.baseline_store = kwargs.get("baseline_store")

        # Manual baselines remain optional; the canonical store is the primary source.
        self.project_root = Path(__file__).resolve().parents[1]

    # ---------------------

    @staticmethod
    def _tempo_flag(pace: float) -> str:
        if pace >= 102:
            return "FAST"
        if pace <= 97:
            return "SLOW"
        return "NORMAL"

    # ---------------------
    # TEAM NAME NORMALIZER
    # ---------------------

    @staticmethod
    def _normalize_team(team: str) -> List[str]:
        """
        Birden fazla aday üretir.
        """
        team = team.strip()
        variants = {team}

        if " vs " in team:
            variants.add(team.split(" vs ")[0].strip())

        if team.lower() == "jazz":
            variants.add("Utah Jazz")

        if team.lower() == "timberwolves":
            variants.add("Minnesota Timberwolves")

        return list(variants)

    # ---------------------
    # MANUAL BASELINE LOADER (KESİN)
    # ---------------------

    def _load_manual_baseline(self, league: str, team: str) -> Optional[Dict[str, Any]]:
        base = self.project_root / "data" / "baselines" / "series" / league

        for name in self._normalize_team(team):
            path = base / f"{name}.json"
            if path.exists():
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        j = json.load(f)
                except Exception:
                    continue

                return {
                    "pts_for": float(j["pts_for"]),
                    "pts_against": float(j["pts_against"]),
                    "pace": float(j.get("pace", 99.5)),
                    "confidence": 0.80,
                    "source": "MANUAL_BASELINE",
                }

        return None

    # ---------------------

    async def _load_store_baseline(self, league: str, team: str) -> Optional[Dict[str, Any]]:
        """Load a canonical TeamBaselineStore record without guessing file paths."""
        store = self.baseline_store
        if store is None:
            return None

        candidates = [team]
        if self.espn and league.upper().strip() == "NBA":
            try:
                abbr = await asyncio.wait_for(
                    self.espn.resolve_team_abbr(league, team),
                    timeout=2.0,
                )
                if abbr:
                    candidates.insert(0, str(abbr).upper().strip())
            except Exception:
                pass

        for candidate in dict.fromkeys(candidates):
            try:
                baseline = store.get(league, candidate)
            except Exception:
                continue
            if baseline is None:
                continue

            n_games = max(0, int(getattr(baseline, "n_games", 0)))
            if n_games < 1:
                continue
            confidence = min(0.90, 0.50 + 0.025 * min(n_games, 16))
            return {
                "pts_for": float(baseline.pts_for),
                "pts_against": float(baseline.pts_against),
                "pace": float(baseline.pace),
                "confidence": confidence,
                "source": "TEAM_BASELINE_STORE",
                "n_games": n_games,
                "fetched_at": int(getattr(baseline, "updated_ts", 0) or 0),
            }
        return None

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

        # 1) Canonical persisted baselines (written by TeamBaselineBootstrapper)
        h_store = await self._load_store_baseline(req.league, req.home)
        a_store = await self._load_store_baseline(req.league, req.away)
        if h_store:
            home_rows.append(h_store)
        if a_store:
            away_rows.append(a_store)

        # 2) Manual baselines are an explicitly lower-priority secondary source.
        if not h_store:
            h_manual = self._load_manual_baseline(req.league, req.home)
            if h_manual:
                home_rows.append(h_manual)
        if not a_store:
            a_manual = self._load_manual_baseline(req.league, req.away)
            if a_manual:
                away_rows.append(a_manual)

        # 3) ESPN recent games are used only when no persisted/manual baseline exists.
        if not home_rows:
            home_rows += await self._espn_rows(req.league, req.home)
        if not away_rows:
            away_rows += await self._espn_rows(req.league, req.away)

        # 4) Strict aggregation: never manufacture league-average team data.
        home_base = aggregate_baseline(home_rows)
        away_base = aggregate_baseline(away_rows)
        missing = []
        if not home_base:
            missing.append(f"home={req.home}")
        if not away_base:
            missing.append(f"away={req.away}")
        if missing:
            raise ValueError(
                "Güvenilir baseline bulunamadı (" + ", ".join(missing) +
                "). Tahmin üretilmedi; önce gerçek maç verisi yüklenmeli."
            )

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
                "confidence_pct": round(100.0 * min(home_base["confidence"], away_base["confidence"]), 1),
                "data_quality": (
                    "MANUAL_BASELINE" if "MANUAL_BASELINE" in home_base.get("sources", [])
                    or "MANUAL_BASELINE" in away_base.get("sources", [])
                    else "VERIFIED_BASELINE"
                ),
                "home_sources": list(home_base.get("sources", [])),
                "away_sources": list(away_base.get("sources", [])),
                "home_baseline_games": int(home_base.get("n_games", 0)),
                "away_baseline_games": int(away_base.get("n_games", 0)),
                "expected_total": round(total_mu, 2),
                "pace_mean": round(pace_mean, 2),
                "engine": "FAZ-13 FINAL (ABSOLUTE PATH + NORMALIZER)",
                "generated_at": int(time.time()),
            },
        )

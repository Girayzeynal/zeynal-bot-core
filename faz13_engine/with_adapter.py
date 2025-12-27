"""
FAZ-13 pre‑match analysis engine with a concrete TeamStatsAdapter implementation.

This module defines a `TeamStatsAdapter` class that fetches recent team
statistics from the API Sports basketball endpoint.  The `Faz13Engine`
is modified to accept either a `TeamStatsAdapter` instance or a pair of
`(api_key, base_url)` strings.  When provided with strings, it constructs
an `APISportsAdapter` automatically.  The engine then uses the
`TeamBaselineBootstrapper` to build baselines and compute prediction bands.

NOTE: The API Sports service requires a valid API key.  You should set
environment variables `API_SPORTS_KEY` and `API_SPORTS_BASE` when running
this module.  The `APISportsAdapter` contains placeholder logic for
looking up team IDs and games; modify it according to the API Sports
documentation to suit your needs.  Network requests are performed using
the synchronous `requests` library.
"""

from __future__ import annotations

import os
import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import requests

from baseline.team_baseline_store import (
    TeamBaselineStore,
    TeamBaselineBootstrapper,
    TeamStatsAdapter,
    TeamBaseline,
)

######################################################################
# Data classes
######################################################################


@dataclass
class PrematchRequest:
    """Input payload for pre‑match analysis."""

    user_id: int
    league: str
    date: str
    home: str
    away: str


@dataclass
class FixtureContext:
    """Context information for a fixture under analysis."""

    league: str
    date: str
    home: str
    away: str


@dataclass
class Faz13CoreOutput:
    """Output of the pre‑match analysis engine."""

    ctx: FixtureContext
    home_band: List[int]
    away_band: List[int]
    total_band: List[int]
    tempo_flag: str
    blowout_risk: str
    ou_direction: str
    meta: Dict[str, Any]
    notes: List[str]
    market: Dict[str, Any] = field(default_factory=dict)
    home_avg: TeamBaseline | None = None
    away_avg: TeamBaseline | None = None
    quarters: List[int] | None = None

    def render_html(self) -> str:
        """Render the analysis as a plain-text/HTML fragment for Telegram."""
        parts: List[str] = []
        parts.append("FAZ-13 Ön Analiz\n")
        parts.append(
            f"Maç: {self.ctx.home} vs {self.ctx.away} | Lig: {self.ctx.league} | Tarih: {self.ctx.date}\n"
        )
        if self.total_band and len(self.total_band) == 2:
            parts.append(f"Toplam (Tahmin): {self.total_band[0]}–{self.total_band[1]}\n")
        if self.home_band and len(self.home_band) == 2:
            parts.append(f"{self.ctx.home} Bant: {self.home_band[0]}–{self.home_band[1]}\n")
        if self.away_band and len(self.away_band) == 2:
            parts.append(f"{self.ctx.away} Bant: {self.away_band[0]}–{self.away_band[1]}\n")
        parts.append(f"Tempo: {self.tempo_flag} | Blowout riski: {self.blowout_risk}\n")
        parts.append(f"Alt/Üst yönü: {self.ou_direction}\n")
        # Meta fields
        conf = self.meta.get("confidence")
        risk = self.meta.get("risk")
        if conf is not None or risk is not None:
            details: List[str] = []
            if conf is not None:
                details.append(f"Güven: {conf}")
            if risk is not None:
                details.append(f"Risk: {risk}")
            parts.append(" | ".join(details) + "\n")
        # Notes
        if self.notes:
            parts.append("\nNotlar:")
            for note in self.notes:
                parts.append(f"\n- {note}")
        return "".join(parts)


######################################################################
# API Sports Stats Adapter
######################################################################


class APISportsAdapter(TeamStatsAdapter):
    """
    Fetch recent team aggregate statistics from the API Sports basketball endpoint.

    API Sports endpoints require a header `X-RapidAPI-Key` or `x-apisports-key` and
    optionally a host header.  See https://www.api-basketball.com/documentation
    for details on available routes.
    """

    def __init__(self, api_key: str, base_url: Optional[str] = None) -> None:
        self.api_key = api_key
        self.base_url = base_url or "https://v1.basketball.api-sports.io"
        # Use the `Host` header expected by API Sports (if needed)
        self.headers = {
            "X-RapidAPI-Key": self.api_key,
            # API sports may accept `x-apisports-key` header as well
            "x-apisports-key": self.api_key,
        }

    def _get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
        resp = requests.get(url, params=params, headers=self.headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        # API Sports returns a dict with a "response" list; we extract it
        if isinstance(data, dict) and "response" in data:
            return data["response"]
        return data

    def _find_team_id(self, league: str, team_name: str) -> Optional[int]:
        """Lookup a team's ID by its name within the specified league."""
        try:
            # Search teams endpoint; API Sports may use `search` parameter
            response = self._get("teams", {"search": team_name})
            # Filter by league if available
            for team in response:
                if team_name.lower() in team.get("name", "").lower():
                    # Team IDs are typically numeric
                    return int(team.get("id"))
        except Exception:
            return None
        return None

    def _get_recent_games(self, team_id: int, n_games: int) -> List[Dict[str, Any]]:
        """Retrieve the last `n_games` games for a given team ID."""
        try:
            # API Sports uses `team` and `last` query params to fetch recent games
            response = self._get("games", {"team": team_id, "last": n_games})
            # Each game entry contains `teams`, `scores`, etc.
            return response if isinstance(response, list) else []
        except Exception:
            return []

    def fetch_team_recent_aggregate(self, league: str, team: str, n_games: int) -> Optional[Dict[str, Any]]:
        """
        Fetch recent aggregate statistics for a team.

        Returns a dictionary with the following keys:
            - n_games: number of games considered
            - pts_for: average points scored
            - pts_against: average points conceded
            - pace: average possessions (placeholder)
            - stdev_total: standard deviation of total points
        If the team ID cannot be found or no games are returned, None is returned.
        """
        team_id = self._find_team_id(league, team)
        if not team_id:
            return None
        games = self._get_recent_games(team_id, n_games)
        if not games:
            return None
        pts_for_list: List[int] = []
        pts_against_list: List[int] = []
        totals: List[int] = []
        for g in games:
            try:
                # API Sports returns scores nested under `scores` with `home` and `away` dictionaries
                scores = g.get("scores", {})
                home_score = scores.get("home", {}).get("total")
                away_score = scores.get("away", {}).get("total")
                if home_score is None or away_score is None:
                    continue
                # Determine whether this team was home or away
                home_info = g.get("teams", {}).get("home", {})
                away_info = g.get("teams", {}).get("away", {})
                if home_info.get("id") == team_id:
                    pts_for_list.append(home_score)
                    pts_against_list.append(away_score)
                elif away_info.get("id") == team_id:
                    pts_for_list.append(away_score)
                    pts_against_list.append(home_score)
                totals.append(home_score + away_score)
            except Exception:
                continue
        if not pts_for_list or not pts_against_list:
            return None
        n_games_eff = len(pts_for_list)
        avg_pts_for = sum(pts_for_list) / n_games_eff
        avg_pts_against = sum(pts_against_list) / n_games_eff
        stdev_total = statistics.pstdev(totals) if len(totals) > 1 else 9.0
        # Pace is not directly available; approximate by possessions per game
        pace = 1.0
        return {
            "n_games": n_games_eff,
            "pts_for": avg_pts_for,
            "pts_against": avg_pts_against,
            "pace": pace,
            "stdev_total": stdev_total,
        }


######################################################################
# FAZ-13 Engine
######################################################################


class Faz13Engine:
    """
    Pre‑match analysis engine using TeamBaselineBootstrapper and a real stats adapter.

    This engine constructs team baselines by calling an injected `TeamStatsAdapter`.
    You may pass in a `TeamStatsAdapter` instance directly or simply provide an
    API key and base URL (strings), in which case an `APISportsAdapter` is
    created automatically.  Baselines are stored on disk via `TeamBaselineStore`.
    """

    def __init__(self, adapter_or_key: Any, base_url: Optional[str] = None, baseline_dir: str = "data/baselines") -> None:
        if isinstance(adapter_or_key, TeamStatsAdapter):
            self.adapter = adapter_or_key
        else:
            # Assume strings correspond to an API key and optional base URL
            key = str(adapter_or_key)
            url = base_url or os.getenv("API_SPORTS_BASE", "https://v1.basketball.api-sports.io")
            self.adapter = APISportsAdapter(key, url)
        self.store = TeamBaselineStore(base_dir=baseline_dir)
        self.bootstrapper = TeamBaselineBootstrapper(self.store, self.adapter)

    def _risk_label(self, conf: float, issues: List[str]) -> str:
        if "no_team_data" in issues:
            return "HIGH"
        if conf >= 75:
            return "LOW"
        if conf >= 60:
            return "MID"
        return "HIGH"

    def pre_analyze(self, league: str, home: str, away: str) -> Dict[str, Any]:
        notes: List[str] = []
        issues: List[str] = []
        # Ensure baselines exist; bootstrapper will attempt to fetch team stats
        home_base = self.bootstrapper.ensure(league, home, min_games=6)
        away_base = self.bootstrapper.ensure(league, away, min_games=6)
        baseline: Dict[str, Any] = {}
        bands: Dict[str, Any] = {}
        signals: Dict[str, Any] = {}
        meta: Dict[str, Any] = {}
        if home_base is None or away_base is None:
            issues.append("no_team_data")
            notes.append(
                "UYARI: Team baseline alınamadı – neutral baseline (0/0) kullanıldı."
            )
            # Use neutral baseline
            baseline = {"mu_total": 0.0, "sigma_total": 9.0, "pace": 1.0}
            bands = {"ft": [0, 0]}
            signals = {"tempo_flag": "NORMAL", "blowout_risk": "LOW", "alt_ust": "NO_EDGE"}
            meta = {"confidence": 63.0, "risk": self._risk_label(63.0, issues)}
        else:
            # Compute expected total based on team baselines
            mu_total = (home_base.pts_for + home_base.pts_against + away_base.pts_for + away_base.pts_against) / 2.0
            sigma_total = (home_base.stdev_total + away_base.stdev_total) / 2.0
            baseline = {"mu_total": mu_total, "sigma_total": sigma_total, "pace": (home_base.pace + away_base.pace) / 2.0}
            lo = int(round(mu_total - 6))
            hi = int(round(mu_total + 6))
            bands = {"ft": [lo, hi]}
            signals = {"tempo_flag": "NORMAL", "blowout_risk": "LOW", "alt_ust": "NO_EDGE"}
            meta = {"confidence": 75.0, "risk": self._risk_label(75.0, issues)}
        return {
            "baseline": baseline,
            "bands": bands,
            "signals": signals,
            "meta": meta,
            "notes": notes,
        }

    async def run_prematch(self, request: PrematchRequest) -> Faz13CoreOutput:
        # Run analysis synchronously then wrap results into an output object
        result = self.pre_analyze(request.league, request.home, request.away) or {}
        baseline = result.get("baseline", {}) or {}
        bands = result.get("bands", {}) or {}
        signals = result.get("signals", {}) or {}
        meta = result.get("meta", {}) or {}
        notes = result.get("notes", []) or []
        total_band = bands.get("ft", [0, 0])
        mu_total = baseline.get("mu_total")
        if isinstance(mu_total, (int, float)):
            half_mu = mu_total / 2.0
            home_band = [int(round(half_mu - 3)), int(round(half_mu + 3))]
            away_band = home_band.copy()
        else:
            lo, hi = total_band
            home_band = [int(round(lo / 2.0)), int(round(hi / 2.0))]
            away_band = home_band.copy()
        ctx = FixtureContext(
            league=request.league,
            date=request.date,
            home=request.home,
            away=request.away,
        )
        return Faz13CoreOutput(
            ctx=ctx,
            home_band=home_band,
            away_band=away_band,
            total_band=total_band,
            tempo_flag=signals.get("tempo_flag", "UNKNOWN"),
            blowout_risk=signals.get("blowout_risk", "UNKNOWN"),
            ou_direction=signals.get("alt_ust", "NO_EDGE"),
            meta=meta,
            notes=notes,
            # Home and away averages are not returned here; downstream consumers
            # can query TeamBaselineStore separately if needed.
            home_avg=None,
            away_avg=None,
      )

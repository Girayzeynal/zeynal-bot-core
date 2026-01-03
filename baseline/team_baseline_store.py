from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional
from statistics import mean, pstdev


# =====================================================
# DATA MODELS
# =====================================================

@dataclass
class TeamBaseline:
    league: str
    team: str
    n_games: int
    pts_for: float
    pts_against: float
    pace: float
    stdev_total: float
    updated_ts: int


@dataclass
class TeamGameRecord:
    ts_utc: int
    pts_for: float
    pts_against: float
    pace: float
    home: bool


# =====================================================
# STORE
# =====================================================

class TeamBaselineStore:
    """
    File-based baseline + recent game series store.
    """

    def __init__(self, base_dir: str = "data/baselines") -> None:
        self.base_dir = base_dir
        self.series_dir = os.path.join(self.base_dir, "series")
        os.makedirs(self.base_dir, exist_ok=True)
        os.makedirs(self.series_dir, exist_ok=True)

    def _key(self, league: str, team: str) -> str:
        return f"{league.strip().upper().replace(' ', '_')}__{team.strip().upper().replace(' ', '_')}"

    def _baseline_path(self, league: str, team: str) -> str:
        return os.path.join(self.base_dir, f"TEAM__{self._key(league, team)}.json")

    def _series_path(self, league: str, team: str) -> str:
        return os.path.join(self.series_dir, f"SERIES__{self._key(league, team)}.json")

    # -------------------------
    # BASELINE
    # -------------------------

    def get(self, league: str, team: str) -> Optional[TeamBaseline]:
        p = self._baseline_path(league, team)
        if not os.path.exists(p):
            return None
        try:
            with open(p, "r", encoding="utf-8") as f:
                return TeamBaseline(**json.load(f))
        except Exception:
            return None

    def put(self, baseline: TeamBaseline) -> None:
        p = self._baseline_path(baseline.league, baseline.team)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(asdict(baseline), f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)

    # -------------------------
    # SERIES
    # -------------------------

    def append_game(
        self,
        league: str,
        team: str,
        pts_for: float,
        pts_against: float,
        pace: float,
        home: bool,
        ts_utc: Optional[int] = None,
        max_games: int = 20,
    ) -> None:
        ts = int(ts_utc or time.time())
        rec = TeamGameRecord(ts, pts_for, pts_against, pace, home)

        path = self._series_path(league, team)
        series: List[Dict[str, Any]] = []

        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    series = json.load(f)
            except Exception:
                series = []

        series.append(asdict(rec))
        series = sorted(series, key=lambda x: x["ts_utc"])[-max_games:]

        with open(path, "w", encoding="utf-8") as f:
            json.dump(series, f, ensure_ascii=False, indent=2)

    def get_series(self, league: str, team: str, n_games: int) -> List[TeamGameRecord]:
        path = self._series_path(league, team)
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return [TeamGameRecord(**r) for r in raw][-n_games:]
        except Exception:
            return []

    # -------------------------
    # ANALYTIC CORE
    # -------------------------

    def compute_dynamic_baseline(
        self, league: str, team: str, n_games: int
    ) -> Optional[Dict[str, float]]:
        series = self.get_series(league, team, n_games)
        if len(series) < max(3, n_games // 2):
            return None

        pts_for = [r.pts_for for r in series]
        pts_against = [r.pts_against for r in series]
        pace = [r.pace for r in series]
        total = [a + b for a, b in zip(pts_for, pts_against)]

        return {
            "n_games": len(series),
            "pts_for": mean(pts_for),
            "pts_against": mean(pts_against),
            "pace": mean(pace),
            "stdev_total": pstdev(total) if len(total) >= 2 else 0.0,
        }


# =====================================================
# BOOTSTRAP (🔥 FIXED)
# =====================================================

class TeamBaselineBootstrapper:
    """
    Multi-source bootstrapper.
    Resolves team name → abbreviation when needed.
    """

    def __init__(self, store: TeamBaselineStore, adapters: List[Any]) -> None:
        self.store = store
        self.adapters = adapters

    async def ensure_async(
        self, league: str, team_name: str, min_games: int = 6
    ) -> Optional[TeamBaseline]:

        existing = self.store.get(league, team_name)
        if existing and existing.n_games >= min_games:
            return existing

        for ad in self.adapters:
            try:
                team_key = team_name

                # 🔥 RESOLVE NAME → ABBR IF SUPPORTED
                resolver = getattr(ad, "resolve_team_abbr", None)
                if callable(resolver):
                    resolved = await resolver(league, team_name)
                    if resolved:
                        team_key = resolved

                fetch = getattr(ad, "fetch_team_recent_games", None)
                if not callable(fetch):
                    continue

                games = await fetch(league, team_key, max(min_games, 10))
                if not games:
                    continue

                for g in games:
                    self.store.append_game(
                        league=league,
                        team=team_name,
                        pts_for=g["pts_for"],
                        pts_against=g["pts_against"],
                        pace=float(g.get("pace") or 100.0),
                        home=bool(g.get("home", False)),
                        ts_utc=g.get("ts_utc"),
                    )

                agg = self.store.compute_dynamic_baseline(league, team_name, min_games)
                if not agg:
                    continue

                baseline = TeamBaseline(
                    league=league,
                    team=team_name,
                    n_games=agg["n_games"],
                    pts_for=agg["pts_for"],
                    pts_against=agg["pts_against"],
                    pace=agg["pace"],
                    stdev_total=agg["stdev_total"],
                    updated_ts=int(time.time()),
                )
                self.store.put(baseline)
                return baseline

            except Exception:
                continue

        return existing 

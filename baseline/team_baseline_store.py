"""
team_baseline_store.py
----------------------
Definitions for persisting and bootstrapping team baseline statistics.  A
team baseline consists of the number of games considered plus aggregate
metrics such as points scored, points allowed, pace and total volatility.

The ``TeamBaselineStore`` saves baselines into JSON files under a
configurable directory.  ``TeamBaselineBootstrapper`` uses a user‑supplied
``TeamStatsAdapter`` to backfill missing baselines by fetching recent
results.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional

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

class TeamBaselineStore:
    """Simple file‑based store for team baselines."""
    def __init__(self, base_dir: str = "data/baselines") -> None:
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)

    def _path(self, league: str, team: str) -> str:
        safe_league = league.strip().upper().replace(" ", "_")
        safe_team = team.strip().upper().replace(" ", "_")
        return os.path.join(self.base_dir, f"TEAM__{safe_league}__{safe_team}.json")

    def get(self, league: str, team: str) -> Optional[TeamBaseline]:
        p = self._path(league, team)
        if not os.path.exists(p):
            return None
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            return TeamBaseline(**data)
        except Exception:
            # corrupted file -> treat as missing
            return None

    def put(self, baseline: TeamBaseline) -> None:
        p = self._path(baseline.league, baseline.team)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(asdict(baseline), f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)

class TeamBaselineBootstrapper:
    """Automatically create a team baseline when none exists."""
    def __init__(self, store: TeamBaselineStore, adapter: "TeamStatsAdapter") -> None:
        self.store = store
        self.adapter = adapter

    def ensure(self, league: str, team: str, min_games: int = 6) -> Optional[TeamBaseline]:
        existing = self.store.get(league, team)
        if existing and existing.n_games >= min_games:
            return existing
        # Try fetch last N games stats via adapter
        stats = self.adapter.fetch_team_recent_aggregate(
            league=league, team=team, n_games=max(min_games, 8)
        )
        if not stats:
            return existing  # still None or old
        baseline = TeamBaseline(
            league=league,
            team=team,
            n_games=int(stats.get("n_games", 0)),
            pts_for=float(stats.get("pts_for", 0.0)),
            pts_against=float(stats.get("pts_against", 0.0)),
            pace=float(stats.get("pace", 1.0)),
            stdev_total=float(stats.get("stdev_total", 9.0)),
            updated_ts=int(time.time()),
        )
        self.store.put(baseline)
        return baseline

class TeamStatsAdapter:
    """Interface for providing team aggregate statistics.
    Your project should implement this adapter to fetch aggregate team stats from
    your preferred source (database, API or scraper).  The method must return a
    dictionary containing at least the keys: n_games, pts_for, pts_against,
    pace and stdev_total.
    """
    def fetch_team_recent_aggregate(self, league: str, team: str, n_games: int) -> Optional[Dict[str, Any]]:
        raise NotImplementedError(
            "Implement using your existing stats provider (db/api/scraper)."
        ) 

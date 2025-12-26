# baseline/team_baseline_store.py
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any


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
    def __init__(self, base_dir: str = "data/baselines"):
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
                d = json.load(f)
            return TeamBaseline(**d)
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
    """
    Baseline yoksa otomatik üretir.
    Not: Burada API kısmı "adapter" üzerinden; elindeki mevcut veri kaynağına bağlarsın.
    """

    def __init__(self, store: TeamBaselineStore, adapter: "TeamStatsAdapter"):
        self.store = store
        self.adapter = adapter

    def ensure(self, league: str, team: str, min_games: int = 6) -> Optional[TeamBaseline]:
        existing = self.store.get(league, team)
        if existing and existing.n_games >= min_games:
            return existing

        # Try fetch last N games stats
        stats = self.adapter.fetch_team_recent_aggregate(league=league, team=team, n_games=max(min_games, 8))
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
    """
    Senin projede bu adapter’i:
    - hali hazırda kullandığın endpoint’e (api-basketball / kendi scraperın / db) bağlayacaksın.
    Bu dosya 'çalışır iskelet' veriyor.
    """
    def fetch_team_recent_aggregate(self, league: str, team: str, n_games: int) -> Optional[Dict[str, Any]]:
        raise NotImplementedError("Implement using your existing stats provider (db/api/scraper).")

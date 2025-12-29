import time
from dataclasses import dataclass
from typing import Dict, Optional


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
    def __init__(self):
        self._store: Dict[str, TeamBaseline] = {}

    def _key(self, league: str, team: str) -> str:
        return f"{league.lower()}::{team.lower()}"

    def get(self, league: str, team: str) -> Optional[TeamBaseline]:
        return self._store.get(self._key(league, team))

    def put(self, baseline: TeamBaseline):
        self._store[self._key(baseline.league, baseline.team)] = baseline


class TeamBaselineBootstrapper:
    def __init__(self, store: TeamBaselineStore):
        self.store = store

    def bootstrap(self, league: str, team: str, stats: Optional[dict]) -> TeamBaseline:
        existing = self.store.get(league, team)
        if existing:
            return existing

        # 🔥 KRİTİK FIX: stats yoksa bile baseline üret
        if not stats:
            baseline = TeamBaseline(
                league=league,
                team=team,
                n_games=0,
                pts_for=0.0,
                pts_against=0.0,
                pace=0.0,
                stdev_total=0.0,
                updated_ts=int(time.time()),
            )
            self.store.put(baseline)
            return baseline

        baseline = TeamBaseline(
            league=league,
            team=team,
            n_games=stats.get("games", 1),
            pts_for=stats.get("pts_for", 0.0),
            pts_against=stats.get("pts_against", 0.0),
            pace=stats.get("pace", 0.0),
            stdev_total=stats.get("stdev_total", 0.0),
            updated_ts=int(time.time()),
        )

        self.store.put(baseline)
        return baseline

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Iterable
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
    Backward compatible with existing TeamBaseline usage.
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
    # BASELINE (OLD API)
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
    # SERIES (NEW)
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
        """
        Append a single game to the rolling time series.
        """
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
            records = [TeamGameRecord(**r) for r in raw]
            return records[-n_games:]
        except Exception:
            return []

    # -------------------------
    # ANALYTIC HELPERS
    # -------------------------

    def compute_dynamic_baseline(
        self, league: str, team: str, n_games: int
    ) -> Optional[Dict[str, float]]:
        """
        Returns analytically meaningful aggregates derived from time series.
        """
        series = self.get_series(league, team, n_games)
        if len(series) < max(3, n_games // 2):
            return None

        pts_for = [r.pts_for for r in series]
        pts_against = [r.pts_against for r in series]
        pace = [r.pace for r in series]

        total_pts = [a + b for a, b in zip(pts_for, pts_against)]

        return {
            "n_games": len(series),
            "pts_for": mean(pts_for),
            "pts_against": mean(pts_against),
            "pace": mean(pace),
            "stdev_total": pstdev(total_pts) if len(total_pts) >= 2 else 0.0,
        }


# =====================================================
# BOOTSTRAP (MULTI-SOURCE PATCH)
# =====================================================

class TeamBaselineBootstrapper:
    """
    Creates/updates baseline AND feeds the rolling series.

    PATCH:
    - Supports MULTIPLE adapters
    - Tries adapters in order (primary → fallback)
    - Backward compatible with single-adapter usage
    """

    def __init__(
        self,
        store: TeamBaselineStore,
        adapter: Optional["TeamStatsAdapter"] = None,
        adapters: Optional[Iterable["TeamStatsAdapter"]] = None,
    ) -> None:
        self.store = store

        if adapters is not None:
            self.adapters: List["TeamStatsAdapter"] = list(adapters)
        elif adapter is not None:
            # backward compatibility
            self.adapters = [adapter]
        else:
            self.adapters = []

    def ensure(self, league: str, team: str, min_games: int = 6) -> Optional[TeamBaseline]:
        existing = self.store.get(league, team)
        if existing and existing.n_games >= min_games:
            return existing

        games: Optional[List[Dict[str, Any]]] = None
        source_used: Optional[str] = None

        # 🔥 MULTI-SOURCE TRY (PRIMARY → FALLBACK)
        for ad in self.adapters:
            try:
                stats = ad.fetch_team_recent_games(
                    league=league,
                    team=team,
                    n_games=max(min_games, 10),
                )
                if stats:
                    games = stats
                    source_used = getattr(ad, "name", ad.__class__.__name__)
                    break
            except Exception:
                continue

        if not games:
            return existing

        # ---- feed rolling series
        for g in games:
            try:
                self.store.append_game(
                    league=league,
                    team=team,
                    pts_for=float(g["pts_for"]),
                    pts_against=float(g["pts_against"]),
                    pace=float(g.get("pace") or 100.0),  # neutral fallback (NOT league avg)
                    home=bool(g.get("home", False)),
                    ts_utc=g.get("ts_utc"),
                )
            except Exception:
                continue

        agg = self.store.compute_dynamic_baseline(league, team, min_games)
        if not agg:
            return existing

        baseline = TeamBaseline(
            league=league,
            team=team,
            n_games=agg["n_games"],
            pts_for=agg["pts_for"],
            pts_against=agg["pts_against"],
            pace=agg["pace"],
            stdev_total=agg["stdev_total"],
            updated_ts=int(time.time()),
        )
        self.store.put(baseline)

        # (Optional) internal trace – not persisted
        # source_used tells which adapter succeeded

        return baseline


# =====================================================
# ADAPTER INTERFACE (UPDATED)
# =====================================================

class TeamStatsAdapter:
    """
    Adapter must return per-game time series in UTC.
    """

    def fetch_team_recent_games(
        self, league: str, team: str, n_games: int
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Each item:
        {
            "ts_utc": int,
            "pts_for": float,
            "pts_against": float,
            "pace": float,
            "home": bool
        }
        """
        raise NotImplementedError  

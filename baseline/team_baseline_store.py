from __future__ import annotations

import json
import os
import time
import asyncio
import inspect
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
# BOOTSTRAP (MULTI-SOURCE + ASYNC AWARE)
# =====================================================

class TeamBaselineBootstrapper:
    """
    Multi-source bootstrapper.

    - Tries adapters in order (primary -> fallback)
    - Async-aware: supports async adapters (like ESPNAdapter/SportsDataIOAdapter)
    - Resolves team name -> abbreviation via adapter if possible
    - Stores series under ORIGINAL team name (so /analyze names work)
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
            self.adapters = [adapter]
        else:
            self.adapters = []

    @staticmethod
    def _looks_like_abbr(team: str) -> bool:
        t = (team or "").strip()
        return 2 <= len(t) <= 4 and " " not in t

    async def _resolve_abbr(self, league: str, team: str) -> Optional[str]:
        """
        Try to resolve team name -> abbr using any adapter that offers resolve_team_abbr().
        If already abbr-like, return upper.
        """
        if self._looks_like_abbr(team):
            return team.strip().upper()

        for ad in self.adapters:
            fn = getattr(ad, "resolve_team_abbr", None)
            if callable(fn):
                try:
                    res = fn(league, team)
                    if inspect.isawaitable(res):
                        res = await res
                    if isinstance(res, str) and res.strip():
                        return res.strip().upper()
                except Exception:
                    continue
        return None

    async def ensure_async(self, league: str, team: str, min_games: int = 6) -> Optional[TeamBaseline]:
        existing = self.store.get(league, team)
        if existing and existing.n_games >= min_games:
            return existing

        if not self.adapters:
            return existing

        # Resolve team name to abbr for providers
        abbr = await self._resolve_abbr(league, team)
        team_for_fetch = abbr or team  # if cannot resolve, try raw (some adapters may accept it)

        games: Optional[List[Dict[str, Any]]] = None

        for ad in self.adapters:
            try:
                res = ad.fetch_team_recent_games(league=league, team=team_for_fetch, n_games=max(min_games, 10))
                if inspect.isawaitable(res):
                    res = await res
                if isinstance(res, list) and res:
                    games = res
                    break
            except Exception:
                continue

        if not games:
            return existing

        # Feed rolling series under ORIGINAL team name
        for g in games:
            try:
                pace_val = g.get("pace")
                if pace_val is None:
                    pace_val = 100.0  # neutral fallback; NOT league avg
                self.store.append_game(
                    league=league,
                    team=team,
                    pts_for=float(g["pts_for"]),
                    pts_against=float(g["pts_against"]),
                    pace=float(pace_val),
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
            n_games=int(agg["n_games"]),
            pts_for=float(agg["pts_for"]),
            pts_against=float(agg["pts_against"]),
            pace=float(agg["pace"]),
            stdev_total=float(agg["stdev_total"]),
            updated_ts=int(time.time()),
        )
        self.store.put(baseline)
        return baseline

    # Legacy sync entrypoint (for old sync adapters)
    def ensure(self, league: str, team: str, min_games: int = 6) -> Optional[TeamBaseline]:
        """
        If you're using async adapters (ESPN/SportsDataIO), call ensure_async() from an async context.
        This sync method is kept for backward compatibility only.
        """
        # If there is a running event loop, user MUST await ensure_async
        try:
            asyncio.get_running_loop()
            # running loop exists -> cannot block here safely
            return self.store.get(league, team)
        except RuntimeError:
            # no running loop -> safe to run
            return asyncio.run(self.ensure_async(league, team, min_games=min_games))


# =====================================================
# ADAPTER INTERFACE
# =====================================================

class TeamStatsAdapter:
    """
    Adapter must return per-game time series in UTC.
    """

    def fetch_team_recent_games(
        self, league: str, team: str, n_games: int
    ) -> Optional[List[Dict[str, Any]]]:
        raise NotImplementedError 

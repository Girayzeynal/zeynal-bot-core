from __future__ import annotations

import json
import os
import time
import logging
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional
from statistics import mean, pstdev


# ============================
# LOGGING (DIAG)
# ============================
logger = logging.getLogger("zeynal-core.baseline")


# ============================
# DATA MODELS
# ============================

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


# ============================
# STORE
# ============================

class TeamBaselineStore:
    """
    File-based baseline + recent game series store.
    Canonical key = team string passed in (we will pass ABBR).
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


# ============================
# BOOTSTRAP (FINAL)
# ============================

class TeamBaselineBootstrapper:
    """
    FINAL MULTI-SOURCE BOOTSTRAPPER
    - Canonical key = ABBR
    - main.py DOES NOT map names

    DIAG PATCH:
    - Hangi adapter kaç maç döndürdü
    - Hangi adapter hata verdi
    - Append sonrası series kaç oldu
    """

    def __init__(self, store: TeamBaselineStore, adapters: List[Any]) -> None:
        self.store = store
        self.adapters = adapters

    async def _canonical(self, league: str, team_input: str) -> str:
        t = (team_input or "").strip()
        if not t:
            return t
        if 2 <= len(t) <= 4 and " " not in t:
            return t.upper()

        for ad in self.adapters:
            resolver = getattr(ad, "resolve_team_abbr", None)
            if callable(resolver):
                try:
                    abbr = await resolver(league, t)
                    if abbr:
                        return str(abbr).upper().strip()
                except Exception as e:
                    logger.info(f"[BASELINE-DIAG] resolver_err adapter={ad.__class__.__name__} team_input='{t}' err={e}")
                    continue
        return t

    async def ensure_async(
        self, league: str, team_input: str, min_games: int = 6
    ) -> Optional[TeamBaseline]:
        team = await self._canonical(league, team_input)

        existing = self.store.get(league, team)
        if existing and existing.n_games >= min_games:
            logger.info(f"[BASELINE-DIAG] existing_ok league={league} team={team} n_games={existing.n_games}")
            return existing

        # DIAG: başlangıç series sayısı
        try:
            pre_series_n = len(self.store.get_series(league, team, 50))
        except Exception:
            pre_series_n = -1
        logger.info(f"[BASELINE-DIAG] start league={league} team_input='{team_input}' canonical='{team}' pre_series={pre_series_n} min_games={min_games}")

        for ad in self.adapters:
            try:
                fetch = getattr(ad, "fetch_team_recent_games", None)
                if not callable(fetch):
                    logger.info(f"[BASELINE-DIAG] skip adapter={ad.__class__.__name__} reason=no_fetch_fn")
                    continue

                want_n = max(int(min_games), 10)
                games = await fetch(league, team, want_n)

                # DIAG: adapter kaç maç döndürdü
                logger.info(
                    f"[BASELINE-DIAG] fetch adapter={ad.__class__.__name__} league={league} team={team} want={want_n} "
                    f"got={'None' if games is None else len(games)}"
                )

                if not games:
                    continue

                # DIAG: ilk/son ts (varsa)
                try:
                    ts_list = [int(g.get("ts_utc") or 0) for g in games if isinstance(g, dict)]
                    ts_list = [t for t in ts_list if t > 0]
                    if ts_list:
                        logger.info(f"[BASELINE-DIAG] fetch_ts adapter={ad.__class__.__name__} team={team} ts_min={min(ts_list)} ts_max={max(ts_list)}")
                except Exception:
                    pass

                wrote = 0
                for g in games:
                    self.store.append_game(
                        league=league,
                        team=team,
                        pts_for=float(g["pts_for"]),
                        pts_against=float(g["pts_against"]),
                        pace=float(g.get("pace") or 100.0),
                        home=bool(g.get("home", False)),
                        ts_utc=g.get("ts_utc"),
                    )
                    wrote += 1

                # DIAG: append sonrası series sayısı
                try:
                    post_series_n = len(self.store.get_series(league, team, 50))
                except Exception:
                    post_series_n = -1

                logger.info(f"[BASELINE-DIAG] appended adapter={ad.__class__.__name__} team={team} wrote={wrote} post_series={post_series_n}")

                agg = self.store.compute_dynamic_baseline(league, team, min_games)
                if not agg:
                    logger.info(f"[BASELINE-DIAG] baseline_compute_failed adapter={ad.__class__.__name__} team={team} min_games={min_games}")
                    continue

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

                logger.info(f"[BASELINE-DIAG] BASELINE_OK adapter={ad.__class__.__name__} league={league} team={team} n_games={baseline.n_games}")
                return baseline

            except Exception as e:
                logger.info(f"[BASELINE-DIAG][ERROR] adapter={ad.__class__.__name__} league={league} team={team} err={e}")
                continue

        logger.info(f"[BASELINE-DIAG] BASELINE_FAIL league={league} team={team} (no adapter produced usable games)")
        return existing

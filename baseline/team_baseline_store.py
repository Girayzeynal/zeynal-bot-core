from __future__ import annotations

import json
import math
import os
import re
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
    game_id: Optional[str] = None
    source: Optional[str] = None


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
        # Never allow untrusted team/league strings to escape the data directory.
        parts = []
        for value in (league, team):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("invalid baseline identity")
            normalized = value.strip().upper().replace(" ", "_")
            if not re.fullmatch(r"[A-Z0-9_\\-]{1,80}", normalized):
                raise ValueError("unsafe baseline identity")
            parts.append(normalized)
        return "__".join(parts)

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
        game_id: Optional[str] = None,
        source: Optional[str] = None,
    ) -> None:
        # Reject malformed timestamps and statistics before touching persistent state.
        if (type(ts_utc) is not int or ts_utc <= 0
                or ts_utc > int(time.time())
                or not all(math.isfinite(float(x)) for x in (pts_for, pts_against, pace))
                or pts_for < 0 or pts_against < 0 or pace <= 0):
            raise ValueError("invalid historical game record")
        if game_id is not None and (not isinstance(game_id, str) or not game_id.strip()):
            raise ValueError("invalid game_id")
        if source is not None and (not isinstance(source, str) or not source.strip()):
            raise ValueError("invalid source")
        if game_id is not None and source is None:
            raise ValueError("game_id requires source")
        ts = ts_utc
        rec = TeamGameRecord(ts, pts_for, pts_against, pace, home, game_id, source)

        path = self._series_path(league, team)
        series: List[Dict[str, Any]] = []

        if os.path.exists(path):
            # Corrupt history must not be silently discarded and overwritten.
            with open(path, "r", encoding="utf-8") as f:
                series = json.load(f)
            if not isinstance(series, list) or not all(isinstance(r, dict) for r in series):
                raise ValueError("invalid persisted game series")

        # A provider identity must never silently change its game facts.
        # Cross-provider reconciliation requires an independently verified mapping.
        if game_id is not None:
            matches = [r for r in series if (
                r.get("game_id") == game_id and r.get("source") == source
            )]
            if matches:
                if len(matches) != 1 or any(
                    r.get(field) != getattr(rec, field)
                    for r in matches
                    for field in ("ts_utc", "pts_for", "pts_against", "pace", "home")
                ):
                    raise ValueError("conflicting game record for provider identity")
                return  # Idempotent repeated fetch; do not rewrite the file.
        else:
            series = [r for r in series if not (
                r.get("game_id") is None and int(r.get("ts_utc", -1)) == ts
            )]
        series.append(asdict(rec))
        series = sorted(series, key=lambda x: x["ts_utc"])[-max_games:]

        # Atomic replacement prevents a crash from truncating the history file.
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(series, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

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

    def get_series_before(self, league: str, team: str, cutoff_ts_utc: int, n_games: int) -> List[TeamGameRecord]:
        """Select only records older than the requested fixture."""
        if n_games <= 0:
            return []
        records = self.get_series(league, team, 100000)
        return sorted(
            (r for r in records if 0 < r.ts_utc < int(cutoff_ts_utc)),
            key=lambda r: r.ts_utc,
        )[-n_games:]

    def compute_baseline_before(
        self, league: str, team: str, cutoff_ts_utc: int,
        n_games: int = 10, min_games: int = 6,
    ) -> Optional[Dict[str, float]]:
        """Compute a baseline exclusively from pre-fixture games."""
        series = self.get_series_before(league, team, cutoff_ts_utc, n_games)
        if len(series) < min_games:
            return None
        pf = [r.pts_for for r in series]
        pa = [r.pts_against for r in series]
        totals = [a + b for a, b in zip(pf, pa)]
        return {
            "n_games": len(series),
            "pts_for": mean(pf),
            "pts_against": mean(pa),
            "pace": mean(r.pace for r in series),
            "stdev_total": pstdev(totals) if len(totals) > 1 else 0.0,
        }

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
        # A sufficient sample is not necessarily fresh. Refresh stale baselines
        # rather than returning them and letting the caller reject them forever.
        now_ts = int(time.time())
        if existing and existing.n_games >= min_games and 0 <= now_ts - int(existing.updated_ts) <= 7 * 86400:
            logger.info(f"[BASELINE-DIAG] existing_ok league={league} team={team} n_games={existing.n_games}")
            return existing
        if existing:
            logger.info(
                "[BASELINE-DIAG] refresh_required league=%s team=%s n_games=%s age_seconds=%s",
                league, team, existing.n_games, now_ts - int(existing.updated_ts),
            )

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
                    # Missing measured pace must not become a synthetic baseline.
                    raw_pace = g.get("pace") if isinstance(g, dict) else None
                    try:
                        measured_pace = float(raw_pace) if raw_pace is not None else None
                    except (TypeError, ValueError):
                        measured_pace = None
                    if measured_pace is None or not math.isfinite(measured_pace) or measured_pace <= 0:
                        logger.info("[BASELINE-DIAG] skip game adapter=%s reason=pace_unavailable", ad.__class__.__name__)
                        continue
                    self.store.append_game(
                        league=league,
                        team=team,
                        pts_for=float(g["pts_for"]),
                        pts_against=float(g["pts_against"]),
                        pace=measured_pace,
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
        # A stale/undersampled baseline must not be reported as refreshed.
        return None

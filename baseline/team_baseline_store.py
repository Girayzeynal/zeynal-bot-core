from __future__ import annotations

import json
import hashlib
import math
import os
import re
import tempfile
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
    timestamp_precision: str = "unknown"


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
        # Preserve existing canonical ASCII keys for deployed NBA records.
        # Names containing whitespace or Unicode use a versioned digest so
        # distinct names cannot alias through space-to-underscore conversion.
        values = []
        for value in (league, team):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("invalid baseline identity")
            normalized = value.strip().upper()
            if (len(normalized) > 160 or any(ord(ch) < 32 or ord(ch) == 127 for ch in normalized)
                    or "/" in normalized or "\\" in normalized
                    or any(0xD800 <= ord(ch) <= 0xDFFF for ch in normalized)):
                # Reject lone UTF-16 surrogate code points before UTF-8 encoding.
                raise ValueError("unsafe baseline identity")
            values.append(normalized)
        if all(re.fullmatch(r"[A-Z0-9_-]{1,80}", x) and "__" not in x
               for x in values):
            return "__".join(values)
        # Domain-separated, length-delimited UTF-8 encoding; never use raw
        # user input as a filename. Legacy keys remain untouched.
        encoded = b"".join(
            len(x.encode("utf-8")).to_bytes(4, "big") + x.encode("utf-8")
            for x in values
        )
        return "V2_" + hashlib.sha256(b"baseline-key-v2\\0" + encoded).hexdigest()

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
        self._atomic_json_write(p, asdict(baseline))

    @staticmethod
    def _atomic_json_write(path: str, payload: Any) -> None:
        # Unique temporary files avoid collisions between independent writers.
        # This protects file replacement, not read-modify-write concurrency.
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=os.path.dirname(path),
                prefix=".baseline-", suffix=".tmp", delete=False,
            ) as handle:
                tmp = handle.name
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
            tmp = None
        finally:
            if tmp is not None:
                try:
                    os.unlink(tmp)
                except FileNotFoundError:
                    pass

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
        timestamp_precision: str = "unknown",
    ) -> None:
        # Reject malformed timestamps and statistics before touching persistent state.
        stats = (pts_for, pts_against, pace)
        if (type(ts_utc) is not int or ts_utc <= 0
                or ts_utc > int(time.time())
                or any(type(x) not in (int, float) for x in stats)
                or not all(math.isfinite(x) for x in stats)
                or pts_for < 0 or pts_against < 0 or pace <= 0
                or type(home) is not bool
                or type(max_games) is not int or max_games <= 0):
            raise ValueError("invalid historical game record")
        if game_id is not None and (not isinstance(game_id, str) or not game_id.strip()):
            raise ValueError("invalid game_id")
        if source is not None and (not isinstance(source, str) or not source.strip()):
            raise ValueError("invalid source")
        if game_id is not None and source is None:
            raise ValueError("game_id requires source")
        if source is not None and (source != source.strip() or
                any(ord(ch) < 32 or ord(ch) == 127 for ch in source)):
            raise ValueError("unsafe source identity")
        if game_id is not None and (game_id != game_id.strip() or
                any(ord(ch) < 32 or ord(ch) == 127 for ch in game_id)):
            raise ValueError("unsafe game identity")
        if (source == "nba_com" and timestamp_precision == "exact"):
            raise ValueError("NBA.com game-date records cannot claim exact completion time")
        if (type(timestamp_precision) is not str
                or timestamp_precision not in ("exact", "date_only", "unknown")):
            raise ValueError("invalid timestamp precision")
        ts = ts_utc
        rec = TeamGameRecord(ts, pts_for, pts_against, pace, home, game_id, source, timestamp_precision)

        path = self._series_path(league, team)
        series: List[Dict[str, Any]] = []

        if os.path.exists(path):
            # Corrupt history must not be silently discarded and overwritten.
            with open(path, "r", encoding="utf-8") as f:
                series = json.load(f)
            if not isinstance(series, list) or not all(isinstance(r, dict) for r in series):
                raise ValueError("invalid persisted game series")
            # Validate every persisted row before read-modify-write; otherwise
            # a malformed record could be retained or silently evicted.
            for existing in series:
                try:
                    TeamGameRecord(**existing)
                except (TypeError, ValueError) as exc:
                    raise ValueError("invalid persisted game record") from exc
            seen_provider_ids = set()
            for existing in series:
                existing_id = existing.get("game_id")
                existing_source = existing.get("source")
                if existing_id is not None:
                    if not isinstance(existing_id, str) or not isinstance(existing_source, str):
                        raise ValueError("invalid persisted provider identity")
                    identity = (existing_source, existing_id)
                    if identity in seen_provider_ids:
                        raise ValueError("duplicate persisted provider identity")
                    seen_provider_ids.add(identity)

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
                ) or any(
                    r.get("timestamp_precision", "unknown") != timestamp_precision
                    for r in matches
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
        self._atomic_json_write(path, series)

    def get_series(self, league: str, team: str, n_games: int) -> List[TeamGameRecord]:
        if type(n_games) is not int or n_games <= 0:
            return []
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
        if (type(n_games) is not int or n_games <= 0
                or type(cutoff_ts_utc) is not int or cutoff_ts_utc <= 0):
            return []
        records = self.get_series(league, team, 100000)
        # "exact" is a provider-declared completed-game timestamp, not proof
        # of the actual final buzzer; callers must validate provider semantics.
        # Legacy/unknown and date-only records fail closed for backtesting.
        return sorted(
            (r for r in records if r.timestamp_precision == "exact"
             and 0 < r.ts_utc < cutoff_ts_utc),
            key=lambda r: r.ts_utc,
        )[-n_games:]

    def compute_baseline_before(
        self, league: str, team: str, cutoff_ts_utc: int,
        n_games: int = 10, min_games: int = 6,
    ) -> Optional[Dict[str, float]]:
        """Compute a baseline exclusively from pre-fixture games."""
        if (type(n_games) is not int or n_games <= 0
                or type(min_games) is not int or min_games <= 0
                or min_games > n_games):
            return None
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
        if type(n_games) is not int or n_games <= 0:
            return None
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
                        home=g["home"],
                        ts_utc=g.get("ts_utc"),
                        game_id=g.get("game_id"),
                        source=g.get("source"),
                        timestamp_precision=g.get("timestamp_precision", "unknown"),
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

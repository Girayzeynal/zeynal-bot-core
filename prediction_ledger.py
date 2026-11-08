"""Immutable, idempotent prediction/outcome ledger for offline backtesting.

Predictions are never replaced after insertion. Results are separate, and only
completed games can be evaluated. No remote data is fetched by this module.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import sqlite3
from typing import Optional

from historical_backtest import HistoricalPrediction, BacktestMetrics, evaluate_predictions


@dataclass(frozen=True)
class PredictionRecord:
    fixture_id: str
    league: str
    prediction_ts_utc: int
    expected_home: float
    expected_away: float
    home_win_probability: Optional[float]
    scope: str = "FINAL_WITH_OT"


@dataclass(frozen=True)
class OutcomeRecord:
    fixture_id: str
    league: str
    result_ts_utc: int
    actual_home: int
    actual_away: int
    scope: str = "FINAL_WITH_OT"


class PredictionLedger:
    def __init__(self, db_path: str):
        self.db_path = db_path
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS predictions (
                league TEXT NOT NULL, fixture_id TEXT NOT NULL,
                prediction_ts_utc INTEGER NOT NULL,
                expected_home REAL NOT NULL, expected_away REAL NOT NULL,
                home_win_probability REAL, scope TEXT NOT NULL,
                PRIMARY KEY (league, fixture_id)
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS outcomes (
                league TEXT NOT NULL, fixture_id TEXT NOT NULL,
                result_ts_utc INTEGER NOT NULL,
                actual_home INTEGER NOT NULL, actual_away INTEGER NOT NULL,
                scope TEXT NOT NULL,
                PRIMARY KEY (league, fixture_id)
            )""")

    def record_prediction_version(self, item: PredictionRecord) -> int:
        """Append every requested forecast, including repeated requests in one second."""
        self._identity(item.league, item.fixture_id)
        if type(item.prediction_ts_utc) is not int or item.prediction_ts_utc <= 0:
            raise ValueError("prediction timestamp must be positive UTC epoch seconds")
        if item.scope not in ("REGULATION_ONLY", "FINAL_WITH_OT"):
            raise ValueError("unknown prediction scope")
        if any(not math.isfinite(v) or v < 0 for v in (item.expected_home, item.expected_away)):
            raise ValueError("invalid expected score")
        if item.home_win_probability is not None and (
            not math.isfinite(item.home_win_probability)
            or not 0 <= item.home_win_probability <= 1
        ):
            raise ValueError("invalid win probability")
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS prediction_versions (
                version_id INTEGER PRIMARY KEY AUTOINCREMENT,
                league TEXT NOT NULL, fixture_id TEXT NOT NULL,
                prediction_ts_utc INTEGER NOT NULL,
                expected_home REAL NOT NULL, expected_away REAL NOT NULL,
                home_win_probability REAL, scope TEXT NOT NULL
            )""")
            cursor = db.execute(
                """INSERT INTO prediction_versions
                   (league, fixture_id, prediction_ts_utc, expected_home,
                    expected_away, home_win_probability, scope)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (item.league, item.fixture_id, item.prediction_ts_utc,
                 item.expected_home, item.expected_away,
                 item.home_win_probability, item.scope),
            )
            return int(cursor.lastrowid)

    def prediction_versions(self, league: str, fixture_id: str) -> list[dict]:
        """Return every immutable version in insertion order."""
        self._identity(league, fixture_id)
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS prediction_versions (
                version_id INTEGER PRIMARY KEY AUTOINCREMENT,
                league TEXT NOT NULL, fixture_id TEXT NOT NULL,
                prediction_ts_utc INTEGER NOT NULL,
                expected_home REAL NOT NULL, expected_away REAL NOT NULL,
                home_win_probability REAL, scope TEXT NOT NULL
            )""")
            rows = db.execute(
                """SELECT version_id, prediction_ts_utc, expected_home,
                          expected_away, home_win_probability, scope
                   FROM prediction_versions
                   WHERE league=? AND fixture_id=? ORDER BY version_id""",
                (league, fixture_id),
            ).fetchall()
        return [dict(zip(
            ("version_id", "prediction_ts_utc", "expected_home",
             "expected_away", "home_win_probability", "scope"), row
        )) for row in rows]

    def compare_prediction_versions(self, league: str, fixture_id: str) -> list[dict]:
        """Compare all pregame versions against one recorded final result."""
        versions = self.prediction_versions(league, fixture_id)
        with self._connect() as db:
            outcome = db.execute(
                """SELECT result_ts_utc, actual_home, actual_away, scope
                   FROM outcomes WHERE league=? AND fixture_id=?""",
                (league, fixture_id),
            ).fetchone()
            start_table = db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='fixture_starts'"
            ).fetchone()
            start = db.execute(
                "SELECT start_ts_utc FROM fixture_starts WHERE league=? AND fixture_id=?",
                (league, fixture_id),
            ).fetchone() if start_table else None
        if outcome is None or start is None:
            return []
        result_ts, actual_home, actual_away, scope = outcome
        total = actual_home + actual_away
        comparisons = []
        for v in versions:
            ts = v["prediction_ts_utc"]
            if not (ts < start[0] < result_ts and v["scope"] == scope):
                continue
            predicted_total = v["expected_home"] + v["expected_away"]
            comparisons.append({
                **v,
                "actual_home": actual_home,
                "actual_away": actual_away,
                "home_absolute_error": abs(v["expected_home"] - actual_home),
                "away_absolute_error": abs(v["expected_away"] - actual_away),
                "total_absolute_error": abs(predicted_total - total),
                "winner_correct": (
                    (v["expected_home"] > v["expected_away"]) ==
                    (actual_home > actual_away)
                ) if actual_home != actual_away and v["expected_home"] != v["expected_away"] else None,
            })
        return comparisons

    def _connect(self):
        return sqlite3.connect(self.db_path, timeout=10)

    @staticmethod
    def _identity(league: str, fixture_id: str):
        if not isinstance(league, str) or not league.strip() or not isinstance(fixture_id, str) or not fixture_id.strip():
            raise ValueError("league and fixture_id must be nonempty strings")

    def record_prediction(self, item: PredictionRecord) -> bool:
        self._identity(item.league, item.fixture_id)
        if type(item.prediction_ts_utc) is not int or item.prediction_ts_utc <= 0:
            raise ValueError("prediction timestamp must be positive UTC epoch seconds")
        if item.scope not in ("REGULATION_ONLY", "FINAL_WITH_OT"):
            raise ValueError("unknown prediction scope")
        for score in (item.expected_home, item.expected_away):
            if not math.isfinite(score) or score < 0:
                raise ValueError("invalid expected score")
        p = item.home_win_probability
        if p is not None and (not math.isfinite(p) or not 0 <= p <= 1):
            raise ValueError("invalid win probability")
        with self._connect() as db:
            cursor = db.execute(
                "INSERT OR IGNORE INTO predictions VALUES (?, ?, ?, ?, ?, ?, ?)",
                (item.league, item.fixture_id, item.prediction_ts_utc,
                 item.expected_home, item.expected_away, p, item.scope),
            )
            return cursor.rowcount == 1

    def record_outcome(self, item: OutcomeRecord) -> bool:
        self._identity(item.league, item.fixture_id)
        if type(item.result_ts_utc) is not int or item.result_ts_utc <= 0:
            raise ValueError("result timestamp must be positive UTC epoch seconds")
        if item.scope not in ("REGULATION_ONLY", "FINAL_WITH_OT"):
            raise ValueError("unknown result scope")
        if type(item.actual_home) is not int or type(item.actual_away) is not int or min(item.actual_home, item.actual_away) < 0:
            raise ValueError("actual scores must be nonnegative integers")
        with self._connect() as db:
            cursor = db.execute(
                "INSERT OR IGNORE INTO outcomes VALUES (?, ?, ?, ?, ?, ?)",
                (item.league, item.fixture_id, item.result_ts_utc,
                 item.actual_home, item.actual_away, item.scope),
            )
            return cursor.rowcount == 1

    def audit(self, league: Optional[str] = None) -> dict:
        """Count paired, unpaired and invalid records before evaluation."""
        where = " WHERE league = ?" if league is not None else ""
        args = (league,) if league is not None else ()
        with self._connect() as db:
            predictions = db.execute(
                "SELECT league, fixture_id, prediction_ts_utc, scope FROM predictions" + where,
                args,
            ).fetchall()
            outcomes = db.execute(
                "SELECT league, fixture_id, result_ts_utc, scope FROM outcomes" + where,
                args,
            ).fetchall()
        pred = {(r[0], r[1]): r for r in predictions}
        obs = {(r[0], r[1]): r for r in outcomes}
        common = pred.keys() & obs.keys()
        invalid_time = sum(pred[k][2] >= obs[k][2] for k in common)
        invalid_scope = sum(pred[k][3] != obs[k][3] for k in common)
        return {
            "predictions": len(pred),
            "outcomes": len(obs),
            "matched": len(common),
            "unmatched_predictions": len(pred.keys() - obs.keys()),
            "unmatched_outcomes": len(obs.keys() - pred.keys()),
            "invalid_time_pairs": invalid_time,
            "scope_mismatch_pairs": invalid_scope,
            "eligible_pairs": sum(
                pred[k][2] < obs[k][2] and pred[k][3] == obs[k][3]
                for k in common
            ),
        }

    def audit_prematch(self, league: Optional[str] = None) -> dict:
        """Fail closed unless independently supplied fixture tipoff is recorded."""
        base = self.audit(league)
        where = " WHERE p.league = ?" if league is not None else ""
        args = (league,) if league is not None else ()
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS fixture_starts (
                league TEXT NOT NULL, fixture_id TEXT NOT NULL,
                start_ts_utc INTEGER NOT NULL,
                PRIMARY KEY (league, fixture_id)
            )""")
            rows = db.execute("""SELECT p.prediction_ts_utc, o.result_ts_utc,
                    p.scope, o.scope, f.start_ts_utc
                FROM predictions p JOIN outcomes o
                  ON p.league=o.league AND p.fixture_id=o.fixture_id
                LEFT JOIN fixture_starts f
                  ON p.league=f.league AND p.fixture_id=f.fixture_id""" + where, args).fetchall()
        base["missing_fixture_start"] = sum(r[4] is None for r in rows)
        base["valid_prematch_pairs"] = sum(
            start is not None and prediction < start < result and p_scope == o_scope
            for prediction, result, p_scope, o_scope, start in rows
        )
        return base

    def record_fixture_start(self, league: str, fixture_id: str, start_ts_utc: int) -> bool:
        """Insert-only fixture start; callers must verify schedule provenance."""
        self._identity(league, fixture_id)
        if type(start_ts_utc) is not int or start_ts_utc <= 0:
            raise ValueError("fixture start must be positive UTC epoch seconds")
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS fixture_starts (
                league TEXT NOT NULL, fixture_id TEXT NOT NULL,
                start_ts_utc INTEGER NOT NULL,
                PRIMARY KEY (league, fixture_id)
            )""")
            cursor = db.execute(
                "INSERT OR IGNORE INTO fixture_starts VALUES (?, ?, ?)",
                (league, fixture_id, start_ts_utc),
            )
            return cursor.rowcount == 1

    def record_fixture_provenance(
        self, league: str, fixture_id: str, provider: str,
        provider_fixture_id: str, start_ts_utc: int,
    ) -> bool:
        """Store immutable source identity and tipoff for a fixture."""
        self._identity(league, fixture_id)
        if not isinstance(provider, str) or not provider.strip():
            raise ValueError("provider is required")
        if not isinstance(provider_fixture_id, str) or not provider_fixture_id.strip():
            raise ValueError("provider fixture ID is required")
        if type(start_ts_utc) is not int or start_ts_utc <= 0:
            raise ValueError("fixture start must be positive UTC epoch seconds")
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS fixture_provenance (
                league TEXT NOT NULL, fixture_id TEXT NOT NULL,
                provider TEXT NOT NULL, provider_fixture_id TEXT NOT NULL,
                start_ts_utc INTEGER NOT NULL,
                PRIMARY KEY (league, fixture_id),
                UNIQUE (league, provider, provider_fixture_id)
            )""")
            cursor = db.execute(
                "INSERT OR IGNORE INTO fixture_provenance VALUES (?, ?, ?, ?, ?)",
                (league, fixture_id, provider.strip(), provider_fixture_id.strip(), start_ts_utc),
            )
            return cursor.rowcount == 1

    def audit_provenance(self, league: Optional[str] = None) -> dict:
        """Count eligible pregame pairs that also have provider identity."""
        base = self.audit_prematch(league)
        where = " WHERE p.league = ?" if league is not None else ""
        args = (league,) if league is not None else ()
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS fixture_provenance (
                league TEXT NOT NULL, fixture_id TEXT NOT NULL,
                provider TEXT NOT NULL, provider_fixture_id TEXT NOT NULL,
                start_ts_utc INTEGER NOT NULL,
                PRIMARY KEY (league, fixture_id),
                UNIQUE (league, provider, provider_fixture_id)
            )""")
            rows = db.execute("""SELECT p.prediction_ts_utc, o.result_ts_utc,
                    p.scope, o.scope, f.start_ts_utc, v.start_ts_utc,
                    v.provider, v.provider_fixture_id
                FROM predictions p JOIN outcomes o
                  ON p.league=o.league AND p.fixture_id=o.fixture_id
                LEFT JOIN fixture_starts f
                  ON p.league=f.league AND p.fixture_id=f.fixture_id
                LEFT JOIN fixture_provenance v
                  ON p.league=v.league AND p.fixture_id=v.fixture_id""" + where, args).fetchall()
        base["missing_provider_identity"] = sum(
            r[5] is None or not r[6] or not r[6].strip()
            or not r[7] or not r[7].strip() for r in rows
        )
        base["provider_start_conflicts"] = sum(
            r[4] is not None and r[5] is not None and r[4] != r[5] for r in rows
        )
        base["provider_consistent_prematch_pairs"] = sum(
            f is not None and v is not None and f == v
            and provider is not None and bool(provider.strip())
            and provider_id is not None and bool(provider_id.strip())
            and prediction < f < result and p_scope == o_scope
            for prediction, result, p_scope, o_scope, f, v, provider, provider_id in rows
        )
        return base

    def evaluate_provenance_verified(self, league: Optional[str] = None) -> BacktestMetrics:
        """Evaluate only matched fixtures with consistent recorded provider identity."""
        where = " WHERE p.league = ?" if league is not None else ""
        args = (league,) if league is not None else ()
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS fixture_starts (
                league TEXT NOT NULL, fixture_id TEXT NOT NULL,
                start_ts_utc INTEGER NOT NULL,
                PRIMARY KEY (league, fixture_id)
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS fixture_provenance (
                league TEXT NOT NULL, fixture_id TEXT NOT NULL,
                provider TEXT NOT NULL, provider_fixture_id TEXT NOT NULL,
                start_ts_utc INTEGER NOT NULL,
                PRIMARY KEY (league, fixture_id),
                UNIQUE (league, provider, provider_fixture_id)
            )""")
            rows = db.execute("""SELECT p.fixture_id, p.league, p.prediction_ts_utc,
                    o.result_ts_utc, p.expected_home, p.expected_away,
                    o.actual_home, o.actual_away, p.home_win_probability,
                    o.scope, p.scope, f.start_ts_utc
                FROM predictions p JOIN outcomes o
                  ON p.league=o.league AND p.fixture_id=o.fixture_id
                JOIN fixture_starts f
                  ON p.league=f.league AND p.fixture_id=f.fixture_id
                JOIN fixture_provenance v
                  ON p.league=v.league AND p.fixture_id=v.fixture_id
                 AND f.start_ts_utc=v.start_ts_utc
                 AND trim(v.provider) != ''
                 AND trim(v.provider_fixture_id) != ''""" + where, args).fetchall()
        valid = [
            HistoricalPrediction(*row)
            for row in rows
            if row[2] < row[11] < row[3] and row[9] == row[10]
        ]
        return evaluate_predictions(valid)

    def evaluate_prematch(self, league: Optional[str] = None) -> BacktestMetrics:
        """Evaluate only rows with an explicitly recorded valid tipoff."""
        where = " WHERE p.league = ?" if league is not None else ""
        args = (league,) if league is not None else ()
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS fixture_starts (
                league TEXT NOT NULL, fixture_id TEXT NOT NULL,
                start_ts_utc INTEGER NOT NULL,
                PRIMARY KEY (league, fixture_id)
            )""")
            rows = db.execute("""SELECT p.fixture_id, p.league, p.prediction_ts_utc,
                    o.result_ts_utc, p.expected_home, p.expected_away,
                    o.actual_home, o.actual_away, p.home_win_probability,
                    o.scope, p.scope, f.start_ts_utc
                FROM predictions p JOIN outcomes o
                  ON p.league=o.league AND p.fixture_id=o.fixture_id
                JOIN fixture_starts f
                  ON p.league=f.league AND p.fixture_id=f.fixture_id""" + where, args).fetchall()
        valid = [
            HistoricalPrediction(*row)
            for row in rows
            if row[2] < row[11] < row[3] and row[9] == row[10]
        ]
        return evaluate_predictions(valid)

    def evaluate(self, league: Optional[str] = None) -> BacktestMetrics:
        sql = """SELECT p.fixture_id, p.league, p.prediction_ts_utc,
                    o.result_ts_utc, p.expected_home, p.expected_away,
                    o.actual_home, o.actual_away, p.home_win_probability,
                    o.scope, p.scope
                 FROM predictions p JOIN outcomes o
                 ON p.league = o.league AND p.fixture_id = o.fixture_id"""
        args = ()
        if league is not None:
            sql += " WHERE p.league = ?"
            args = (league,)
        with self._connect() as db:
            rows = db.execute(sql, args).fetchall()
        return evaluate_predictions(HistoricalPrediction(*row) for row in rows)

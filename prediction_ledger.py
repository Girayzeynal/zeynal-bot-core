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

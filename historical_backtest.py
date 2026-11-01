"""Leakage-resistant evaluation of timestamped, completed basketball games.

Only evaluates supplied immutable predictions and observed results. It never fetches
or fabricates outcomes. Every prediction must precede its result timestamp.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import math
from statistics import fmean
from typing import Iterable, Optional


@dataclass(frozen=True)
class HistoricalPrediction:
    fixture_id: str
    league: str
    prediction_ts_utc: int
    result_ts_utc: int
    expected_home: float
    expected_away: float
    actual_home: int
    actual_away: int
    home_win_probability: Optional[float] = None
    # Regulation-only probabilities must not be scored against OT-inclusive results.
    result_scope: str = "FINAL_WITH_OT"
    prediction_scope: str = "FINAL_WITH_OT"
    fixture_start_ts_utc: Optional[int] = None


@dataclass(frozen=True)
class BacktestMetrics:
    n_games: int
    score_mae: float
    score_rmse: float
    total_mae: float
    total_rmse: float
    home_win_brier: Optional[float]
    home_win_log_loss: Optional[float]
    n_probability_games: int
    total_bias: float = 0.0
    home_score_bias: float = 0.0
    away_score_bias: float = 0.0


def _finite(value: float, name: str) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def evaluate_predictions(records: Iterable[HistoricalPrediction]) -> BacktestMetrics:
    rows = list(records)
    if not rows:
        raise ValueError("at least one completed game is required")
    keys = set()
    score_errors, total_errors, home_errors, away_errors, brier, log_loss = [], [], [], [], [], []
    for row in rows:
        key = (row.league, row.fixture_id)
        if not row.league.strip() or not row.fixture_id.strip() or key in keys:
            raise ValueError("fixture identifiers must be nonempty and unique per league")
        keys.add(key)
        if not isinstance(row.prediction_ts_utc, int) or not isinstance(row.result_ts_utc, int):
            raise ValueError("timestamps must be integer UTC epoch seconds")
        if row.fixture_start_ts_utc is not None:
            if isinstance(row.fixture_start_ts_utc, bool) or not isinstance(row.fixture_start_ts_utc, int):
                raise ValueError("fixture start must be integer UTC epoch seconds")
            if not row.prediction_ts_utc < row.fixture_start_ts_utc < row.result_ts_utc:
                raise ValueError("prematch prediction must precede fixture start, which must precede result")
        if row.prediction_ts_utc >= row.result_ts_utc:
            raise ValueError("prediction must precede the observed result")
        if row.prediction_scope != row.result_scope:
            raise ValueError("prediction/result scope mismatch: regulation vs overtime")
        h = _finite(row.expected_home, "expected_home")
        a = _finite(row.expected_away, "expected_away")
        if h < 0 or a < 0 or not isinstance(row.actual_home, int) or not isinstance(row.actual_away, int):
            raise ValueError("scores must be nonnegative and actual scores must be integers")
        if row.actual_home < 0 or row.actual_away < 0:
            raise ValueError("actual scores must be nonnegative")
        score_errors.extend([h - row.actual_home, a - row.actual_away])
        home_errors.append(h - row.actual_home)
        away_errors.append(a - row.actual_away)
        total_errors.append(h + a - row.actual_home - row.actual_away)
        if row.home_win_probability is not None:
            p = _finite(row.home_win_probability, "home_win_probability")
            if not 0 <= p <= 1:
                raise ValueError("home_win_probability must be within [0,1]")
            if row.actual_home == row.actual_away:
                raise ValueError("binary home-win scoring requires a decisive result")
            outcome = float(row.actual_home > row.actual_away)
            brier.append((p - outcome) ** 2)
            clipped = max(1e-15, min(1 - 1e-15, p))
            log_loss.append(-(outcome * math.log(clipped) + (1 - outcome) * math.log1p(-clipped)))
    return BacktestMetrics(
        n_games=len(rows),
        score_mae=fmean(abs(e) for e in score_errors),
        score_rmse=math.sqrt(fmean(e * e for e in score_errors)),
        total_mae=fmean(abs(e) for e in total_errors),
        total_rmse=math.sqrt(fmean(e * e for e in total_errors)),
        home_win_brier=fmean(brier) if brier else None,
        home_win_log_loss=fmean(log_loss) if log_loss else None,
        n_probability_games=len(brier),
        total_bias=fmean(total_errors),
        home_score_bias=fmean(home_errors),
        away_score_bias=fmean(away_errors),
    )

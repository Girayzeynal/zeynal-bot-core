"""Descriptive error intervals for already source-verified original predictions."""
from historical_backtest import evaluate_predictions
from backtest_uncertainty import bootstrap_mean_interval, moving_block_mean_interval


def describe_error_uncertainty(records):
    rows = list(records)
    if rows:
        evaluate_predictions(rows)
    if any(row.fixture_start_ts_utc is None for row in rows):
        raise ValueError("verified fixture start required")
    if len({(row.league, row.prediction_scope) for row in rows}) > 1:
        raise ValueError("one league and scoring scope required")
    rows.sort(key=lambda row: (row.fixture_start_ts_utc, row.fixture_id))
    # Resample whole games, keeping home/away errors paired. Never treat two
    # correlated team scores from a game as two independent observations.
    total_errors = [r.expected_home+r.expected_away-r.actual_home-r.actual_away for r in rows]
    per_game_score_mae = [(abs(r.expected_home-r.actual_home)+abs(r.expected_away-r.actual_away))/2
                          for r in rows]
    samples = dict(total_bias=total_errors, total_mae=[abs(e) for e in total_errors],
                   score_mae=per_game_score_mae)
    intervals = {name: dict(iid=bootstrap_mean_interval(values),
                           chronological_block=moving_block_mean_interval(values, block_size=5))
                 for name, values in samples.items()}
    return dict(status="descriptive_only" if len(rows) >= 2 else "insufficient_verified_sample",
                n_games=len(rows), resampling_unit="whole_game", chronological_order="fixture_start_utc_then_id",
                fixed_block_size=5, intervals=intervals,
                assumptions="iid assumes independent games; circular blocks preserve local ordering only",
                limitations="small samples and shared-team dependence can invalidate coverage; no calibration proof",
                calibration_status="NOT_ESTABLISHED")

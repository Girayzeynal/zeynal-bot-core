"""Offline bias-correction evaluation; never changes forecasts or claims calibration."""
from dataclasses import asdict, replace
from historical_backtest import evaluate_predictions


def evaluate_walk_forward(records, min_training_games=30):
    """Use only same-league/scope finals observed strictly before each prediction.

    Input provenance must already be replayed by the bound report. Corrections
    are research counterfactuals, not original forecasts or fitted deployment parameters.
    Training is expanding-window; a future result cannot alter an earlier fold.
    """
    if type(min_training_games) is not int or min_training_games < 1:
        raise ValueError("min_training_games must be a positive integer")
    rows = list(records)
    if rows:
        evaluate_predictions(rows)  # enforce duplicate, score, time and scope contracts
    if any(r.fixture_start_ts_utc is None for r in rows):
        raise ValueError("verified fixture start required")
    groups = {(r.league, r.prediction_scope) for r in rows}
    if len(groups) > 1:
        raise ValueError("walk-forward evaluation requires one league and scoring scope")
    rows.sort(key=lambda r: (r.prediction_ts_utc, r.fixture_id))
    original, corrected, folds = [], [], []
    for row in rows:
        training = [r for r in rows if r.result_ts_utc < row.prediction_ts_utc]
        if len(training) < min_training_games:
            continue
        train_metrics = evaluate_predictions(training)
        home = row.expected_home - train_metrics.home_score_bias
        away = row.expected_away - train_metrics.away_score_bias
        # Do not silently clip a correction that produces an invalid score.
        if home < 0 or away < 0:
            folds.append(dict(fixture_id=row.fixture_id, status="invalid_correction",
                              training_games=len(training)))
            continue
        original.append(row)
        corrected.append(replace(row, expected_home=home, expected_away=away))
        folds.append(dict(fixture_id=row.fixture_id, status="evaluated",
                          prediction_ts_utc=row.prediction_ts_utc,
                          training_games=len(training),
                          latest_training_result_ts_utc=max(r.result_ts_utc for r in training),
                          home_bias=train_metrics.home_score_bias,
                          away_bias=train_metrics.away_score_bias))
    invalid = sum(f["status"] == "invalid_correction" for f in folds)
    return dict(status="evaluated" if original else "insufficient_verified_history",
                method="expanding_window_team_score_bias", min_training_games=min_training_games,
                input_games=len(rows), evaluated_games=len(original),
                insufficient_training_games=len(rows) - len(folds), invalid_corrections=invalid,
                original_metrics=asdict(evaluate_predictions(original)) if original else None,
                corrected_metrics=asdict(evaluate_predictions(corrected)) if corrected else None,
                folds=folds, calibration_status="NOT_ESTABLISHED",
                usage="offline_research_only")

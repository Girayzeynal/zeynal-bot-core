# Calibration data flow and trust boundaries

This repository contains **two separate paths**, which must not be conflated.

1. `faz23_engine.Faz23Engine.record_snapshot` stores analysis snapshots, including repeat analyses of one fixture. `prematch_snapshots_for_calibration` selects the latest snapshot **before a caller-supplied verified UTC tipoff**. Snapshot identity is currently a string built from date, home, away and league; it is **not** a provider fixture ID.
2. `prediction_ledger.PredictionLedger` is the existing immutable, provider-provenance-aware prediction/outcome ledger. `verified_backtest_report.report` uses this ledger to evaluate ESPN-provenance-verified prediction/result pairs and provides the canonical verified backtest reporting path.

`calibration_metrics.evaluate_verified_totals` is an **offline exploratory utility**. Its `verified=True` result flag and `VERIFIED_BASELINE` label are assertions supplied by the caller, **not independent source verification**. Its MAE/RMSE/bias values must not be published as verified production accuracy without reconciling the fixture to a provider ID, verified UTC tipoff, final score, scoring scope (regulation vs overtime), and immutable prediction provenance through the canonical ledger.

## Integration gates still outstanding

- Verify the actual provider fixture ID and league/season mapping, rather than relying on team names.
- Validate source timestamps, actual final status, home/away orientation and scoring scope.
- The explicit NBA orchestrator now links original FAZ13 input copies and
  pre-tipoff projections to an ESPN fixture ID in one transaction, refusing
  posthoc input attachment. See `prediction-input-binding.md`. Prospective
  results and empirical calibration remain outstanding.
- Reconcile snapshot selection and ledger reports to avoid counting a fixture twice.
- Perform real-data walk-forward validation; publish sample size, coverage, error metrics and exclusions.
- Keep the PR draft and production unchanged until authenticated provider integration and CI are confirmed.

No authenticated historical result feed has been integrated by this document.

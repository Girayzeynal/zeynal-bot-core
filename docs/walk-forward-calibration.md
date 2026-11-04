# Chronological calibration research

Commit `7f57c46` passed both push CI (41884894819) and PR CI
(41884910495) before this module was added.

The strict bound report now includes an expanding-window bias-correction
experiment. Only records that already passed original-input and result-evidence
replay enter the experiment. EuroLeague also requires its original fixture
observation. NBA and EuroLeague reports remain separate.

For each prediction, training includes only results whose actual observation
timestamp is strictly earlier than the prediction timestamp. A past game with
a late-observed result cannot enter training early. The current game, equal-time
results, and future games cannot influence its correction. Input ordering does
not change the experiment.

The correction subtracts prior mean home and away score error from the original
team-score projections. It is an offline counterfactual; persisted forecasts,
production parameters, and ledgers are unchanged. Invalid negative corrected
scores are excluded explicitly rather than clipped. Original and corrected
metrics use exactly the same eligible evaluation games.

The default minimum training size is 30 games, a research configuration rather
than a guarantee of statistical adequacy. No available history means null
metrics, not zero error. Output always retains `NOT_ESTABLISHED` calibration
status. This experiment does not establish independent holdout performance,
probability calibration, interval coverage, or production readiness. Choosing
parameters after inspecting these results would require a separate untouched
holdout to assess them.

Seven synthetic tests cover known bias, late/equal-time observations, future
invariance, deterministic ordering, invalid corrections, empty samples, and
identity/scope/start/threshold contracts. These are algorithm tests, not measured
basketball accuracy. The real prospective EuroLeague ledger still has one
prediction and zero verified outcomes, so it cannot train or evaluate a fold.

Run the evidence-bound report with:

```sh
python -m verified_backtest_cli EXISTING_LEDGER --league EUROLEAGUE --require-bound-evidence
```

Authentic completed results and a sufficient prospective sample remain required.
No EuroCup profile or fabricated result was introduced.

Validation: all 489 local regression tests passed; compilation and diff checks
passed. Replayed the existing NBA/ESPN research ledger as well: one original
prediction, zero verified final outcomes, zero evaluation folds, null metrics.
This was an offline evidence replay, not a new ESPN network validation.
Exact NBA and EuroLeague report outputs are retained under `docs/evidence/` as
`nba-walk-forward-20261104.json` and `euroleague-walk-forward-20261104.json`.

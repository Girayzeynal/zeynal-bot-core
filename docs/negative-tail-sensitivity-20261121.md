# Negative-only P95 upper-tail sensitivity (2026-11-21)

## Intent / policy

The user explicitly requires **positive signed total-score deviations untouched**.
This module is a read-only gate on the already verified and hash-pinned original
quality report, not an automatic calibration or deployment. Positive cases are
counted but **their interval data is not read and no alternative values are
computed for them**. The original 54 snapshots and 46 settled outcomes remain
exactly as published.

Input: `PHASE92_READ_ONLY_QUALITY_REPORT_V1` envelope, with the native verified
`archive_audit.performance.forecasts` and `error_review.groups` from the same
report, exact fixture ID + snapshot SHA + fitted cohort. Reject score/sign
mismatches, source SHA mismatch, duplicate keys, invalid p50/p90/p95 order,
or missing native verified reports. Missing original negative intervals are
reported separately as `missing_negative_interval_count`, never fabricated.

## Scenarios

For **negative errors only**, compute three fixed, predeclared *boundary*
sensitivity cases:

```
hypothetical_P95 = original_P50 + factor * (original_P95 - original_P50)
factor in {1.00, 1.10, 1.20}
```

These are NOT actual Monte Carlo simulations, new score forecasts, quantile
recomputations, recommended sports betting lines, or calibrated intervals.
They only describe how the five originally observed upper-tail exceedances
would compare to *arbitrary one-sided wider numerical thresholds* in an
outcome-selected historical subgroup. No factor is optimized or declared best.

Interpretation limitations:
- Selection of negative cases uses the **observed final result**. That sign is
  not known before tipoff. Conditional exceedance percentages cannot validate
  P95 calibration for all games.
- The original quantile distributions and underlying score simulation paths
  are not represented by a simple widened endpoint. A genuine future shadow
  simulation requires original pregame inputs, an independently specified
  stochastic law, and forward validation.
- This analysis cannot show whether any change avoids harming the 21 positive
  originals; neither those original values nor alternatives are touched.
- No model, original forecasts, SQLite source data, Telegram, Fly deployment,
  calibration fit, or positive cases are changed.

## Device command (once PR branch is fetched; no checkout required)

```bash
cd ~/zeynal-hybrid-844
git fetch origin feature/negative-error-readonly-20261121
git show FETCH_HEAD:hybrid_engine/negative_tail_sensitivity.py |
  PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B - --report \
  "$HOME/zeynal-test-isolated/data/quality-phase924/reports/quality-4b2be633584586dd439fcfc3f6414001217ac4d9f8c60a9d8fc68c6e17a7a2f1.json"
```

This `git show | python` method does not merge/checkout any branch. The
module must be compatible with the already installed `core.team_identity`
digest routine. Output is printed, not written.

A future phase can implement a *genuine* shadow simulation under a separate,
specified predictor and score distribution, based solely on timestamp-eligible
features and with a protected positive-group regression check. This report
alone cannot infer those numerical adjustments.

## Regression

```bash
.venv/bin/python -B -m unittest tests.test_negative_tail_sensitivity -v
```

Synthetic fixtures test sign integrity, report pin, quantile order, explicit
missing-band abstention and no mutation. They are not real 2026/27 performance.
See issue #139 / PR #140 for user-supplied real-device counts and audit evidence.

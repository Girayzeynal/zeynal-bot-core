# Offline EuroLeague/EuroCup historical evidence audit

`euro_history_audit` replays supplied source-bound team input copies without
network access, ledger writes, profile creation or forecasting. It requires an
explicit league and season. Each record must match its source club, score,
orientation, exact start, season and replayed box-score pace evidence. Its
source observation must precede the original input capture time. Missing or
corrupt records fail the audit rather than disappear from the denominator.

Duplicate fixtures within a team, conflicting facts across team copies and
reused source UUIDs are rejected. Shared fixtures between opposing teams count
once in the descriptive pace distribution. Independent observation timestamps
may differ; they do not turn the same fixture into another game. The audit
preserves original input bytes and observation times.

```sh
python -m euro_history_audit \
  /workspace/scratch/eurocup-baseline-u2026-research/input-copies.json \
  --league EUROCUP --year 2026
```

The existing real U2026 research copies replayed successfully: KLA and TRN each
have six records, including one shared game, for **11 distinct fixtures**.
Deduplicated box-score estimated pace mean is 77.9673 possessions per 40 minutes;
sample standard deviation is 3.0947. These describe only these eleven selected
games. They are not a league-wide average, a measured possession count, a
calibrated EuroCup profile or out-of-sample predictive accuracy. The 0.44
free-throw coefficient remains an explicit assumption. No second provider or
independent possession count has verified this sample.

The exact report is retained in `evidence/eurocup-history-audit-20261104.json`.
It declares `coverage_scope: supplied_records_only`, zero profiles/forecasts
created and `calibration_status: NOT_ESTABLISHED`. Full season coverage,
independent reconciliation, prospective forecasts and empirical validation
remain outstanding. EuroCup analysis remains blocked by its missing profile.

Validation: 516 local regression tests passed, including eight new audit cases
using trimmed real fixtures and explicit corrupt/synthetic conflicts. Compilation
and diff checks passed. Prior commit `e64f0d7` passed push CI 41887230532 and
PR CI 41887243001. The real audit was offline; no new ESPN or Euroleague Live
HTTP validation, merge or production deployment was performed.

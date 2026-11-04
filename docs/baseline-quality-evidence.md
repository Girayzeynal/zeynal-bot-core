# FAZ13 quality requires replayable original inputs

Prior commit `335ed1c` passed push CI 41889597077 and PR CI 41889610811.

FAZ13 previously classified any baseline with nonempty source labels as
`VERIFIED_BASELINE`. An aggregate-only store, a missing/empty historical series,
or an aggregate that disagreed with its historical rows could therefore carry
the same label as a replayed input snapshot. That could pass the downstream
baseline-quality gate despite unavailable original inputs.

Quality now starts as `MANUAL_BASELINE` for manual data and otherwise
`UNVERIFIED_BASELINE`. Only successful capture and sealing of both teams'
original input rows upgrades it to `VERIFIED_BASELINE`. Exact record counts,
availability times, source-specific evidence where applicable and aggregate
reconciliation continue to be checked by the existing snapshot contract.
An unsuccessful capture keeps exploratory projections but cannot authorize a
strong FAZ22/FAZ23 decision. No default pace or score was added.

The label means the supported input-copy contract passed. It does not establish
independent-provider authenticity, empirical predictive calibration, or verified
final-result accuracy. Existing strict ledger reports still require original
fixture/result provenance and source-specific result evidence.

Regression tests cover aggregate-only stores, empty series, inconsistent
aggregates and downstream decision blocking. Existing actual-engine input-copy
cases explicitly assert that a valid snapshot retains the verified label.
No provider network requests or production integration are part of this change.

Validation: all 526 local regression tests passed, including the original-input
binding and EuroLeague evidence integration suites. Compilation and diff checks
passed. Empirical calibration and authentic completed prospective outcomes remain
outstanding; no merge, deployment or secret change occurred.

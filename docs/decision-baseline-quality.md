# Baseline quality at the FAZ13–FAZ22–FAZ23 boundary

Prior commit `09f9759` passed push CI 41888101498 and PR CI 41888110307.

FAZ22 now refuses strong decisions when `data_quality` is missing, manual,
unknown, or unverified. It preserves calculated projections for exploratory
inspection while setting a baseline-quality lock, empty signals and zero final
heuristic confidence. Live and force overrides cannot bypass this gate. FAZ23
checks baseline quality again, so changing it after FAZ22 approval cannot retain
strong signals.

FAZ13, FAZ22 and FAZ23 explicitly label confidence as
`HEURISTIC_SCORE_NOT_WIN_PROBABILITY` and calibration as `NOT_ESTABLISHED`.
The existing sample-size confidence heuristic and hand-set league thresholds
have not become calibrated success probabilities. A caller-supplied calibrated
label does not establish validation. Future empirical calibration needs a
separate versioned evidence contract.

`VERIFIED_BASELINE` is an upstream quality assertion, not a cryptographic source
signature or a substitute for replaying original evidence. This decision gate
blocks known unverified states; it cannot authenticate arbitrarily fabricated
core objects. The research ledger's strict original-input, fixture and result
bindings remain mandatory for verified accuracy reporting. Verified baseline
quality also does not imply that the model itself is empirically calibrated.

Regression cases cover manual/unknown quality with ordinary, live and force
paths, quality changes after upstream approval, and attempted calibration-label
promotion. Existing verified-baseline integration fixtures are explicitly labeled
so they continue to test FAZ22/FAZ23 threshold and risk behavior. No projection,
real outcome or measured accuracy was invented. Production deployment and merge
remain outside this change.

Validation: all 524 local regression tests passed, including three additional
integration tests with multiple malformed/manual/live/force cases. Compilation
and diff checks passed. No provider network request, prediction-ledger mutation,
merge or deployment was performed by this validation.

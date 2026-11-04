# FAZ27 real prospective outcome check

Initial remote head: 363547de9aee086a98e471fb3a826c689c55a5ae, independently
verified on draft/open/unmerged PR #12. Both unit-tests and docker-build passed
in push run 41920244841 and PR run 41920252729. No model/collector code correction
was justified by this check; only actual observation evidence is added.

## Actual observation: 2026-11-04 22:14:50 UTC

| ESPN ID | Home | Away | Registered start UTC | Source state | Final |
| --- | --- | --- | --- | --- | --- |
| 401909922 | Detroit Pistons (8) | Philadelphia 76ers (20) | 2026-11-05 00:00 | pre / Scheduled | unavailable |
| 401909923 | Washington Wizards (27) | Atlanta Hawks (1) | 2026-11-05 00:00 | pre / Scheduled | unavailable |

Both live summary requests returned HTTP 200. Source IDs, UTC starts and
home/away IDs agree with the prior retained observation and the existing
registered starts. Explicit source completed flags are false; final-score
parsers return no accepted result. No pregame zero score is counted as a final.
There was no observed provider access failure in this FAZ27 check. This does
not establish availability at future collection times or independent-provider
confirmation.

The existing bound-result collector returned awaiting_tipoff for each fixture.
It did not create any prediction or outcome and did not require a second
final-result fetch before tipoff. Pending games were not falsely labeled
complete, no hypothetical final was generated, and no clock was advanced for
these real observations.

## Immutable prediction and evaluation audit

The original ledger is
/workspace/scratch/faz25-history-poll/diagnostic-ledger.sqlite.
It retains two original predictions, two original-input copies and two FAZ24
three-stage bundles. Selected original prediction/input/stage SQL records before
and after the check are equal. Their digest also matches the FAZ26 evidence,
confirming no prediction regeneration, modification or backdating between checks.
SQLite integrity_check returned ok.

Verified completed games in this prospective cohort: **0**.
Original real prematch forecasts: **2**.
Verified scored forecast/result pairs: **0**.
No outcomes or outcome-evidence rows exist for this ledger. Strict FAZ24 reporting
replayed the original bindings and excluded both pending games from its sample.
MAE/RMSE, Brier, log-loss and probability-calibration values remain null, not zero.
This is not a claim of successful forecasting or sufficient statistical evidence.
FAZ22/23 retain FAZ13 score projections plus their own decisions; they do not
supply independent calibrated win probabilities.

## Missing evidence and production gates

Actual final results, matching verified result observations and sufficient
prospective examples remain required for measured accuracy. Original injury and
roster evidence is missing/unverified. Box-score pace estimates remain labeled
estimates. Appropriate archived probability outputs and matched scoring scope
are required before Brier/log-loss/calibration can be computed.

Continuous unattended reliability, independent-provider redundancy and external
backup disaster recovery remain unverified. FAZ26's original historical KeyError
incident still lacks enough retained diagnostics for a definitive root cause;
this status check supplies no new evidence about that incident.

Raw actual summaries are preserved locally under /workspace/scratch/faz27-check;
committed docs/evidence/faz27-real-check-20261104.json retains URLs, observation
times, source hashes, IDs/status, immutable-record checks and the strict report.
No production timer, merge, Fly.io/Telegram deployment, paid service, external
message or secret change is included.

Validation: all 576 local regression tests passed in 21.957 seconds. Negative
provider-failure cases intentionally log errors; the suite's final result is OK.
Diff checks passed. No local Docker build is asserted; the pushed commit's
unit-tests/docker-build jobs must be verified separately on GitHub.

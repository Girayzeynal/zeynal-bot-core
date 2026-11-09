# FAZ28 first actual prospective multilayer collection

A clean checkout of 2bbe3c39d7af2122542cb127fc6a044001553a4d was used. Its
unit-tests and docker-build jobs were independently verified successful in push
41929902120 and PR 41929907875. No model code change was needed for this run.

## Actual fixture and write

Selected actual ESPN fixture 401909925: Brooklyn Nets (17) home, Charlotte
Hornets (30) away. Explicit pregame schedule identity/start was validated from
UTC-date scoreboard queries and resolved again by the existing ESPN named-team
fixture resolver before generation/persistence. This is same-provider validation,
not an independent second-provider confirmation.

Registered tipoff: 1793838600 = 2026-11-05 00:30 UTC / 03:30 Europe/Istanbul.
Original generation, multilayer capture and atomic recording: 1793833437 =
2026-11-04 23:03:57 UTC / 2026-11-05 02:03:57 Europe/Istanbul, all before tipoff.
The ledger is /workspace/scratch/faz28-real-v1udwyw4/ledger.sqlite. It contains one
original prediction, one original-input copy and one immutable three-stage
bundle with the optional multilayer output; zero outcomes are present.

Fresh date-scoped ESPN regular-season history was fetched using the existing
verified-history adapter and replayable box-score evidence. Seven BKN and eight
CHA input records were used. All game starts, source observation timestamps and
input capture times preceded or met their strict permitted generation boundaries.
Latest source observation was 1793833435, two seconds before generation; latest
input game start was 1793665800 = 2026-11-03 03:30 Europe/Istanbul. Recent fetching
does not imply that injury/roster/market information was available.

## Stored outputs, not regenerated historical predictions

FAZ13 anchors: Brooklyn 107.10, Charlotte 105.76, total 212.86. The model-implied
home margin is +1.34 and fair home handicap -1.34, not a bookmaker line. Equal
expectation quarter allocation with explicit cent rounding gives:

| Period | Brooklyn | Charlotte | Total |
| --- | ---: | ---: | ---: |
| 1Q | 26.78 | 26.44 | 53.22 |
| 2Q | 26.78 | 26.44 | 53.22 |
| 3Q | 26.77 | 26.44 | 53.21 |
| 4Q | 26.77 | 26.44 | 53.21 |
| 1H | 53.56 | 52.88 | 106.44 |
| 2H | 53.54 | 52.88 | 106.42 |

10,000 stored Monte Carlo draws, seed 20261104, assumed score correlation 0.0:
normal-time home win 0.5229, away win 0.4574, tie 0.0197. Sample mean scores are
107.1642 and 105.6579 (total 212.8221); these are sampling estimates, not a
replacement of FAZ13's original anchor. P05/P25/P50/P75/P95 simulated totals:
181/200/213/226/244. No market line, over/under/push or eventual OT-inclusive
winner probability is present. FAZ22 and FAZ23 both return NO_STRONG_SIGNAL;
original heuristic confidence 67.5 and final heuristic confidence 55 are not
win probabilities.

## Audit results and limitations

Exact Decimal sums reconcile quarters, halves and both team totals. Simulation
period means reconcile to simulated team means within floating-point precision;
three regulation probability categories sum to one. The existing FAZ24 report
reopened and replayed the optional model binding/configuration from original
sealed inputs successfully. SQLite integrity_check returned ok. Read-only export
did not modify the new DB. Entire file SHA256 of the existing Detroit–Philadelphia
and Washington–Atlanta ledger remained unchanged; neither record was extended
or re-estimated.

These are actual pre-tipoff model outputs, not evidence of predictive accuracy.
Real scored FAZ28 samples remain zero; no MAE/RMSE/Brier/log-loss/calibration metric
is populated. Original anchors use FINAL_WITH_OT historical scores and the normal-
time simulation remains an explicitly unvalidated regulation proxy. Quarter
weights, Gaussian score distribution and correlation are uncalibrated model
assumptions. Injury/roster evidence, scoped market line, separately verified
regulation means and an empirical quarter model remain unavailable. Pace remains
a BOX_SCORE_ESTIMATE using 0.44 free-throw coefficient, not measured possessions.

Exact stored values, hashes, timestamps, configuration, missing-data flags and
audit booleans are retained in docs/evidence/faz28-first-real-prospective-20261104.json.
The ledger is isolated local research storage; no scheduled production service,
merge, Fly.io/Telegram deployment, paid API or secret change was used.

Regression validation: all 587 tests passed again in 24.941 seconds. Diff checks
passed. No synthetic fixture was counted as a real observation. Dedicated
unit-tests/docker-build CI jobs must be checked for the evidence commit as well.

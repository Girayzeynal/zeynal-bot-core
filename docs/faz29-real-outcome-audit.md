# FAZ29 actual outcomes and version-separated error audit

Starting source head 55c4e0f19f32350a4589bea62f2507123d4d934e was verified on
feature/nba-command-20261104 / draft PR #12. Push 41930972600 and PR 41930977900
both passed unit-tests and docker-build. No production integration was enabled.

## Actual final validation and recording

On 2026-11-05 actual ESPN summaries explicitly reported FINAL/post/completed=true
for 401909922 (DET 106, PHI 112), 401909923 (WSH 105, ATL 120) and 401909925
(BKN 114, CHA 104). Source IDs, UTC starts, home/away identities and final scores
were matched with the existing original-input-bound collector. Date scoreboard
20261104 independently fetched within ESPN agreed on all three identities and
scores. Each side's four period scores reconcile to the final; no overtime
appears. This is cross-route consistency within ESPN, not an independent provider.
The NBA official CDN request returned HTTP 403; no accepted official NBA payload
was available and no access-control bypass was attempted.

SQLite online backups were created before results were written. Existing
outcomes/outcome_evidence tables received the actual verified finals only.
A second ingestion accepted identical results without increasing row count,
changing first observation times or replacing result evidence. No predictions,
input copies or FAZ24 stage bundles were regenerated, modified or backdated.
Their selected-row digests before and after are equal. Whole database file hashes
naturally change when separate result tables receive new rows; that is not a
claim that an entire database remained byte-identical. Both integrity checks
returned ok. Backup files remain local research recovery copies.

## Audit implementation and scope

`prospective_error_audit.py LEDGER_A LEDGER_B` reads databases using mode=ro.
It validates stored input/result evidence and stage digest/context/chronology,
never calls the Monte Carlo generator, and computes errors from archived outputs.
Duplicate fixture IDs or canonical team-pair/start combinations across ledgers
are rejected, so backups cannot inflate sample size.

Period observations are an additive immutable result table, separate from all
forecasts. They retain a minimal source summary, true source observation and
local recording timestamps, final-result digest and replay hash. Periods must
sum to scores, counts must agree, any overtime must follow a tie, and status
period counts cannot contradict linescores. Repeated identical observations
preserve the first record; conflicting or backdated observations are refused.
The result-table UPDATE/DELETE triggers are local safeguards, not external
cryptographic attestation against a database owner.

HistoricalPrediction metrics are grouped by model family, exact archived source
SHA and scoring scope. FAZ13 anchors and FAZ28 Monte Carlo score expectations are
not pooled. FAZ22/23 carried the same score projections and all three games had
NO_STRONG_SIGNAL, so raw-score winner direction is not a record of recommended
bets or a separate FAZ22/23 score model. Signed error means prediction minus
actual; signed margin error uses (predicted home-away) minus (actual home-away).

| Fixture | Original FAZ13 | Final | Home error | Away error | Total abs error | Margin error |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| DET–PHI / 401909922 | 108.49–105.58 | 106–112 | +2.49 | -6.42 | 3.93 | +8.91 |
| WSH–ATL / 401909923 | 111.71–111.34 | 105–120 | +6.71 | -8.66 | 1.95 | +15.37 |
| BKN–CHA / 401909925 | 107.10–105.76 | 114–104 | -6.90 | +1.76 | 5.14 | -8.66 |

Original generation/recording times are unchanged: DET 1793827475, WSH 1793827477
(source 9bd8ab492680174accb18afc43dd0426b578ce32), BKN 1793833437 (source
2bbe3c39d7af2122542cb127fc6a044001553a4d). All precede their registered starts
1793836800, 1793836800 and 1793838600 respectively. Full values and original
preservation evidence are retained in docs/evidence/faz29-source-and-immutability-20261105.json.

## FAZ28 distribution and descriptive performance

BKN–CHA's archived Monte Carlo mean is 107.1642–105.6579 (total 212.8221),
separate from the retained FAZ13 anchor. Actual regulation score is independently
established from the four retained linescores: 114–104, total 218. Thus its
normal-time distribution can be inspected against the appropriate normal-time
outcome despite the model's still-unvalidated regulation-proxy assumption.
The actual total falls inside P05–P95 = [181,244], a central **90%** model range,
not a 95% confidence interval or evidence that coverage is calibrated.

| Model / source SHA prefix / scope | Games | Team score MAE | Team score RMSE | Total MAE | Total RMSE |
| --- | ---: | ---: | ---: | ---: | ---: |
| FAZ13 / 9bd8ab4 / FINAL_WITH_OT | 2 | 6.070 | 6.470 | 2.940 | 3.102 |
| FAZ13 / 2bbe3c3 / FINAL_WITH_OT | 1 | 4.330 | 5.035 | 5.140 | 5.140 |
| FAZ28_NORMAL_V1/MC / 2bbe3c3 / REGULATION_ONLY | 1 | 4.247 | 4.974 | 5.178 | 5.178 |

Team score MAE/RMSE average the home and away errors across games; total metrics
use one combined total error per game. There are **three unique real games and
three original forecasts**, not four independent examples: BKN appears in two
separate model-output cohorts. Binary probability metrics are not populated by
this score audit; FAZ28's archived three-way regulation probabilities are retained,
not converted into calibrated full-game win probabilities. No model is claimed
superior from one or two games. All calibration statuses remain NOT_ESTABLISHED.

## Missing data and causality limits

No verified pre-tipoff injuries, roster or market evidence was retained for these
forecasts. Pace was a box-score estimate using a 0.44 free-throw coefficient,
not a measured possession count. Stored input starts imply 47.5-hour gaps for
DET/PHI and WSH/ATL and 48-hour gaps for BKN/CHA. These are intervals from last
observed game **start** to next start, not verified rest duration, travel burden
or proof the schedule history was exhaustive. No fatigue adjustment is inferred.

Those absent features and the simple offense/defense averaging model limit
explanations. It is not established that injuries, missing players, pace, rest
or market absence caused any particular miss. In the two 9bd8ab4 cases, away
scores were underpredicted while home scores were overpredicted; their errors
partly cancelled in game totals. That is an observation, not a demonstrated
population bias. In the single BKN case equal quarter weights underpredicted
home Q4 by 7.23 points; one quarter is not evidence of a general fourth-quarter
coefficient. Its slight Monte Carlo-vs-anchor metric differences may reflect
sampling noise rather than a better model.

## Forward-only calibration and FAZ30 priorities

No model parameters or prior forecasts were adjusted from these results.
Existing walk-forward evaluation is invoked separately inside each model/version/
scope cohort; training requires result observation strictly earlier than the
new prediction. Period-based rows use local period-evidence recording time,
not a guessed final-buzzer time. None of these cohorts meets its configured
30-game training minimum (a research setting, not a statistical adequacy claim).
Regression coverage explicitly excludes equal-time and future observations.

1. Improve/evaluate team score and margin modeling separately from total error.
   The two old-source games had low total errors yet wrong raw-score winner
   directions. Compare a shrinkage opponent/pace/home-court model against the
   frozen average baseline, using only verified pre-tipoff features and forward
   holdouts; do not fit a correction from these two results alone.
2. Establish explicit regulation and period targets before learning quarter/half
   effects. The original mean is OT-inclusive, while FAZ28 is a regulation proxy
   with equal period weights. Retain replayable final/period observations like
   these and validate new period weights on unseen prospective games. Q4's single
   miss motivates investigation, not retrospective weight tuning.
3. Accumulate a versioned prospective probability sample, then fit/test variance,
   correlation and calibration on strictly earlier observations with a separate
   holdout. One P05–P95 hit is insufficient; evaluate proper three-way probability
   scores and empirical interval coverage. Keep injuries/rosters/rest missing
   until their time-stamped source evidence can be collected reliably.

Final result ingestion for these three games is now actual, not synthetic.
Independent official-source reconciliation, broad prospective coverage, provider
reliability, off-machine backup recovery and credible calibration remain release
gates. No merge, Fly.io/Telegram deployment, paid service or secret change occurred.

Validation: 596 local regression tests passed in 23.617 seconds. Nine new audit
cases cover exact signed/total/margin errors, actual trimmed period evidence,
nonfinal/corrupt/missing periods, future/equal-time leakage refusal, immutable
forecast preservation, model/scope separation, result idempotency, duplicate
ledger refusal, corruption detection, read-only audit and refusal to regenerate
Monte Carlo outputs. Compilation and diff checks passed. Source/result reads
and metrics have been replayed after the final code changes.

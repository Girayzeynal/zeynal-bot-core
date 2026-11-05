# FAZ30 forward-only model diagnostics

Starting head 011d27b5284573155998ca8442ded70316dcca2b was independently verified
on draft/unmerged PR #12. Both unit-tests/docker-build passed in push 41968484568
and PR 41968489755. FAZ29's three actual final pairs are the descriptive baseline.
No forecast model, production coefficient or original ledger/report was changed.

## Metrics and fair comparisons

model_evaluation.score_metrics reuses the existing validated HistoricalPrediction
evaluator and adds separate home, away and margin MAE/RMSE/bias. Total errors
remain separate; one combined total observation is not confused with two team
score observations. Mixed model/version/scope cohorts or duplicate games are
rejected. Metrics retain their sign convention prediction-minus-actual.

| Model / archived source | n | Home MAE/RMSE | Away MAE/RMSE | Total MAE/RMSE | Margin MAE/RMSE |
| --- | ---: | --- | --- | --- | --- |
| FAZ13 / 9bd8ab4 | 2 | 4.600 / 5.061 | 7.540 / 7.623 | 2.940 / 3.102 | 12.140 / 12.562 |
| FAZ13 / 2bbe3c3 | 1 | 6.900 / 6.900 | 1.760 / 1.760 | 5.140 / 5.140 | 8.660 / 8.660 |
| FAZ28 MC / 2bbe3c3 | 1 | 6.836 / 6.836 | 1.658 / 1.658 | 5.178 / 5.178 | 8.494 / 8.494 |

FAZ13 scope is FINAL_WITH_OT; FAZ28 scope is REGULATION_ONLY with its archived
UNVALIDATED_REGULATION_PROXY status. Three unique real games are represented,
not four independent model observations. Values are descriptive only; n=1/2
cannot establish stable bias, superiority or calibrated probabilities.

paired_compare intersects fixture IDs and verifies identical actual scores,
start, scope and prediction cutoff. Only that common set enters both metrics.
It reports unmatched and timing-mismatch games instead of generating the missing
version's forecast. For future shadow versions, archive each version in a separate
research ledger from a common pre-tipoff input cutoff; FAZ30 audits each ledger
individually and permits a game across different version cohorts while rejecting
same-cohort duplication. It never edits a frozen FAZ24 bundle.

Current real comparison results are NO_COMMON_GAMES for the two FAZ13 source
versions and INCOMPATIBLE_SCOPE for comparisons with FAZ28. BKN is shared but
scope differences are not silently normalized, even though its realized result
had no overtime. Positive paired-comparison behavior is tested with synthetic
same-game/same-cutoff forecasts; there is no actual paired-version benchmark yet.

## Data coverage and source-time period layer

faz30.input_coverage replays each original sealed snapshot. It reports raw
points-for/against counts, identified opponents, estimated versus measured pace,
source-observation coverage, original home/away flags and missing adjusted ratings.
Raw means are not labeled learned offense/defense strength or a home-advantage
coefficient. An opponent ID is not proof of an opponent-adjusted rating.

All three original snapshots used 7 home-team and 8 away-team game rows. Each
retained ESPN record contained replayable period evidence and source observation
time. Across the 45 team-game copies, a newly materialized export contains
**36 distinct historical games**, deduplicated by provider identity and canonical
team-pair/start conflicts. These are historical input observations, not 36 new
prospective forecasts or accuracy samples. Whole-season coverage is not claimed.

period_feature_layer records original source summary, source URL and digest,
parent input reference, source observation time, actual materialization time and
usable_after=max(source_observed,materialized). It stores four regulation periods,
any overtime periods, REGULATION_ONLY score and FINAL_WITH_OT score separately.
Scores/counts/ties must reconcile through the existing period-final parser.
Integrity and semantic replay reject rehashed field changes, unsupported schemas
and false source labels. These checks are not independent provider signatures;
upstream source authentication and original sealed-input validation remain required.

select_available requires usable_after strictly earlier than the requested
prediction timestamp; equal times are excluded. A newly extracted feature with
an old source timestamp cannot masquerade as an old live feature. Exporting
observations does not assert prediction availability. At all three original
prematch cutoffs, the new layer returns **zero** available records. No original
forecast was regenerated or reclassified. Prior-game periods can inform a later
match, never that same game's earlier prematch input.

This is a tested, immutable-hash JSON observation layer and design for collection,
not an installed historical downloader or production SQLite migration. A future
collector can reuse fixed ESPN summary routes, append observations to a separate
period store and preserve original hashes/timestamps. Suggested storage columns:
provider, provider_fixture_id, source_observed_utc, materialized_utc, payload_json,
payload_sha256, with immutable observations and explicit conflict handling.
Corrections need new auditable observations; do not overwrite old source facts.
No quarter data is inserted into the FAZ24 or FAZ29 databases by this task.

Missing/unsupported inputs remain explicit: possession-adjusted offense/defense,
opponent-strength normalization, fitted home advantage, verified injuries,
rosters, market data, measured possessions, travel and true recovery duration.
Raw home/away indicators and observed game-start gaps do not establish effects.
These missing features are model limitations, not proven causes of particular
misses. Source freshness is reported at the original prediction time, not
restamped as a new fetch.

## Variance, correlation and chronological evaluation

simulation_assumptions.variance_contract exposes the latent covariance and
predicted total/margin standard deviations implied by supplied marginal std,
correlation and shared pace variance. Impossible residual covariance is rejected;
shared variance is not double-counted. These analytical values describe the
continuous normal variables before rounding/clipping, not exact discrete score
variance or calibrated outcome uncertainty.

The sensitivity harness accepts explicit requests with at least 10,000 draws and
retains configuration/seed and observed covariance diagnostics. Synthetic tests
vary correlation -0.35/0/+0.35 and compare empirical versus latent behavior. No
real archived forecast is rerun for this report: it only reads BKN's stored input
std, observed simulation std/correlation and source configuration. This checks
simulator assumptions, not actual predictive variance calibration.

walk_forward_plan groups by model, version and scope and only exposes training
labels whose observation time strictly precedes the held prediction. Equal-time,
future and other-version results are excluded. It plans folds; it fits nothing
and never replaces an original forecast. Feature selection separately enforces
both source and materialization clocks. Current real folds have zero available
prior results and zero eligible folds under minimum_training=30. That minimum is
an operational research setting, not a statistical adequacy guarantee.

## Integrity, interpretation and next experiments

The real report was executed with MonteCarloEngine.simulate patched to raise if
called; it completed. Both entire SQLite file hashes and both committed FAZ29
evidence file hashes stayed identical before/after reporting. Existing code and
coefficients for FAZ13/22/23/24/28/29 were untouched. Exact preservation and new
diagnostic outputs are retained under docs/evidence/faz30-*.json.

The main observed weakness remains cancellation: old-source away underprediction
and home overprediction hid larger margin errors behind smaller total errors.
Test opponent/pace/home-advantage alternatives in future shadow cohorts, with
verified time-stamped injury/roster inputs when available. First establish
regulation/period targets and comparable cutoffs; then fit/validate quarter and
probability models on sufficient earlier observations and untouched holdouts.
Do not tune coefficients or infer feature causality from these three games.

Unresolved gates: enough comparable prospective versions, empirical period and
probability calibration, verified injury/roster/recovery/market feeds, independent
provider confirmation, operational reliability and external backup recovery.
The old unreproduced KeyError incident is not newly explained by FAZ30.
No production timer, merge, Fly.io/Telegram deployment or secret change occurred.

Local validation: all **609 tests passed** (25.983 seconds), including thirteen
new FAZ30 cases for separate metrics, aligned common-game cohorts, scope/cutoff/
identity conflicts, strict label availability, regulation/OT separation, newly
materialized-feature timing, corruption/schema rejection, missing raw source
coverage and reproducible 10,000-draw covariance sensitivity. Compilation and
diff checks passed. Local Docker success is not asserted; dedicated GitHub jobs
must validate the new commit.

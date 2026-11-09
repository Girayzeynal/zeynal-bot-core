# FAZ28 opt-in multilayer NBA projection

Architecture audit: FAZ13 seals actual historical inputs and score projections;
FAZ22/23 apply decision filters, not independent score estimators. FAZ24 stores
immutable atomic stage/input bundles. Existing Monte Carlo code provides seeded
correlated regulation-score draws and sampling diagnostics. These are reused.
Initial remote SHA 23833f21610fa7a309f481a8827885b50446077b was verified on draft
PR #12; both unit-tests/docker-build passed in runs 41923713348 and 41923724352.

## Output and model assumptions

`FAZ28_NORMAL_V1` retains the original FAZ13 home/away means without overwriting
any score. New team totals, four quarter expectations, first/second half totals
and model-implied home margin/fair home handicap use those anchors. Quarter
expectations initially have equal weights. A deterministic cent allocation
preserves each team total exactly; period/half/game sums reconcile. This is a
structural decomposition, not a fitted quarter or half model. Gamma(18,1)
allocation inside the existing simulator is also an explicit uncalibrated
scenario assumption, not measured period evidence.

Scenario scores follow a nonnegative rounded bivariate normal distribution.
Marginal standard deviations are sample standard deviations of pts_for from the
original sealed rows, not the old hard-coded core-average volatility. Default
score correlation is zero (an explicit independence assumption, not a measured
correlation). The default uses 10,000 draws, seed 20261104, with 10,000–100,000
allowed. Model ID, full source SHA, complete configuration, input digest and
capture time are retained. Missing/nonpositive variance leaves simulation and
probabilities unavailable rather than inventing volatility.

The simulator reports regulation home win, away win and tie probabilities,
which sum to one. It does not turn ties into an invented overtime winner.
Eventual full-game win probability remains null. Its mean estimate, quantiles,
sampling errors and probability diagnostics are retained separately from the
original score anchors. Scenario period means now retain numerical precision
instead of display-rounding each quarter, preserving their sum to team means.

**Scope limitation:** original FAZ13 means use FINAL_WITH_OT historical scores.
They are used as an explicitly unvalidated regulation proxy; independently
verified regulation-only means are absent. Output declares
UNVALIDATED_REGULATION_PROXY and NOT_ESTABLISHED calibration. Neither normal
probabilities nor period allocations are verified predictive accuracy. Sampling
intervals measure Monte Carlo noise, not model correctness. No parameter was
fitted to the outcomes being predicted.

A handicap output is the model-implied fair line, not an observed bookmaker
line or betting recommendation. Market handicap remains null. Total over/under/
push probabilities require a separately supplied positive market_total with
explicit REGULATION_ONLY scope; missing or OT-inclusive/unknown lines cannot
be silently substituted. Absent injuries, rosters, market, empirical period
model, verified regulation means and calibration are explicitly listed. Source
pace is labeled BOX_SCORE_ESTIMATE only when that evidence is present, otherwise
UNVERIFIED_SOURCE_PACE. No missing injury or player effect is imputed.

## Prospective integration and immutability

```
python -m faz24 collect NEW_LEDGER BASELINES YYYY-MM-DD HOME AWAY --model-version FULL_SHA --multilayer
python -m faz25 poll RESEARCH_LEDGER BASELINES --cycles 1 --multilayer
```

Flags are opt-in and off by default. No production timer is enabled. The bundle
retains a single shared multilayer output referenced by each stage digest,
without changing core scores or allowing FAZ22/23 to invent approved market
signals. New payloads replay deterministically from sealed inputs/configuration
before atomic persistence and during reporting. Capture time is bounded by
original generation and pre-tipoff recording; wall clock is rechecked after
simulation replay to reject a start crossed while validating.

Schema-v1 bundles without the optional extension remain valid. Existing rows
cannot be enriched after insertion; any changed retry fails. No migration,
update or backfill of old prediction payloads occurs. The CLI report exposes
new stored outputs under multilayer_predictions, separately from original-score
metrics. Its multilayer evaluation remains unavailable: verified regulation/
period outcomes and scope-compatible original probabilities are required before
new fields can be scored. FINAL_WITH_OT outcomes cannot validate the regulation
proxy. Unknown future model IDs are rejected instead of replayed with the
wrong implementation.

## Real versus synthetic evidence

Only synthetic new-model cases are evaluated here. Existing real ledger entries
401909922 and 401909923 were read via SQLite mode=ro; the entire database hash
was unchanged and original selected-row digest matches FAZ27. There are two
original forecasts and **zero FAZ28 records or scored real FAZ28 games** in that
ledger. Their missing half/quarter/probability fields remain missing. No output
was retroactively calculated into those records. Exact preservation evidence is
retained in docs/evidence/faz28-original-preservation-20261104.json.

Tests cover 10,000-draw repeatability, probability partitions, exact deterministic
quarter/half/team sums, simulated period sums, missing-data flags, invalid
configuration/scoping, no artificial zero-variance volatility, semantic tamper
rejection, atomic opt-in persistence, posthoc refusal, read-only reporting and
crossing tipoff during replay. Synthetic metrics do not count as prospective
basketball accuracy. Independent regulation/period histories, parameter fitting,
injuries/rosters, probability calibration, sufficient prospective observations
and operational/backup reliability remain production gates.

No merge, Fly.io/Telegram deployment, paid API, secret change or live background
scheduler was used. Local Docker socket access was previously denied; the final
commit's dedicated GitHub Docker job must establish build success.

Final local validation: all 587 regression tests passed (21.814 seconds),
including eleven new FAZ28 synthetic/integration cases. Compilation and diff
checks passed. Results are conditioned on the seeded Python implementation;
future replay must use a compatible runtime/model implementation. No empirical
probability calibration or real FAZ28 accuracy measurement was established.

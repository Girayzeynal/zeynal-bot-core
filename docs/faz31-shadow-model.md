# FAZ31 experimental shadow model

Initial SHA 8baea64bc2d8150ab24f12251ad07873ddea36fa was independently verified
on draft/unmerged PR #12. Both unit-tests/docker-build passed in push 41970953023
and PR 41970957886. FAZ13 and FAZ28 source files, coefficients and original
FAZ24/FAZ29 records are unchanged. FAZ24 only receives an optional atomic bundle
extension; all existing calls remain opt-out by default.

## Real readiness result

| Item | Actual evidence |
| --- | --- |
| Original prospective reference forecasts | 3 |
| Historical period observations retained by FAZ30 | 36 distinct games |
| Original time-stamped FAZ31 feature/label examples | 0 |
| Real shadow models trained | 0 |
| Actual numeric reference/shadow comparison pairs | 0 |
| Real shadow score/probability metrics | unavailable |
| Calibration / promotion | NOT_ESTABLISHED / disabled |

The three actual final scores remain the baseline audit set. They cannot become
100 training examples, and newly computed FAZ31 features cannot be assigned their
old prematch timestamps. Period observations are historical source material,
not archived original prematch feature vectors. Real training is therefore
NOT_TRAINED. No weights were fitted to those games and no numeric shadow
forecast was backfilled. Common-game real superiority cannot be assessed.

## Source-timed experimental features

shadow_features makes regulation-form features from the already replayable
period observation layer. Both source observation and materialization times
must precede the shared prediction cutoff. Features retain exact source records,
record hashes, target source fixture/team IDs, cutoff, creation and availability
times; replay checks the math and rejects rehashed changes. Public creation
requires an actual pre-tipoff shared-cutoff capture, not a historical timestamp.
No global clock patching occurs in production replay code.

The twelve features comprise home/away points per estimated 100 possessions,
defensive points allowed, sample opponent offense/defense form, estimated pace,
and each team's observed home-minus-away offensive form. The latter is a noisy
association, not a causal home-advantage estimate. Opponent form is not an official
league-wide rating. Box-score pace retains its 0.44 free-throw assumption, and
OT-inclusive pace is only a proxy for regulation pace. Selection-biased/small
history remains an explicit risk.

Each target side requires at least five own source games, at least two home and
two away appearances, and two or more observed games for each opponent used in
its form summary. Missing coverage produces UNAVAILABLE; no mean, injury effect
or home coefficient is invented. Injuries, rosters, market and true recovery
remain optional-unavailable markers, not verified healthy-player assumptions.
The source/feature digests are integrity checks, not provider signatures;
training callers must use audited exports, not fabricated source-shaped JSON.

## Ridge score and unequal-quarter heads

FAZ31_RIDGE_V1 standardizes features using training data only and fits penalized
linear heads for regulation total and margin, plus eight quarter-score shares.
The intercept is unpenalized. Candidate penalties 1/10/100 are selected only on
validation score-MAE plus half margin-MAE. Total and margin imply consistent team
scores; bounded clipping prevents negative predictions. Separate learned quarter
shares are nonnegative-normalized and allocated in cents to the team total.
Zero learned share mass means unavailable periods, never an equal-weight fallback.
This is independent of FAZ28's frozen equal-quarter rule.

The operational minimum is 100 original feature/label pairs with at least
60 train / 20 validation / 20 test cases after time purging. Counts are not proof
of statistical adequacy or league diversity. Source identities and quarter
labels must reconcile; features must have existed by their original pregame
cutoffs. Label observations must be after start and actually observed before
training. Duplicate fixtures are rejected.

Splits are chronological; training labels not observed before the first
validation prediction and validation labels not observed before the first test
prediction are purged. Same-time boundaries cannot leak between partitions.
Preprocessing/coefficients use training only; penalty selection and residual
variance use validation only. Test labels do not select parameters. Expanding
walk-forward evaluation grows training with fixed validation/test windows and
disjoint twenty-game test blocks. These are offline holdouts, not real live
performance. Models trained today cannot be applied as original historical
forecasts: artifact training/availability times must precede a new cutoff.

## Probability and calibration reporting

A discretized normal margin head uses validation-margin residual standard
deviation with half-point boundaries to produce home/away/tie probabilities for
REGULATION_ONLY. Zero variance leaves probabilities unavailable. No overtime
winner conversion is made. Three-way Brier sum, log-loss and home-event ten-bin
ECE are reported separately from score/total/margin errors, with sample counts.
They remain descriptive and NOT_ESTABLISHED calibration. Validation diagnostics
used during development are not an independent final calibration assessment.
Neither small held-out sets nor a correct individual winner establish superiority.

## Simultaneous prospective storage and comparisons

```
python -m faz31 inspect PERIOD_EXPORT LEDGER_A LEDGER_B
python -m faz31 train AUDITED_EXAMPLES_JSON NEW_ARTIFACT_JSON
python -m faz24 collect NEW_RESEARCH_LEDGER BASELINES YYYY-MM-DD HOME AWAY \
  --model-version FULL_CLEAN_SOURCE_SHA --multilayer \
  --shadow-periods PERIOD_EXPORT [--shadow-model TRAINED_ARTIFACT_JSON]
```

Training artifact output refuses overwrite. Inspect is read-only and exports
only originally archived READY shadow-feature pairs with verified period labels;
legacy references are not upgraded retrospectively. Explicit training requires a
clean checkout and records its exact source SHA, selected penalty, scalers,
coefficients, split IDs, dataset digest, training/availability times, score and
probability holdout diagnostics. No production model file is replaced.

Optional FAZ24 shadow packets share the original reference input hash, fixture,
source version, prediction cutoff and FAZ28 reference digest. They store the
feature envelope/model artifact plus numeric shadow output or an explicit
ABSTAIN status. If same-cutoff feature capture is missed, prediction is refused.
No model artifact means ABSTAIN_NOT_TRAINED when feature coverage is ready; other
coverage/timing failures remain separate. An abstention is not a shadow forecast.

The packet is inserted with reference FAZ13/22/23, original inputs and optional
FAZ28 in the existing single transaction, guarded by the actual pre-tipoff clock.
Failure rolls back the reference too. An existing reference cannot receive a
shadow after the fact. No old bundles are migrated. Stored numeric comparisons
require verified regulation results and same-game/same-cutoff/same-scope outputs;
Brier/log-loss/ECE remain separate. Reference FINAL_WITH_OT scores are not silently
compared with regulation shadow predictions. The comparison uses the FAZ28 normal
proxy as the scoped reference and retains that reference's own scope limitation.

Only synthetic cases have exercised successful training and numeric shadow
prediction. Current real data are insufficient, so real simultaneous numeric
shadow/reference records and real walk-forward metrics remain unverified.
There is no automatic promotion, timer installation, production handler hook,
merge, Fly.io/Telegram deployment, paid API or secret change.

## Integrity and open gates

Read-only inspection left both SQLite file hashes and FAZ29/FAZ30 evidence file
hashes unchanged. New readiness/preservation artifacts are under docs/evidence.
The old three-game descriptive reference metrics remain unchanged. Outstanding:
source-authenticated feature/label accumulation, broad matchup/league coverage,
verified injuries/rosters/recovery, real timed shadow collection, enough unseen
holdouts, probability calibration, independent source availability and operational
backup/restore monitoring. The unreproduced historical KeyError is not explained
by this new experimental model.

Local validation: all **622 regression tests passed** in 25.163 seconds,
including thirteen new FAZ31 cases. Positive ridge/quarter/probability training
and walk-forward behavior use only explicitly synthetic 100/120-example data.
Tests cover insufficient data, semantic feature tampering, late-label purging,
test-label independence of fitted coefficients, pre-artifact cutoff refusal,
learned unequal-quarter reconciliation, three-way probability scoring,
disjoint walk-forward test windows, same-cutoff bindings, atomic abstention,
rollback and posthoc refusal. Compilation and diff checks passed. Local Docker
success is not claimed; dedicated GitHub jobs must validate this commit.

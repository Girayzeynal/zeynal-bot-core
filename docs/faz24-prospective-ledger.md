# FAZ24 prospective NBA stage ledger

Initial remote head: `34b36f7489108d47c060b77c565b335079853c5d`.
Both unit-tests and docker-build passed in push 41911666688 and PR 41911680710.
PR #12 remains draft against fix/faz22-force-guard-20261104.

## Existing infrastructure retained

FAZ24 reuses FAZ13 input sealing, ESPN fixture resolution, atomic prediction
bridge, PredictionLedger, ESPN bound-result collection, strict bound evaluation,
walk-forward bias experiment and whole-game error uncertainty. No production
handler or scheduler was replaced or enabled.

## Opt-in collection

```
python -m faz24 collect NEW_RESEARCH_LEDGER BASELINE_DIRECTORY YYYY-MM-DD HOME AWAY --model-version FULL_CHECKED_OUT_SHA
python -m providers.espn_bound_results RESEARCH_LEDGER ESPN_FIXTURE_ID
python -m faz24 report RESEARCH_LEDGER
```

The date uses the existing explicit Istanbul-calendar fixture resolver; stored
times are UTC epoch seconds. Collection resolves the unplayed fixture before
running engines and resolves it again before persistence. After acquiring the
SQLite write lock, actual recording time must still precede tipoff. Old generation
timestamps cannot authorize historical insertion. A CLI collection requires the
supplied source SHA to match a clean checked-out commit.

The three outputs are deep-copied at each stage. Each includes its context,
projection, decisions, metadata, bands and notes. The bundle also retains the
source commit, generation/capture/recording times, fixture start, exact source
fixture identity through canonical provenance, original-input digest, historical
input source/game IDs, latest historical start and source observation, and
explicit missing observation/injury/roster/probability statuses.

A single BEGIN IMMEDIATE transaction inserts stages, canonical prediction,
provenance and original inputs. Any failure rolls back all. Exact retries are
idempotent; a fresh changed run cannot replace the original. Existing older
predictions cannot receive stages after the fact. A home/away/start uniqueness
constraint prevents alias fixture IDs from inflating a team's fixture sample.
The retained ESPN resolver and exact input team bindings prevent name guessing.
SQL triggers reject stage UPDATE/DELETE. Hashes and semantic binding checks
support audit/replay; a database owner able to drop triggers and rewrite hashes
can still tamper, so this is not external cryptographic attestation.

## Evaluation boundaries

Verified completed results are linked using the existing ESPN collector and its
replayable result evidence. FAZ24 report filters a temporary database copy to
FAZ24 fixtures only; existing non-FAZ24 forecasts cannot inflate prospective
coverage. The original database is not edited by reporting. Source-result and
original-input gates remain mandatory.

FAZ22 and FAZ23 currently filter/annotate FAZ13 scores, rather than producing
independent new score projections. Stage output reports make shared-score
semantics explicit; they do not claim three independent forecast models.
MAE/RMSE become descriptive metrics only for verified completed pairs. No
calibrated original win probability is produced by this pipeline, so Brier,
log-loss and probability calibration remain null. Heuristic confidence must not
be scored as a probability. Validating a future probability-output contract and
archiving those probabilities before tipoff is required before those metrics
can be populated.

The historical walk-forward research result is separate from prospective
metrics. It is the existing expanding-window bias experiment with strictly
prior observed results, not fabricated historical model predictions. No authentic
historical pre-tipoff snapshots are created by this change. Small samples never
automatically establish calibration; status remains NOT_ESTABLISHED.

No background process, cron job, paid API, secret change, merge or production
deployment is installed. An external opt-in scheduler may invoke collection;
continuous operational collection and sufficient authentic completed prospective
samples remain requirements for measuring real accuracy.

Local validation: 551 regression tests passed in 20.199 seconds. Ten added
synthetic FAZ24 cases cover automatic stage collection, atomic rollback,
pre-tipoff wall-clock enforcement, original-input/stage consistency, idempotency,
posthoc refusal, update/delete triggers, corruption and read-only reporting.
Compilation and diff checks passed. A local Docker daemon probe failed with
permission denied on /var/run/docker.sock; Docker build must be validated by
GitHub's dedicated docker-build job, not claimed as a successful local build.

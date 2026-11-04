# Immutable prediction input binding

FAZ13 now captures the individual records underlying each loaded team aggregate
while generating its output. Before marking the input snapshot `CAPTURED`, it
checks sample counts, exact timestamps, unique source/game identities, source
pace observations and numerical agreement between the records and the aggregate
actually used. It then seals the two input copies with fixture context,
prediction time, expected scores, scoring scope and a canonical JSON SHA-256.

Schema version 1 replays the current FAZ13 score formula: expected home is the
mean of home points-for and away points-against; expected away is the reverse.
Each stored expected score must match within the existing 0.011 rounding
tolerance. This reproduces the score projection, not every downstream confidence
or display heuristic. A digest detects alteration; it is not source attestation.

Outputs lacking auditable records remain exploratory and show
`input_snapshot_status: UNAVAILABLE`. The canonical NBA orchestrator requires
the original snapshot and never reconstructs it from current baseline files.
All existing source, sample, numerical, fixture and pre-tipoff checks still
apply. Input capture times must be at or before prediction generation, and any
estimated-pace observation must be strictly earlier than the capture time.

`prediction_inputs` is an additive SQLite table keyed by league and fixture ID.
The bridge uses a single `BEGIN IMMEDIATE` transaction for input snapshots,
predictions, fixture starts and provider identity. A failure rolls all records
back. Repeated identical submissions are idempotent. Different input games are
rejected even if they produce identical means. An existing prediction without
inputs cannot have evidence attached later.

`PredictionLedger.load_prediction_inputs` replays the stored copy against the
immutable prediction values without baseline files. `audit_prediction_inputs`
reports bound, missing, invalid and orphaned snapshots. The existing verified
backtest report now includes this separate audit; its legacy metrics continue
to mean provider-identity/timing verification, not automatic proof of original
model inputs. Generic ledger callers may still store legacy unbound predictions;
those are explicitly counted as missing rather than silently upgraded.

## Validation

- Previous commit `7642564`: GitHub run 41867420411 completed successfully.
- Full local suite: **395 passing tests**. Eleven new synthetic offline integration
  tests exercise actual FAZ13 generation, SQLite reopen, deleted baseline files,
  aggregate mismatch, changed inputs/hashes, late captures, equal-mean input
  replacement, posthoc binding refusal, atomic rollback and corruption detection.
  A longer rolling history does not expand the trailing window used by the
  loaded aggregate; only its numerically reconciled input sample is captured.
  Existing orchestrator fixtures were updated to supply original snapshots.
- Compilation and `git diff --check` pass.

## Live prospective research check

Only read-only ESPN calls and an isolated local directory were used. No remote
application, production baseline, Telegram message or production ledger changed.

ESPN fixture `401909924` (BOS home / MIL away) had verified scheduled tipoff
`2026-11-05T00:30:00+00:00`. Both teams supplied seven historical regular-season
games. Each summary matched scoreboard identity, score and period evidence;
pace remained explicitly a box-score estimate. The real FAZ13 projection was
generated **before tipoff**, at `2026-11-04T16:39:48+00:00`, and persisted with
its input snapshot in a local research ledger. The input binding audit found
one bound prediction, zero missing/invalid/orphaned snapshots. Both baseline
files and series files were then deleted; the original inputs still replayed
from SQLite without fetching replacements.

The retained summary is `evidence/prospective-input-binding-20261104.json`.
It contains the original local ledger path and snapshot digest. The check script
is retained at `/workspace/scratch/verify_prospective_inputs.py` in this workspace.
No result was invented or recorded: **zero outcomes, calibration not evaluated**.
The forecast has no validated accuracy claim and is not a production promotion.

## Remaining gates

Source authentication still relies on the trusted adapter endpoint and caller;
timestamps/digests are local assertions, not third-party signatures. This work
does not establish independent possession accuracy. The prospective research
record needs an authentic completed result with matching fixture ID, timing and
scoring scope before it may enter evaluation. One evaluated match would still
be insufficient to establish calibration. Multi-league provider integration and
empirical model calibration remain open.

# Original EuroLeague fixture and prediction binding

Previous commit `7a9cd99`: CI run 41878239870 completed successfully after its
initial queued state. No queued run was substituted for a successful result.

## Contract

`persist_resolved_euroleague_prematch` is an explicit research entry point. It
requires an original FAZ13 input snapshot, matching team averages, six or more
source-bound observations per team, consistent source/key/sample metadata and
an exact source club-code context. It does not reconstruct inputs from current
baseline files or guess team-name aliases.

Persistence performs a fresh official season-catalog read, then a matching
individual fixture request. The short baseline cache is deliberately not used
to certify a new prediction. Existing HTTP 429 cooldowns still apply; there is
no stale-data fallback or alternate endpoint/identity bypass.

The chosen fixture must be uniquely identified by season, home/away club codes
and its date in Europe/Istanbul. It must be regular season, explicitly unplayed,
confirmed in UTC and future-dated at observation time. Scores and all reported
periods must be zero. Catalog/detail disagreements, a different input season or
provider, ambiguous matches and inconsistent score projections reject the write.

Each fixture observation retains source identity/UUID, original source fields,
UTC start and observation time, source URL and a canonical JSON digest. Its
observation time must be at or after original prediction generation and before
tipoff. Stale observations cannot certify a newer prediction. A local timestamp
and digest are not independent provider attestation.

The projection bridge now supports exactly two explicit paths: existing ESPN
records and EuroLeague `EUROLEAGUE_LIVE` records with mandatory original input
and fixture evidence. EuroCup is not admitted by this new path. It is not
assigned an invented profile or mislabeled as ESPN.

`fixture_observations` is an additive ledger table. A single transaction writes
prediction, original inputs, fixture observation, provider identity and tipoff.
The actual clock is checked again inside the transaction; a delayed lock cannot
permit a new post-tipoff insertion. Existing predictions cannot receive fixture
proof posthoc. Later identical observations preserve the first stored time and
digest. Changed/backdated observations are rejected rather than overwritten.

`load_fixture_observation` replays the archived observation against the immutable
prediction, provider metadata and original inputs. A past pre-tipoff observation
remains replayable after the match starts, without current baseline files or
network access. This is different from inserting a new historical prediction,
which is refused.

## Regression validation

Full local suite: **467 passing tests**, including eighteen new offline synthetic
EuroLeague cases using the real FAZ13 and SQLite code. Coverage includes source
and season isolation, metadata/score tampering, date/team mismatches, catalog
ambiguity, unavailable sources, idempotency, stale observations, posthoc binding,
post-tipoff guards, atomic rollback, corruption and restart/pruning replay.
Compilation and `git diff --check` passed.

All network responses and future fixtures in those unit tests are synthetic or
mocked. Their successful tests are not reported as real prediction performance.
Existing NBA report/evaluator gates remain separate; the NBA strict evaluator
does not silently evaluate EuroLeague rows.

## Actual prospective research check

After the previous HTTP 429 observation, a later bounded probe returned HTTP 200.
The probe is retained in `evidence/euroleague-prematch-access-probe-20261104.json`;
it establishes response availability only. The subsequent complete research
check is separately retained in
`evidence/euroleague-prospective-binding-20261104.json`.

- Actual source fixture: `E2026_100`, OLY home / RED away, UUID
  `840cb0f0-660c-413a-b127-99aa52046d4d`.
- Verified scheduled UTC start: `2026-11-06T19:15:00+00:00`.
- Original FAZ13 generation: `2026-11-04T17:49:16+00:00`, before tipoff.
- Six captured historical inputs per team. Existing real RED observations were
  compared with the fresh catalog and reused with their original timestamps;
  the opponent's source batch was fetched and reconciled. No history was
  backdated or silently restamped.
- The actual FAZ13 -> FAZ22 -> FAZ23 chain ran in a new isolated research
  directory. It returned `NO_STRONG_SIGNAL` with an empty signal list.
- One provider-correct projection, its input copy and its fresh fixture
  observation were saved atomically and successfully reopened from SQLite.
- **Zero outcomes** were recorded. Calibration status remains `NOT_EVALUATED`;
  there is no claim of predictive accuracy or production readiness.

The local ledger and analysis snapshot files are retained under
`/workspace/scratch/euroleague-prospective-elskbakv/`. The check script is
`/workspace/scratch/verify_euroleague_prospective.py` and made only read-only
remote calls and isolated local writes. Previous incomplete ZAL verification
artifacts were not rewritten or promoted to successful status.

## Remaining gates

EuroLeague completed-result evidence binding and its explicit strict evaluator
are now implemented and tested; see `euroleague-result-evaluation.md`. A real
completed result has not been collected for this future fixture, and the live
check still reports a pending result. Independent source/possession validation, empirical model
calibration and the missing EuroCup profile remain open. Production bootstrap,
Telegram entry points and deployment settings were not enabled or changed.
No merge, deployment, paid service or secret change occurred.

# Bound final-result collection and evaluation

Previous commit `6038c05`: GitHub CI run 41870152471 completed successfully.

## Collection contract

`providers.espn_bound_results` only processes an existing NBA prediction with a
valid original input snapshot, ESPN fixture identity, matching tipoff and
`FINAL_WITH_OT` scope. It never creates predictions or infers missing outcomes.

Before tipoff it returns `awaiting_tipoff` without requesting a result. After
tipoff it fetches the fixed ESPN summary endpoint for the registered numeric
provider fixture ID. Event ID, exact start time, final status, decisive integer
scores and independently resolved home/away team IDs must agree. Unfinished
responses return `awaiting_final`; malformed or contradictory finals return an
error status rather than being reported as successful pending work.

An accepted observation stores the source fields needed to replay the final
score, actual local observation time, source URL, resolved team IDs and the
original prediction input digest. The result and observation are inserted in
one SQLite transaction. Storage failure rolls both back.

An identical repeated fetch is accepted idempotently and preserves the first
observation time. Conflicting scores, changed evidence and backdating are
rejected. An outcome written through the legacy API cannot receive evidence
posthoc. `accepted` means the verified record exists; it does not necessarily
mean a new row was inserted on that invocation.

The digest detects corruption; it is not a provider signature. Team resolution
and source authenticity still depend on the trusted adapter. The result time
records observation of the completed result, not an invented final-buzzer time.
No independent second-provider reconciliation is claimed.

## Commands

For the existing **local research ledger** only:

```sh
python -m providers.espn_bound_results \
  /workspace/scratch/zeynal-prospective-sy39s8y2/research-ledger.sqlite 401909924

python -m verified_backtest_cli \
  /workspace/scratch/zeynal-prospective-sy39s8y2/research-ledger.sqlite \
  --require-bound-evidence
```

Collection may write an authenticated completed outcome to the selected local
ledger and perform additive schema setup. This validation used only the isolated
research path above. No scheduling, messaging, deployment or paid service was
used. The reporting CLI evaluates a backup and leaves its source unchanged.

## Strict report

`--require-bound-evidence` evaluates only records with both replayable original
inputs and matching final-score observations. Missing/corrupt evidence, scope
conflicts and results still pending are counted separately. Counts reconcile
to all predictions; absent results yield `sample_size: 0` and `metrics: null`.
A small evaluated sample is labeled explicitly; evaluation does not establish
calibration. Legacy provider-identity reports remain available without this
flag and do not establish the stronger input-and-result evidence claim.

## Validation and real-data limits

- Full local suite: **409 passing tests**, including fourteen new synthetic
  tests for accepted finals, pending games, identity/start/team conflicts,
  missing inputs, idempotency, conflicts, atomic rollback, posthoc attachment,
  corrupted data, backdating, scope mismatch and read-only reporting.
- Compilation and `git diff --check` passed.
- Actual prospective BOS–MIL fixture `401909924` returned `awaiting_tipoff`.
  The local research ledger retained **zero outcomes and zero result
  observations**. The strict report returned `no_bound_results`, sample size
  zero and no error metrics. Evidence is retained in
  `evidence/bound-result-check-20261104.json` and
  `evidence/bound-result-report-20261104.json`.
- The real final-result path has **not yet been validated on this future
  fixture**. Only synthetic final-result tests passed; this is not completed
  real-data calibration. The next data-dependent step is collecting its
  authentic final and growing a prospective evaluation sample.

Independent possession validation, empirical calibration and non-NBA source
integration remain outstanding. No merge or production deployment occurred.

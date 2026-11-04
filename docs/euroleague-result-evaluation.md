# Source-bound EuroLeague results and evaluation

Previous commit `a4f06c5`: push CI 41882403605 and PR CI 41882017221 both
completed successfully. The initial PR-only lookup did not establish that
result; the complete commit-filtered run list was subsequently checked.

## Final-result gates

`providers.euroleague_results` only processes an existing EuroLeague projection
with replayable original inputs and its original pre-tipoff fixture observation.
It never creates predictions or guesses missing outcomes. Before the registered
tipoff it returns `awaiting_tipoff` without a provider request. An unplayed
provider record after tipoff returns `awaiting_final` without fetching stats.

After a played response, the collector fetches the matching stats route and
requires the original provider, league, season, fixture identifier, UUID, game
code, UTC start, home/away club codes and phase to agree. Source period totals,
overtime ties, player/club/season identities, made shots, points and team-plus-
player totals must reconcile. The full game-clock duration must match the
period evidence: 40 minutes for regulation, 45 for one overtime, and so on.
The `played` flag alone cannot certify completion. `Confirmed` is not treated
as a final-status indicator.

The retained result observation contains the replayable original game/stats
fields, actual local observation time, source URLs, the original prediction
input digest and the original fixture-observation digest. The result timestamp
is when the completed result was observed, not an invented final-buzzer time.
Hashes detect corruption; they are not independent provider signatures.

Outcome and evidence insertion is atomic. The transaction rechecks registered
prediction/provenance/start and original digests. Partial failures roll back
both rows. Identical later fetches preserve the first observation and do not
increase the sample size. Different scores, changed source facts, backdating,
or attaching evidence to an existing legacy result are rejected. Provider
corrections require a separate explicit workflow rather than silent replacement.

## Explicit evaluation

```sh
python -m providers.euroleague_results \
  /workspace/scratch/euroleague-prospective-elskbakv/research-ledger.sqlite E2026_100

python -m verified_backtest_cli \
  /workspace/scratch/euroleague-prospective-elskbakv/research-ledger.sqlite \
  --league EUROLEAGUE --require-bound-evidence
```

Collection writes only a verified final to the selected existing local research
ledger. Reporting operates on a backup, preserving source bytes. NBA remains the
default report league; EuroLeague requires explicit selection and reports
`provider: EUROLEAGUE_LIVE`. EuroCup is unsupported by this evaluator and no
profile was fabricated for it.

Only replayable input, fixture and final-result bindings enter EuroLeague error
metrics. Missing/corrupt bindings, scope mismatches and pending results have
separate, mutually exclusive counts. Counts reconcile to all predictions.
Only `FINAL_WITH_OT` is supported; regulation outcomes cannot be substituted.
A one-match evaluation is labeled `small_sample`, never proof of calibration.
Even larger descriptive samples do not automatically establish calibration.

## Validation

Full local suite: **482 passing tests**, including fifteen new synthetic
integration cases. These cover actual FAZ13 generation and fixture persistence
before synthetic result ingestion, normal and overtime finals, incomplete data,
wrong identity/start/orientation, full-clock/stat checks, pending matches,
atomic rollback, idempotency, conflicts/backdating, posthoc attachment refusal,
corruption, scope separation and read-only CLI behavior. All source responses
and results in those tests are mocked/synthetic, not real predictive accuracy.
Compilation and `git diff --check` passed.

The existing real prospective `E2026_100` (OLY–RED) ledger was checked using the
new collector. Its registered start is `2026-11-06T19:15:00+00:00`; the check
returned `awaiting_tipoff` and made no final-result request. It retained **zero
outcomes and zero result observations**. The strict report returned one
prediction, zero evaluated samples, `metrics: null`, and
`calibration_status: NOT_ESTABLISHED`.

The exact outputs are retained in `evidence/euroleague-result-check-20261104.json`
and `evidence/euroleague-bound-report-20261104.json`. The real completed-result
path for this future fixture has **not yet been validated**. No result was
invented to complete the demonstration or populate metrics.

## Remaining work

Collect an authentic completed result when the fixture is due, then accumulate
a prospective sample and perform empirical calibration. Independent provider
and possession checks, the unresolved ZAL persistence check, EuroCup profile
development and production-entry-point integration remain open. No scheduler,
messaging, production deployment, merge, paid service or secret change was used.

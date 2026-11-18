# Additional critical integrity audit — 18 November 2026

Base: `bb9ec84d5615a8bdd81f06f94a89b4cc876c3872` (draft PR #91).
Branch: `feature/critical-integrity-audit-20261118`.

These are reproduced code defects, **not established explanations of the user's
historical misses or pending phone results**. The original UserLAnd archive and
dedicated Telegram configuration remain unavailable in Cloud. No production
deployment, main merge, secret change, archive deletion or paid provider call
was made. The production collector's opt-in setting remains disabled by default.

## Confirmed findings

| Finding | Before | After | Regression proof |
|---|---|---|---|
| Shared-ledger NBA outage | `forward_nba_results.read_confirmed` scans every league, then rejects a non-NBA payload. A schema-valid EuroLeague snapshot therefore disables NBA settlement when the new timer is used with a shared production ledger. | A new strictly NBA-filtered read-only reader validates SQL indices, payload SHA, commit receipt and publication deadline. The source-pinned legacy forward reader remains unchanged for its dedicated experiment. | `SharedLedgerTests.test_valid_european_record_does_not_disable_nba_settlement` reproduces the old reader's rejection and settles NBA while leaving the European forecast pending and all commit proofs unchanged. |
| One invalid day prevents other finals | A bad digest/identity/clock raises out of the entire day loop. A later valid source day is never reached. Previously settled dates are fetched repeatedly too. | Reject and report the invalid source date, continue other independent dates, and request only started, unresolved snapshots. All-invalid sources still fail closed. Database failures still propagate rather than being hidden as source errors. | `SharedLedgerTests` covers valid later finals, repeat polls without source calls, and a real SQLite exception. Existing invalid URL/digest/clock tests still pass. |
| OT enters early-period markets | The generic sample and settlement functions add OT to **any** period. A first-quarter total of 50 becomes 65 when game OT adds 15, potentially changing the direction at a line of 60. | Reject OT inclusion for 1Q/2Q/3Q/1H in both primitives. FULL/4Q/2H retain explicitly requested, coherent OT support; the normal-scope defaults remain unchanged. No bookmaker rule is inferred. | `PeriodScopeTests` checks both simulated and realized values and retains positive FULL/4Q/2H cases. Existing second-half-OT regressions remain green. |
| False 100-game calibration acceptance | New `shadow_learning.evaluate` pools exact fitted model versions. Two independently inadequate 50-game fits can produce `CANDIDATE_FOR_MANUAL_REVIEW` at a pooled 100 games. Snapshot variants of one fixture also count separately. | Evaluate each original fit and season separately, reject duplicate independent fixtures, and provide no pooled score or gate. Mixed-cohort `n` is undefined; published fixtures and settled forecasts are separately labeled. | Two 50-game fits remain insufficient. Five snapshot variants cannot turn 20 matches into 100 independent games. Pending mixed cohorts do not claim settled counts. |
| Research queue starvation | New V3 sorts pending fixtures chronologically and always retries the first two. If those remain unsupported, a later supported fixture is never attempted. | Use result-blind fair rotation with independent score/shadow retry deadlines. All eligible originals remain in the admission denominator. | `StudyIntegrityTests.test_two_unsupported_fixtures_cannot_starve_later_supported_fixture` uses real model predictions, two failing fixture checks and a later successful publication on the next tick. |
| Acceptance evidence can silently disagree | New V3's label-map comprehension keeps the last conflicting native label; candidate publications need not have a prior admission. Shadow evaluation does not compare its saved raw probability with the authenticated original winner vector and can consume a foreign-league label. | Reject duplicate label identities, require prior admission before acceptance, enforce study version, check the exact original probability and NBA scope, and reject non-finite scores/future evaluation clocks. | Separate tests cover conflicting native outcomes, absent admission, changed probability under the same snapshot SHA and a foreign-league final. |

The OT issue concerns a conditional API path when OT paths/rules are supplied;
it does not mean all current Telegram quarter outputs contained OT. Likewise,
the shared-ledger problem is latent in the opt-in production collector; the
isolated NBA-only test ledger does not itself establish a shared-ledger incident.

## Reproduction and test evidence

A detached temporary worktree at the exact base commit was used, without
reverting or changing the working branch. The corrected synthetic regression
fixtures were copied into that base worktree. The baseline run reported:

```text
Ran 15 tests in 0.423s
FAILED (failures=17, errors=3)
```

Failure counts include period subtests. The errors include the shared-ledger
rejection, the abort on an invalid source day and the legacy status API's
missing integrity-attestation field. The calibration
counterexample actually returns the erroneous manual-review status; it is not
inferred only from reading code. Synthetic scores are not live model performance.

After correction, the targeted NBA/result/decision suite passed 114 tests; the
subsequent targeted result/model suite passed 72 tests. The local full suite
then reported:

```text
Ran 1546 tests in 147.214s
OK
```

A final mixed-cohort pending-counter regression was subsequently added; the
latest 53-test model/integrity subset passed in 7.715 seconds. Exact
commands, counts, raw log hashes and compressed output are in
`evidence/critical-integrity-validation-20261118.json`. Exact-head CI results,
including deployment-image tests and hard 256 MiB / one-CPU probes, are reported
in the PR. The provider resource probe now includes these new regressions.

The initial test-development issues were corrected without weakening source
guards: one synthetic European fixture initially had post-capture input clocks,
and the queue test initially tried to parse the literal synthetic season as a
real year. The final baseline reproduction uses valid fixtures and a cached,
actually fitted synthetic model. No remaining passing status is based on those
invalid setups.

## Existing plans and archives

All **27 V1** and **13 V2** registered source pins match the base commit.
`models.py`, `live_nba.py`, the existing V1/V2 protocols, the legacy forward
reader and all European model files are unchanged. Forecasts, snapshots,
results and native source archives were not edited or relabeled.

The corrected V3 study has a new version:
`ISSUE90_SEPARATE_NBA_STUDY_V2_INTEGRITY`, with separate default storage at
`data/nba-research-v3-integrity-v2`. The older `data/nba-research-v3` remains
untouched. Its old reports can still be inspected, but are explicitly marked
`NO_CURRENT_INTEGRITY_ATTESTATION` by the read-only status envelope. Old plans
are not silently re-signed, reset, copied or counted as new confirmatory trials.

The original `/accuracy` and `/compare` archives keep their existing records.
Separating the corrected study is necessary because its acceptance semantics
and source pins changed; it is not deletion of the historical match count.

Current diagnostic commands on this isolated branch:

```bash
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh --issue90-status
```

To inspect the old V3 directory without migrating or modifying it:

```bash
cd ~/zeynal-hybrid-844
.venv/bin/python -B -m hybrid_engine.issue90_research \
  --directory ~/zeynal-test-isolated/data/nba-research-v3
```

The launcher accepts this isolated audit branch as well as the earlier research
branches. No main branch is enabled by this change.

## Remaining external acceptance

Real Telegram preflight still reports `NOT_CONFIGURED`: dedicated test token,
bot identity and chat configuration are missing. Actual Telegram delivery is
**NOT_VERIFIED**. Existing PTB/local HTTP tests remain local transport evidence.
The user's actual archive was not inspected or repaired remotely. New study
superiority, measured PBP/player integration and release approval remain
outstanding. Production readiness remains **NO_GO**.

# FAZ 95.7 — isolated EuroLeague / EuroCup automatic PREMATCH capture

## Root cause and integration

`test_bot.py` started a background **result collector**, but new European
forecasts were produced only when a human issued `/analyze`. If the first
request arrived inside the final 15 minutes, the existing safety guard correctly
refused new inference and there was no earlier forecast to replay.

The isolated test bot now starts `EuropeanPrematchScheduler.run()` after its
expected test-bot identity and empty webhook are verified. It stops the task
with the existing shutdown cancellation flow. Replay-only mode cannot start
it. No background Telegram broadcast or production application hook is added.

`AutomaticEuropeanService` in `hybrid_engine/europe_prematch.py` extends the
existing `europe_live.EuropeanService`. It uses its original official preflight,
prepared model loader, historical feature cut, simulation and reporting. Both
`europe_live.py` and `europe_models.py` remain **byte-for-byte unchanged**: their
hashes are source pins in existing prepared models, so editing them would
invalidate those models. NBA/challenger model pins and the registered phone
protocol are also unchanged. No model preparation, training or calibration is
performed by this scheduler.

## Timing and status policy

All stored clocks are UTC; command dates and displayed match times use
`Europe/Istanbul`.

| 22:30 TSİ fixture | Existing valid forecast | No existing forecast |
| --- | --- | --- |
| 20:30–21:00 | Reuse / skip automatic capture | Target early-capture window, provided model/history/source validate |
| 22:10 | Replay exactly | Catch-up capture may proceed with verified inputs |
| 22:16 | Replay exactly, even without current source access | ABSTAIN; final-15-minute cutoff |
| 22:31 | Archived replay only | ABSTAIN; already started, no historical PREMATCH backfill |

The automatic target is 90–120 minutes before tipoff. A restart after that
window may catch up only while **more than 900 seconds** remain. At exactly
900 seconds and later, no new publication is accepted. The cutoff is checked
before inference and again at publication, including before/after the forecast
asset's disk write. A boundary crossed during inference or asset I/O leaves
no `first-*` PREMATCH publication. An unpublished content-addressed asset can
remain after a failed attempt; it is not a published forecast and is not listed
or counted in accuracy. Nothing is deleted to conceal a failed attempt.

The current official catalog must be URL/hash/competition/season/clock bound,
complete, and fresh. Match date/hour/status must be confirmed, `played=false`,
scores zero, and available partial scores zero. A future clock cannot override
nonzero live scores. The original inference routine rechecks the fixture and
source before publishing. Missing/expired/tampered models, insufficient history,
changed fixtures and source failures abstain rather than synthesize data.

The loop wakes every 60 seconds, processes at most four matches serially, rotates
the league order, and backs off each failed fixture for 300 seconds so one
blocked match cannot starve others. Idle discovery waits until the next
120-minute window or at most 30 minutes; active discovery normally waits five
minutes. Pending work can be revisited after 60 seconds. Existing controlled
transport cooldowns remain effective. These are scheduling/admission bounds,
not a promise of an uninterrupted network or a hard process-kill deadline.

## Immutable publication and offline replay

- An asynchronous nonblocking OS file lock serializes European inference for
  each isolated league directory, across service instances and processes.
- A separate publication lock rechecks existing fixture **and official provider
  match IDs**, independently of model version or a rescheduled canonical ID.
- The first valid publication wins. Existing forecasts, prepared parameters,
  source receipts and results are not overwritten. Existing legacy records
  are retained rather than migrated or silently deduplicated.
- Previous-registry/legacy provider IDs prevent a second publication for the
  same official match. The original engine's same-day legacy replay remains.
- Archived team aliases are resolved only from the original hash-verified
  fixture document. Shared/ambiguous aliases are refused. This is archived-pair
  replay, not a fabricated two-team season participant registry.
- A stored forecast can therefore be replayed with a recorded source alias
  during the final 15 minutes or after tipoff even if the provider is offline.
- One published record contains the unchanged BAYES_QMC, BAYES_MC and
  FAZ13_REFERENCE component outputs. Three model rows in `/predictions` are
  component reports, not three independently published matches.

Automatic attempts use a separate append-only hash journal under
`data/europe-prematch/auto-*.json`. Storage is bounded to 4,096 reports / 64 MiB.
Journal failure is logged explicitly and reported as `PARTIAL_ABSTAIN`; existing
prediction archives remain durable. Journal errors never expose raw exception
text, tokens or keys. `/test euroleague` and `/test eurocup` show the automatic
capture state. A read-only launcher mode inspects recorded attempts.

## Verification and actual Telegram limitation

Twenty-one new tests cover both leagues, real simulation samples using synthetic
native fixture/history inputs, missing models/history, source failure/recovery,
disk errors, hash tampering, process publication races, concurrent services,
restart/model-version reuse, rescheduled IDs, exact cutoff, simulation/disk
boundary crossings and fair retry behavior.

A real PTB handler / loopback HTTP integration captures both leagues early and
delivers `/analyze` at **22:10, 22:16 and 22:31**, then `/predictions`, `/compare`,
`/accuracy` and `/test`. It asserts no resimulation, unchanged archive bytes,
proper league routing, visible NOT_CALIBRATED and Telegram message length limits.
This is explicitly a **local HTTP double**, not external Telegram E2E.

Initial tests exposed an archived-alias replay bug; that was fixed using the
original pinned source aliases. Test-harness failures caused by loading native
Nov 12/13 archives with a Nov 11 mocked clock and by an uninjected scheduler
clock were corrected without weakening the native archive clock checks.
Failed tests were not skipped or disabled. Final counts and exact-HEAD GitHub
unit/Docker/resource checks are recorded in PR #89.

Local final validation: **1,445/1,445** full tests passed in 126.240 s;
**75/75** targeted tests passed in 25.132 s. Zero failures/errors. The final
loopback handler check was rerun after explicitly pinning its synthetic test
token in the cached main module. All original 1,424 tests are retained.
Machine-readable results and log hashes:
`docs/evidence/europe-auto-prematch-phase957-20261117.json`.

Cloud preflight returns `NOT_CONFIGURED` with all four dedicated test Telegram
fields absent (`ZEYNAL_TEST_BOT_TOKEN`, `ZEYNAL_TEST_BOT_ID`,
`ZEYNAL_TEST_BOT_USERNAME`, `ZEYNAL_TEST_CHAT_ID`). Therefore actual authenticated
Telegram E2E is **BLOCKED** here. No credentials were requested, imported from
production or printed. Machine-readable local evidence accompanies this report.

## UserLAnd operation

Stop the isolated bot with Ctrl+C and run the existing launcher. It fetches the
same research branch and starts automatic capture without a new model fit:

```bash
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh
```

Keep it running at least two hours before the fixtures. The phone/Ubuntu
process must stay alive; a stopped or suspended UserLAnd session cannot prepare
forecasts. In the authorized test chat, check:

```text
/test euroleague
/test eurocup
/predictions EUROLEAGUE
/predictions EUROCUP
```

After the update, recorded attempt status can also be read without starting a
second poller or changing data:

```bash
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh --europe-prematch-status
```

Use `/analyze` with the official fixture command in the final 15 minutes and
after tipoff. The same original forecast SHA and issue/archive time must remain.
Check `/compare EUROLEAGUE <E-season_game>` or `/compare EUROCUP <U-season_game>`
and `/accuracy <league>` after a verified final; unfinished matches must not
become successes. Missing sources or models must remain ABSTAIN.

Production decision remains **NO-GO**: authenticated phone E2E of this automatic
flow is pending, calibration/sample limitations and European market/roster
coverage blockers remain. This change does not resolve those independent
limitations. No main merge, Fly deployment, secret change, disk/snapshot action,
production bot change or archive reset was performed.

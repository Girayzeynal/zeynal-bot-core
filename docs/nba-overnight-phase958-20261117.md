# FAZ 95.8 — NBA overnight capture without a human tipoff-time routine

The user should not have to stay awake until NBA tipoff or stop the test bot to
run challenger capture. The prior advice to issue `/analyze` around 45 minutes
before the game described a manual workflow, not a model requirement. The
registered 3,600-second limit measures **age of original inputs at challenger
capture**, not distance from capture to tipoff.

## Implemented flow

`NBAOvernightScheduler` starts in `hybrid_engine.test_bot` after the expected
isolated bot identity and empty webhook are verified, alongside the existing
European and result tasks. Replay-only mode does not enable it. Only a real
`LiveNBAHybridService` with its prepared model enables NBA overnight scheduling.

It discovers verified ESPN fixtures in the **next 36 hours**, preserving
Istanbul calendar dates across midnight. A bounded batch prepares up to two
new matches serially. The native service still performs identity, history,
source-clock, target-exclusion and precommit fixture rechecks. Postponed/live/
completed fixtures and the final 15 minutes cannot create a new primary NBA
forecast. An isolated ledger adapter passes a `tipoff - 900 seconds` durable
deadline into the existing atomic SQLite commit/receipt implementation.
Existing snapshots and receipts are never modified.

The candidate experiment is captured immediately after each new original,
using the **existing registered plan** and the same immutable original input
assets. Fresh manual originals are also collected in the background. The loop
wakes every minute, normally rediscovers fixtures after ten minutes, revisits
remaining batches after one minute, and backs off unavailable fixtures for
five minutes. Source transport quotas/cooldowns and original inference budgets
remain effective. These are admission/scheduling bounds, not hard termination
guarantees for a worker HTTP call.

No human needs to issue a command at night or stop the test bot for
`--challenger-capture`. No automatic Telegram broadcast is sent. `/nba` and
`/analyze` remain usable; `/predictions NBA` includes the original automatically
archived forecasts. `/test nba` shows automatic scheduling, registered-plan
status/SHA, pending/settled experiment cases and matched-game/day counts **per
cohort**, rather than pooling leagues or incompatible fits.

The live command router also checks the static replay result's actual match
date before using it. An older fixture between the same teams cannot hide an
automatically archived new fixture. Replay-only mode retains its original
date-mismatch behavior; live mode delegates nonmatching dates to the verified
live service, which still rejects retrospective new forecasts.

## Existing plan and records stay intact

- `live_nba.py`, the sampler, model sources, `challenger_forward.py`,
  `challenger_review.py`, and all 27 registered predictor pins remain unchanged.
- The phone protocol SHA remains
  `1e8f24a665a8b34a2ca22c37e408591ae8547b12788fe70c7150079b43249317`.
- No protocol is silently registered, reset, backdated or relaxed. Missing or
  invalid plans abstain explicitly. The original 100 future matched games,
  20 distinct Istanbul match days, freshness, coverage and statistical gates
  are retained; no automatic promotion occurs.
- Active model parameters are not fitted or replaced. The existing challenger
  procedure may update its **separate research posterior** from the original
  pre-issue history, as specified by the existing plan. Calibration remains off.
- The legacy function's CLI location label is explicitly annotated as
  `ISOLATED_BACKGROUND_WORKER_NOT_TELEGRAM_REQUEST` in the automatic report.
  Predictor files and saved experiment forecasts are not rewritten to do this.
- Original provider match IDs already in the main ledger are skipped, including
  rescheduled fixtures. No second original is created merely to refresh old
  inputs or change a first timestamp. An original already too old for the plan
  stays in the ordinary archive and is excluded from the registered experiment.
  `/test nba` exposes this exclusion rather than treating it as accepted.
- Result collection keeps appending verified native finals. The separate
  performance reader joins only registered prematch captures with available
  finals. Historical development games are not promoted into a new cohort.

The automatic attempt journal is separate under `data/nba-overnight/auto-*.json`,
using the existing bounded, content-addressed writer (4,096 entries / 64 MiB).
Disk/journal/plan/source errors produce explicit partial-abstention states and
safe logs without raw exception text or credentials. Cancellation is handled by
the existing bot shutdown lifecycle. European inference and production Faz13
remain unchanged.

## Validation and evidence boundaries

Sixteen new tests use native-shaped synthetic ESPN receipts with **real**
prepared-model inference and registered candidate capture. They verify:

- 19:00 Istanbul capture of a 03:00 next-day match, including an immediately
  archived stochastic-period candidate, without waiting until tipoff.
- Real 10,000-sample distributions, unchanged registered plan and active model.
- Restart/retry immutability and stale-original exclusion without retiming.
- Fresh manual originals collected automatically without a terminal command.
- Explicit missing-plan/source/capture failures, postponed/started fixtures,
  atomic final-15-minute commit rejection, and bounded timezone-aware discovery.
- Real PTB handlers against local HTTP for `/test nba`, `/predictions`,
  `/accuracy`, `/compare` and archived `/analyze`, with no unsolicited messages,
  resimulation, changed original DB bytes or unsupported calibration claims.

These are **synthetic provider / local HTTP** tests. They are not authenticated
live provider or external Telegram E2E evidence. Cloud preflight still reports
the four dedicated test-bot configuration fields missing. Real E2E of this new
overnight feature therefore remains **BLOCKED in Cloud** until the authenticated
UserLAnd bot is restarted and its actual new captures are inspected.

Full local counts, log hashes and exact-HEAD GitHub/Docker/resource results are
reported in the accompanying evidence and PR #89. No failed test is hidden or
disabled.

The initial full run exposed a **test fixture cleanup bug**: the new PTB test
used an unstarted `IsolatedAsyncioTestCase` as a fixture and its fake-clock
cleanup could not execute. This leaked the Nov 11 test clock into later native
archive tests (8 failures / 26 errors; class-setup failures prevented some
cases from running). Cleanup is now registered on the actual running test's
runner. Native clock/source guards were not weakened; the new NBA test followed
by native archive/posterior tests and the complete suite are rerun afterward.

Final local results after the routing correction: **1,461/1,461** full tests passed in 118.459 s; the new NBA
suite followed by native archive/posterior clock regressions passed **49/49** in
5.761 s. Overnight plus static-replay routing regressions passed **41/41** in 7.116 s. Zero final failures/errors, all previous 1,445 tests retained.
`docs/evidence/nba-overnight-phase958-20261117.json` records the final and initial
log hashes, the resolved fixture failure, and unchanged protected source hashes.

## UserLAnd operation

Stop the isolated bot once with Ctrl+C and launch the updated branch:

```bash
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh
```

Keep this process alive and the phone connected. Android/UserLAnd suspension or
process shutdown prevents background work; code cannot run inside a stopped
terminal session. No timing-sensitive manual Telegram command is required.

When convenient, send these **in Telegram**, separately:

```text
/test nba
/predictions NBA
```

The expected diagnostics include `NBA otomatik PREMATCH: AÇIK`, `gelecek 36 saat`,
and a registered protocol status with pending/settled counts. `CHECKED` alone
does not prove a new capture: inspect the original and experiment records.
An already archived or ineligible match must not be counted again. New
overnight records retain their real original production time and raw
`NOT_CALIBRATED` status. Alternative diagnostics, only if needed, are read-only:

```bash
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh --nba-overnight-status
```

Production decision stays **NO-GO** until independent acceptance and explicit
release approval. No main merge, Fly deployment, production data/secret change,
disk/snapshot operation or paid service is part of this change.

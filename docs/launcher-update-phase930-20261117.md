# FAZ 93.0 — Reload updated launcher before dispatch

Continue PR #89 from 029f620 on the same research branch. This is a launcher
correction; it does not change any model, probability, archived prediction,
SQLite data, Fly machine/volume, secret, snapshot or production deployment.

## Observed report and reproduced cause

The user's first command was --player-inputs-plan while the installed launcher
was 8042f2d. The terminal shows a fast-forward to 029f620, followed by FAZ17 init
and Application started, without the expected PLAYER_INPUT_BATCH_V1 JSON.
That output alone does NOT prove that collection occurred.

The old Bash process continues executing its already-open file/buffer when Git
replaces the on-disk launcher. Version 8042f2d did not recognize the new option;
unknown options fell through to the normal poller. The first command therefore
blocks in the bot, and the next two pasted shell commands cannot be assumed to
have run. The API init log is not evidence about this offline command's provider
availability and was not treated as the cause.

The regression uses the exact pinned 8042f2d launcher in an isolated local Git
installation and updates its origin to the current source DURING execution.
The first old invocation demonstrably reaches a test_bot shim; the next fresh
invocation reaches player_inputs. The shim makes no Telegram/API requests.
The old file is tests/fixtures/launcher-8042f2d.sh, SHA-256
42d77e81cffb9cc247ca8fe32fe94d307eaa1efc1f2f6d263374aa8171c31cd4.

Earlier launcher tests used a current, already up-to-date installation and did
not cover this update boundary. They are retained; their installation now
contains the actual launcher file, required for the new source comparison.

## Correction

The launcher fingerprints its installed source before fetching. After a successful
fast-forward it checks the source again. If changed, it prints only
RESTARTING_UPDATED_LAUNCHER, closes its inherited polling lock descriptor, and
executes the installed script with the exact original arguments.
The new process acquires the existing single-instance lock normally. If another
poller wins that race, it refuses a second instance rather than bypassing locks.
No token is read before mode dispatch.

Unknown modes and extra arguments now return exit 2 with a fixed diagnostic
instead of silently starting the bot. Existing no-argument startup and existing
provider-check / error-review modes remain supported. The provider-check and
error-review shortcuts preserve their prior no-update behavior.

An old pre-fix process cannot retroactively adopt this correction. Users upgrading
from 8042f2d must stop the mistakenly launched isolated poller and invoke the
updated on-disk file again. Updating the checkout explicitly before invocation
also avoids the boundary. Do not run a second poller or edit production secrets.

## Verification

Seven launcher tests pass locally (the original test plus six new cases):
- Exact legacy update reproduction and successful next invocation.
- Fixed launcher re-executes once, preserving the requested plan mode.
- Numeric fixture argument survives, with no self-lock failure.
- Unknown mode cannot fall through even when bot credentials/model shim exist.
- Unexpected extra arguments are rejected.
- Real Python player_inputs CLI reaches DRY_RUN using a real temporary SQLite
  ledger; byte hash is unchanged, output directory is not created, token absent.
- Existing plan/collect/results dispatch remains covered.

The existing hard 1 CPU / 256 MiB probe already includes this test module.
CI and final full-suite counts are recorded on PR #89. Synthetic local Git and
HTTP/PTB tests are not real Telegram E2E or private UserLAnd archive validation.

## Single-terminal recovery

Stop the isolated poller with Ctrl+C. Execute only this command first:

    bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh --player-inputs-plan

Expected: JSON format PLAYER_INPUT_BATCH_V1, status DRY_RUN (or an explicit
BLOCKED archive error), and return to the shell. Application started is NOT the
expected response. If there are suitable archived future fixtures, then run:

    bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh --player-inputs-all

Finally restart the isolated poller normally:

    bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh

The user's 03:38 TSİ log is after Boston–Orlando's archived 03:00 TSİ tipoff.
That original match cannot receive a newly backdated PREMATCH minute input.
An empty eligible plan is legitimate when all archived games have started.
New genuinely future fixtures need their normal isolated /analyze archive first.
No historical forecast is changed to bypass this requirement.

Production/default-model decision remains NO-GO. This fixes command routing,
not scoring accuracy or calibration; real new-head Telegram/phone verification
is still required. Main merge and Fly deployment remain prohibited.

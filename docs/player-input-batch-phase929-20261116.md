# FAZ 92.9 — Bounded prospective NBA player-input collection

Continue PR #89 from 8042f2d on its existing research branch. No default model,
prediction mathematics, calibration, production bot, old archive, main branch,
Fly deployment, secret, disk or snapshot changes.

## Gap addressed

The player model needs real projected-minute inputs archived BEFORE each target
game. The previous increment only offered a one-fixture collection CLI. A list
of game outcomes, past actual box minutes or repeated Telegram displays is not
a substitute for this prospective input archive.

The new offline batch planner reads existing native-verified NBA forecasts with
LedgerReports and exact snapshot SHA lookup. It does not create new forecasts.
A dry run needs no Telegram token, model fitting or network source requests and
does not create its output directory or write a report.

The collector processes, by default, up to FOUR games sequentially from a
48-hour horizon with at least 15 minutes remaining before tipoff. These are
research collection admission limits, not a claim about optimal injury timing.
Use the one-game tool for an explicit eligible fixture if needed. Function
parameters have strict bounded integer policies, including rejection of bools.

Already archived first minute inputs are witness-verified and skipped, so they
do not consume the limit or indefinitely block later fixtures. A different
original snapshot link is reported rather than replaced. Ambiguous model
versions, settled games, started games and unsuitable time windows are counted
as separate skip reasons. Missing/invalid archives are BLOCKED, not a successful
empty result. No file or schema is created at a missing ledger path.

The pre-tipoff window and selected snapshot pin are checked again before each
collection. Two consecutive source/input blocks stop further source work.
A 180-second admission budget is checked BETWEEN fixtures: it is NOT a hard
process timeout. An in-flight collection keeps the existing native request
timeouts. There are no parallel requests added by this batch layer, no retries
in an automatic loop, no fitting and no Telegram polling.

The exact original SQLite bytes are fingerprinted using 512-KiB streaming chunks
before and after the pass. If another process changes the file, the report says
so; it never attempts to restore or overwrite that file. This measurement is a
file-byte observation, not a guarantee against an external WAL writer. Run the
single-terminal launcher with the isolated poller stopped as described below.

A real pass writes only separate content-addressed batch reports and the
existing dedicated player-input archive. Source blocks are legitimate results:
dual-source absence corroboration, exact identities, full history and all
previous prospective clock checks remain required. No fake minutes or success
counts are inserted when the sources are insufficient.

## UserLAnd — single terminal

Stop the isolated poller with Ctrl+C, then run the read-only plan:

    bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh --player-inputs-plan

The existing launcher fetches/fast-forwards the SAME research branch and holds
its existing local single-instance lock. The planner itself performs no API
requests and writes no files. Check selected, skipped and eligible_total.

To collect separate minute inputs for at most four suitable archived future games:

    bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh --player-inputs-all

This is a one-shot offline acquisition, not a new scoring run. Repeating it skips
successfully archived first inputs. PARTIAL / COMPLETED_WITH_BLOCKS / BLOCKED are
reported explicitly, with per-game status and remaining_eligible. The selected
list is the planned list; results lists only attempts or windows that closed.

To review the new paired model against later native results without long paths:

    bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh --player-shadow-results

Only prospectively published shadow pairs are eligible. The ten previous games
do not become paired player-model results after the fact. With no prepared real
player model and no new pairs the correct result is n=0, not fabricated metrics.
No training is invoked by this command.

Restart the original isolated poller afterward:

    bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh

The private ledger is on the phone, not available in this Cloud environment.
These new commands still require real UserLAnd verification. Do not paste tokens
or API keys into chat. Real Telegram E2E for this revision remains BLOCKED.

## Verification and recovery

Twenty new batch tests passed locally before the Cloud executor disconnected.
An initial synthetic SQLite test used a clock earlier than its archived snapshot
and correctly failed the existing clock validator. It was corrected to read at
a genuinely later time; the insufficient lead time is then explicitly skipped.
No validator was bypassed or test disabled.

Tests cover read-only dry run, limits/order, actual SQLite byte preservation and
exact snapshot lookup, duplicate fits, previous input preservation, tipoff/window
boundaries, source circuit break, admission budget, changed pins, safe exceptions,
missing schema/database, concurrent external writes and disk failures.
A separate launcher test uses a real LOCAL synthetic Git origin and installed
interpreter; it runs the new flags without a Telegram token or poller.
Both new modules are included in the existing hard 1-CPU / 256-MiB runtime probe.

The terminal failed again before a final local full run. Source recovery uses
the preserved conversation edits on the existing branch; exact-head GitHub CI
is the final verification source. The PR contains its actual counts/status.

The prior native box probe files were recovered and inspected locally: ESPN
401909976 and 401909296, 51 player rows in total, explicit DNP rows=5.
The displayed minute sums for their home/away sides are 240/241 and 240/241;
rounding is not exact-seconds evidence. Receipt clocks are later than the
original Philadelphia forecast and must not be backdated into it.
A deterministic local source packet was assembled (94,124 bytes,
SHA-256 c13228dc3960d20da6f59282c1bff3dbfa80096110467e66079803b6e430425c)
but the executor connection failed before its bytes could be uploaded.
That packet is NOT included in this commit and no CI native replay result is
claimed for it. Previously committed evidence packages remain unchanged.

## Decision

NO-GO for a default/production model switch. Real qualified player training and
new paired OOS results remain zero in the available evidence. Individual player
defense/pace, minute uncertainty and independent calibration remain unfinished.
The 100 training / 100 future audit / eight day cluster research thresholds from
the previous increment are unchanged and are not automatic promotion criteria.

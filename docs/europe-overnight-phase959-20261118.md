# FAZ 95.9 — EuroLeague and EuroCup overnight preparation

The European automatic scheduler previously admitted new fixtures only inside
two hours of tipoff. It now prepares every eligible, unarchived official fixture
in the **next 36 hours**, matching the NBA scheduling horizon. Users can leave
the isolated bot running in the evening instead of issuing commands near tipoff.

## Behavior

- Both EuroLeague and EuroCup use the existing automatically started scheduler.
  The 36-hour horizon is inclusive; matches beyond it wait for a later scan.
- Official competition, season, confirmed date/time, scheduled status and zero
  live scores remain mandatory. Dates shown in commands use Europe/Istanbul,
  including next-day fixtures.
- Each league retains its own prepared model and verified historical inputs.
  Missing models, history or source verification produce explicit abstentions.
  No training, calibration or fitting is added to the automatic request path.
- The existing bounded serial batches, rotating league priority, retry/backoff,
  publication locks, immutable first record and final-15-minute checks remain.
  Restarts, manual commands and postponed match IDs cannot create a second
  original merely to update its timestamp.
- A late `/analyze` reopens the saved forecast. Without a prior forecast, the
  final 15 minutes and started/completed games cannot be backfilled as prematch.
- `/predictions`, `/compare` and `/accuracy` use the same existing archives and
  result readers. No unsolicited Telegram messages are sent.
- `/test euroleague` and `/test eurocup` now show
  `Avrupa otomatik PREMATCH: AÇIK · gelecek 36 saat`.

The attempt report advances to `EUROPE_AUTO_PREMATCH_V2`, replacing its obsolete
90–120-minute target metadata with `lookahead_seconds: 129600`. The read-only
status reader still accepts historical V1 journals without rewriting them.
Scheduling bounds are unchanged: the worker wakes every minute, scans eligible
fixtures every five minutes, revisits unfinished batches after a minute, and
waits up to thirty minutes when there is no eligible match (or until the next
fixture enters the 36-hour horizon). Original source quotas remain effective.

## Evidence boundaries

Two additional tests cover both leagues preparing next-day fixtures more than
24 hours early with real 10,000-sample model inference, offline replay after a
restart, model/archive byte preservation, and the inclusive 36-hour boundary.
Existing real PTB/local HTTP tests now prepare at 19:00 for a 22:30 match,
outside the old two-hour window. They exercise `/analyze` at 22:10, 22:16 and
22:31 plus listing, comparison, accuracy and both league diagnostics.
All earlier concurrency, process publication race, missing-data, live-score and
deadline-crossing tests remain in place.

These tests use synthetic official-source receipts and local HTTP Telegram
transport. They are not authenticated live-provider or external Telegram
delivery evidence. Dedicated test-bot configuration is absent in Cloud, so real
Telegram validation requires restarting the user's existing isolated UserLAnd
bot and inspecting its actual records.

NBA inference, European engine/model/sampler source pins and all saved forecasts
remain unchanged. The registered NBA challenger plan is not altered or applied
to European games. European leagues retain separate model and performance
cohorts; their raw match counts do not satisfy the NBA experiment's gate.

Final local result: **1,463/1,463 tests passed** in 121.272 seconds, zero failures/errors. All previous 1,461 tests remain; two are added. Source hashes and the full log hash are recorded in `docs/evidence/europe-overnight-phase959-20261118.json`. Exact-commit GitHub/Docker/resource results are recorded in PR #89.

## UserLAnd

Stop the current isolated bot once with Ctrl+C and run:

```bash
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh
```

Keep UserLAnd running with internet access. No timing-sensitive night command
is necessary. Send each check as a separate Telegram message:

```text
/test euroleague
/test eurocup
/predictions EUROLEAGUE
/predictions EUROCUP
```

Check real production/archive times and saved match IDs; an `AÇIK` or `CHECKED`
label by itself is not evidence that a new eligible match was archived.
The existing optional read-only terminal check is unchanged:

```bash
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh --europe-prematch-status
```

No main merge, Fly.io production deployment, production data/secret change,
archive deletion/reset or paid service is authorized by this implementation.

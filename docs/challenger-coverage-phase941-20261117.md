# FAZ 94.1 — coverage presentation without invalidating the registered plan

Continue PR #89 from 074e4d7. UserLAnd completed the real 18-game review:
reviewed=18, blocked=0, remaining=0, database_and_wal_unchanged=true.
Updated Bayes total MAE 15.90170754 versus frozen 16.68559664 and Faz13 reference
16.48888889; team MAE 10.47203785 versus 10.74396448 and 10.73333333.
All show 13/18 winner matches. This is three day clusters of development data,
not fresh confirmation or a calibrated confidence claim. MC/QMC/stochastic
variants share point means and are not three independent predictive wins.

## Confirmed display bug

The 074e4d7 CLI called m['coverage'].get('TOTAL'), whereas live_metrics /
empirical_coverage returns m['coverage']['markets']['TOTAL']. The complete
SHA-bound report already contains coverage. Null in the stdout summary did NOT
mean the archived intervals were missing, recalibrated or changed.

## Why the frozen files remain byte-identical

The phone registered protocol
1e8f24a665a8b34a2ca22c37e408591ae8547b12788fe70c7150079b43249317
at UTC epoch 1794926907. The plan pins 27 source files, including
challenger_review.py itself. Editing that otherwise trivial .get() would make
the already registered protocol fail its source contract.

The correction is an unpinned read-only display layer, challenger_summary.py.
No file listed by source_pins() changes; the test reconstructs the user-reported
plan metadata with public source pins and verifies the identical SHA. This is a
compatibility check, not a fabricated copy or independent signature of the
private plan. Never delete/reset/re-register the experiment to fix presentation.

The launcher --challenger-review now runs the ORIGINAL offline review in a
child and formats its saved SHA-verified report. Model math, arguments, report
bytes and child failure exit status are preserved. The legacy direct Python
challenger_review CLI remains frozen, including its defective summary field;
use the launcher or the new viewer for corrected presentation.

## Read the existing 18-game report without rerunning models

Stop the isolated poller with Ctrl+C if needed, then:

    bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh --challenger-summary

This launcher updates the existing research checkout as usual; the viewer itself
has no network, training, SQLite or Telegram activity. It selects the most
recently written challengers-*.json file, NEVER the best metric. An invalid latest
file fails closed, not back to an older favorable report. An exact report can
also be selected with the Python viewer's --report argument.

Read limits: 1024 candidate filenames, 16 MiB per report; constrained local path,
no symlink or /data access, exact filename/payload SHA and explicit read-only
research scope. No new directory is created in view mode. No report, forecast,
source archive or registered protocol is overwritten. Missing intervals remain
null with an explicit NO_SUPPORTED_TOTAL_INTERVALS or
NO_SETTLED_SUPPORTED_FORECASTS reason. Existing coverage is descriptive, not a
confidence index. Partial/blocked review exit codes remain nonzero.

## Evidence and limits

The preserved native one-game gzip report is used unchanged to regress the
real nested coverage schema. Synthetic reports cover 9/18 and 14/18 field
transfer, hashes, bounds, missing/symlink paths, first metadata preservation,
failed child execution and unchanged protocol SHA. A real subprocess plus
manufactured SQLite tests the wrapper failure path; it is not Telegram E2E.

The local Cloud environment explicitly failed to start this turn. No local
shell/test run is claimed. Changes are on the same GitHub branch; exact-head
GitHub unit/Docker/resource checks and results are recorded on PR #89.

Actual new viewer execution in private UserLAnd is not yet verified. Previous
real Telegram /compare and /accuracy replies remain distinct evidence.
Production/default model NO-GO; the 100 future-game / 20 day-cluster protocol,
input coverage and calibration requirements remain unchanged.

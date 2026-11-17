# FAZ 93.1 — Official NBA continuation pages and actionable source diagnostics

Continue PR #89 from 6b6f2a2 on the existing research branch. Scores, default
models, calibration rules, SQLite, old forecasts, main and Fly production remain
unchanged. No absence policy is relaxed and no prediction is manufactured.

## Two different findings, kept distinct

The UserLAnd review for Denver–Phoenix (401910001) showed two ESPN Out entries:
Julian Strawther and Mark Williams. The official_extraction_status was null and
warnings contained OFFICIAL_REPORT_UNAVAILABLE_OR_UNVERIFIED. This proves no
corroborated official status was available in that review; it does NOT identify
whether index/PDF access, archive I/O or extraction failed. It is not proof that
pdfplumber is missing. The old code swallowed that stage into a generic warning.

A separate real Cloud access probe successfully retrieved the official 2026/27
season index and the published 16 November 2026 08:30 PM ET PDF. These are public
sources without API keys. This does not prove the phone had successful access.

The PDF has EIGHT pages. The old coordinate fallback required column headers on
every page, while the official PDF prints them on page one only. It returned
8 early rows, and no Denver/Phoenix rows. Actual PDF text includes both players
on page five. This parser defect was independently reproduced from the captured
PDF, separate from the phone's unclassified access warning.

## Parser correction

- Continuation pages may reuse anchored columns only if the official report title
  and page geometry match the preceding anchored layout. Unverified continuation
  layouts fail closed; changed reports do not inherit old teams/games.
- Sparse game context is preserved across verified pages. A changed matchup
  without a team or a new time without a matchup cannot borrow the old game.
- Mixed table/coordinate PDFs merge unique source rows. Conflicting statuses
  between extraction methods fail closed. Existing full table reasons take
  precedence over coordinate fragments for the same status.
- A wrapped reason no longer drops an otherwise explicit player/status row.
  Coordinate reason text is labelled a fragment, not a reconstructed medical
  diagnosis. A source Out/Available is still not independent medical verification.
- The existing bounded PDF worker retains its 128 MiB address-space, four CPU
  seconds and timeout limits. The parser version is explicit V2.

The captured PDF now yields 112 source rows, including SEVEN PHX@DEN rows:
Ryan Dunn Available; Drew Timme Out; Mark Williams Out; DaRon Holmes II Out;
Ryan Nembhard Out; Julian Strawther Out; Cam Whitmore Out. These are source
observations, not seven injured players or a confirmed lineup.

ESPN and NBA now corroborate the two original Out observations in this replay.
FOUR additional NBA Out observations have no ESPN corroboration (Timme, Holmes,
Nembhard, Whitmore). The current two-source policy still blocks those minute
projections. Successful extraction is NOT reported as a successful prospective
minute archive or scoring improvement. No PPG deduction or confidence index is
introduced. Unknown projected minutes and individual defense/pace remain open.

## Diagnostics and phone command

Future reviews record the official failure stage, safe code, HTTP status when
available, parsed rows, matched fixture rows, parser version and reason scope.
Stages distinguish index fetch/discovery, PDF fetch/archive/extraction and exact
player/game matching. Raw exception bodies, cookies and secrets are not exposed.
Existing generic warnings remain available for backwards-compatible consumers.

The collector and batch report retain a bounded per-player list of missing
corroborating sources. This is a diagnostic, not an eligibility/health judgement.
Different unmapped names are not merged under a null player ID.

To inspect the stored phone review without another Python heredoc, stop the
isolated poller with Ctrl+C if running, then:

    bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh --roster-status 401910001

The launcher updates only the existing branch. The inspector itself makes NO
API requests, creates no directory, checks file hashes and rewrites nothing.
For old failed reviews it explicitly says legacy_failure_stage_unknown=true;
it cannot retroactively invent the lost HTTP failure. Missing data is reported
as ARCHIVE_UNAVAILABLE, not a successful empty roster.

New collection attempts automatically include roster_diagnostics. Do not backfill
minute inputs after tipoff, or turn later source access into an original forecast
input. After reviewing output, restart the isolated bot normally:

    bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh

## Reproducible public evidence and tests

New append-only packet:

    docs/evidence/roster-phase931-denver-native-20261117.tar.gz
    SHA-256 b86111bc6ce429c02accaf11677fa885cb14978286ffd3aac13ea965b824a84f

It contains the actual public source receipts/bytes and the ORIGINAL incomplete
V1 review, with null model/prediction linkage. V2 reprocessing is explicitly later
parser replay, not an original observation or prospective prediction. Predictions
created=0; prospective player-minute inputs created=0; real Telegram delivery=false.
No previously committed packet or forecast is changed.

The older native replay test had exact V1 partial-list expectations, which failed
when V2 correctly found later rows. It now preserves every old row unchanged AND
checks exact expanded current counts/identity sets: Orlando four official rows,
Chicago/Cleveland twelve. This tests a new interpretation of pinned source bytes;
it does not rewrite archived V1 observations. The new Denver native case separately
asserts exact seven player/status pairs, 112 extracted rows, and four remaining
corroboration blocks. Optional PDF absence is tested explicitly in the base image.

New synthetic tests cover headerless pages, wrapped statuses, geometry/title
mismatch, context boundaries, table/coordinate conflicts, HTTP 429 stage reporting,
PDF failure vs index failure, timeout redaction, missing dependency, unmatched
fixture, unmapped identities and read-only inspection/tampering. Collector/batch
propagation and real launcher dispatch are also tested. Full-suite/CI/resource
results for the exact final HEAD are recorded on PR #89.

Real UserLAnd access on the updated code and real Telegram E2E remain BLOCKED
until actual phone output is supplied. Production/default-model decision is
NO-GO: parsing coverage improved, but real player-model OOS/calibration superiority
is still unproven. No merge, deploy, secret or persistent-data deletion occurs.

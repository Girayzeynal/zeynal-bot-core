# FAZ 93.2 — Explicit fresh official PDF fallback for index HTTP 403

Continue PR #89 from a70fb6c, on its existing research branch. Existing forecasts,
SQLite, scores, source packets, main and Fly production remain unchanged.
No API key, subscription, new service or production secret is required.

## Confirmed boundary, not an invented automatic mirror

The phone received 403 from the official NBA season index, but RECEIVED from the
published 16 November 08:30 PM PDF on ak-static.cms.nba.com. Its SHA was exactly
33371df0af61078971013ad42afec57efbfdd4bcd4cad6507733523c18b38097,
matching the Cloud capture. This confirms PDF-host access, not current report
freshness, successful minute collection or real Telegram delivery.

Additional Cloud probes found no verified automatic alternative: the public
WordPress season slug query returned an empty JSON list, nba.com/injuryreport
returned 404, and the two NBA LiveData discovery endpoints returned 403 in Cloud.
Those endpoints are NOT wired as working providers. No browser challenge, proxy,
rotating identity, denied-path retry or guessed timestamp filename is introduced.

The new fallback is EXPLICIT and OPT-IN. Someone must supply a real published
official PDF URL (for example from the official page in an environment where it
is accessible). The code does not manufacture or enumerate possible filenames.
Automatic newest-report discovery is still unavailable on a device denied by
the index. This is a limited research bridge, not a claim that discovery is fixed.

## Admission and immutable records

The --roster-pdf command accepts only the existing exact HTTPS official CDN URL
pattern, with no credentials, query parameters, redirects or foreign hosts.
It rejects future reports and reports older than 30 minutes before source access.
The body must be a bounded PDF with a matching SHA. The existing bounded child
parser must expose one consistent official report title; its Eastern publication
clock must equal the timestamp in the URL, converted to UTC. Missing parser,
unverified title, changed content or conflicting records are BLOCKED.

Actual source reception and first archive timestamps remain separate from the
publisher clock. The private official-reports directory uses content-addressed
PDF/link records. Repeating a URL/body preserves its first record; a later
explicitly imported publisher correction has a different record. Same-time
conflicting content is not arbitrarily selected. No historical record is deleted.
The importer creates no forecast, player-minute projection or calibration.

## Runtime behavior

The isolated test bot and offline player-input collector consult this optional
local registry only after an actual index 403 (including its existing cooldown).
Missing, invalid, expired or unconfigured registries retain the original block.
401, 404, 429, transport failures and arbitrary parse errors do NOT silently
activate this fallback. There are no additional retries of the denied index.

The PDF is fetched from the official CDN again and must match its imported SHA.
Its body publication clock is rechecked. Index denial remains separately visible;
the display says the supplied fresh official link was used and that it is NOT
verified as the globally latest report. The cached review expires at the report's
30-minute age boundary, even if the usual five-minute source cache would last longer.
A live index remains preferred when accessible. Parseable body publication clocks
are also checked on that normal path.

All existing fixture, season, team/player identity, pre-tipoff, uncertainty and
two-source absence checks remain. Four NBA-only Out rows in the Denver replay
still fail ESPN corroboration. Import success does not imply minute collection,
model fit, scoring improvement, a calibrated probability or a confidence index.
Source selection is explicit in the review hash/witness; old forecasts are not
reclassified with later data. No current report is backfilled after a game's tipoff.

## UserLAnd — only the isolated installation

Stop the isolated poller with Ctrl+C. Given a genuinely fresh, published URL:

    bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh --roster-pdf 'ACTUAL_PUBLISHED_OFFICIAL_PDF_URL'

The placeholder is NOT a real link. Use the actual source URL, not a timestamp
guess or the old test PDF. A report's age is checked at import and every use.
Success is EXPLICIT_OFFICIAL_LINK_ARCHIVED or EXISTING_EXPLICIT_LINK, with
latest_report_verified=false and forecast_created=false. A BLOCKED result exits
nonzero and reports whether the optional pdfplumber dependency is present.
If it is absent, the existing isolated --roster-setup can install that optional
research dependency; it is not a fix for index 403 itself.

The normal --player-inputs-plan / --player-inputs-all commands may then use that
explicit record only for eligible future archived fixtures, subject to all other
checks. The bot's Kadro view can also show this clearly labelled source observation.
Restart normally when finished:

    bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh

No custom .env, pasted API token, Fly secret activation or production restart
is part of this process. Expiry requires a NEW genuinely published fresh URL;
re-importing an old report never refreshes its publication clock.

## Verification and limits

New tests cover the exact official URL, body SHA and title/clock binding; future,
stale, wrong-season, redirected or foreign input; parser failure; immutable
re-import; content revisions/ambiguity; opt-in 403-only routing; cooldown;
cache-expiry boundary; post-tipoff refusal; real launcher dispatch; and safe
nonzero CLI failures. The existing pinned eight-page public Denver PDF is replayed
with its original capture clock and an explicitly SYNTHETIC index 403 in the test.
The normal image verifies missing PDF dependency behavior; the optional image
runs the real bounded worker. These tests are not a live phone fallback test.

Exact final-head full-suite, Docker and hard 1 CPU / 256 MiB results are recorded
on PR #89. Native source bytes and old records are unchanged. There is no new real
player-model fit or OOS accuracy evidence; production/default-model GO remains
NO-GO. Actual new-mode phone/Telegram verification and automatic fresh discovery
remain open. This fallback never makes a "latest" or medical certainty claim.

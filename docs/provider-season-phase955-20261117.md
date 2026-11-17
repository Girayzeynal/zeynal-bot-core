# Phase 95.5 — provider season selection and truthful access diagnostics

Continue PR #89 / `feature/hybrid-market-roster-evidence-20261114` from `12470d3b8e1b87d0ddeb9d99e3cb56fb6c8bcc49`.

## User evidence and confirmed code issue

The user supplied live isolated-bot panel responses: The Odds API could not find the mapped league in its active catalog; API-Basketball reported both plan/subscription and season error classes at the fixture query; the official EuroCup news URL returned HTTP 429 at **17.11.2026 21:36:42 TSİ**. The pasted response did not include a fixture ID, so none is inferred. These are user-reported adapter execution/error observations, not positive market/player feed coverage or an independent private-ledger audit.

Code review found that API-Basketball requests constructed the season with `snapshot['season'].replace('/', '-')`. The European adapter did **not** use the provider's own declared season list. Thus a wrong season format had not been excluded before the UI asserted a plan restriction. This is a real code/diagnostic gap; **it is not proof that formatting caused the user's specific provider rejection**. Their private native catalog/error receipts are not available in Cloud.

## Fix

- European requests now use `provider_seasons.select_season` on the exact matched league's native `seasons` catalog. An explicit dual-year value is returned literally. A numeric year label is eligible only when explicit provider start/end dates bind it to the requested two-year season and fixture date.
- Missing, malformed, oversized, ambiguous or incompatible lists fail closed before `/games`. There is no fallback to an old season just because the subscription might allow it. No team or date relaxation.
- Source season selections retain a content-addressed catalog pin, declared available values, requested model season and the exact query value. Real plan/season rejections retain this evidence and the existing per-season cooldown.
- NBA keeps its existing query-season behavior. No score, model, covariance, distribution, prepared-model pin, SQLite record or challenger-protocol file changes.
- The UI no longer turns an unverified mixed plan/season error into a definite subscription diagnosis. If the catalog-selected value is proven, it says so separately; the provider may still reject access. No subscription or key deployment is performed.
- An absent The Odds API mapping now includes the expected sport key and safe active basketball keys from the native catalog. This means **the expected active key was not found**, not that every provider/account can never offer that competition. A malformed catalog is classified as schema failure rather than coverage absence.
- The isolated `--europe-data-check` JSON now includes only whitelisted season/catalog/error-code diagnostics, without raw provider error text or credential values.

## Tests and remaining blockers

Thirteen new regressions cover exact/numeric season values, source date bounds, no historical-season workaround, missing/ambiguous lists, query values and source pins, real-plan-denial caching, active odds catalog metadata and schema errors. Existing European synthetic provider fixtures now declare their season metadata. The previous cached-denial rendering test still checks preserved cooldown/source clocks, and now expects an appropriately qualified cause description rather than an unproven definite plan diagnosis. No tests were removed or disabled.

Focused local validation: **75 passed**, zero failures/errors. Full local regression: **1,410 passed**, zero failures/errors, 106.269 s. Exact-head CI/Docker/resource results are reported separately on PR #89 after completion.

This patch does **not** establish real authenticated European access or fix the official website's HTTP 429. The user's test-bot responses remain the real execution evidence. A fresh provider catalog/fixture check on an actual future archived fixture is required to decide whether the remaining barrier is catalog/season support, account permissions or provider matching. Future-key changes, upgrading subscriptions, activating staged Fly secrets or changing production are not authorized by this diagnostic fix and were not performed.

## UserLAnd

Stop only the isolated test bot with Ctrl+C. To update and run the safe existing diagnostic, use an actual archived fixture ID:

```bash
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh --europe-data-check EUROCUP U2026_<actual_code>
```

The report should show `provider_details.API_BASKETBALL.season_selection` and the actual requested provider season, or an explicit missing/ambiguous/unlisted status. The Odds API details show the expected key and available active basketball keys when coverage was not found. After tipoff no new current source check is performed; select a genuinely future archived fixture instead of retiming an old prediction.

Restart the isolated bot normally afterward:

```bash
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh
```

No model re-preparation is needed for this source-adapter fix. Real Telegram E2E of this follow-up is pending. **NO-GO for production promotion.** No main merge, Fly.io deployment, secret changes or historical archive edits.

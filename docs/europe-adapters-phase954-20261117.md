# Phase 95.4 — connect European current-source adapters

Branch/PR unchanged: `feature/hybrid-market-roster-evidence-20261114`, PR #89. Starting UI head `574c6a2854e365d1529abe8ccd9f7aea3926ce51`; public-source inspection commit `a3f5fa498a69ea9f815206b87f1a2d628ebde650`.

## What is connected

The European Piyasa and Kadro/Sakatlık buttons now invoke a bound `EuropeanDataReview` service. It verifies the original archived forecast SHA, fixture/team IDs, generated time, model version, source cutoff and stored sample hash. New observations are archived separately under `europe-data`/provider evidence; they never enter the original forecast, model training or live performance metrics.

**Markets:** reuse the existing private, quota-limited `ProviderAccess` and `ProviderBridge` passed to the isolated bot. EuroLeague was already mapped but not connected to the European panels; EuroCup now has a catalog-gated sports mapping. An active matching sport must actually be present in The Odds API catalog before any events/odds URL is called. API-Basketball uses existing exact league, season, team and UTC fixture cross-checks; its fixture/statistics response is not injury/lineup evidence.

Only an exact European event pair and start are accepted. The NBA +600-second association is not applied to European games. Sponsor/name differences that cannot be verified remain an explicit matching block, not a fuzzy merge. Missing credentials, unavailable league coverage, subscription/season errors, quotas, stale prices and service failures stay visible.

When native quotes are admissible, original Bayesian/QMC parameters/cuts are read from the forecast's SHA-bound assets in a temporary workspace and the deterministic samples must reproduce the stored SHA and point projection exactly. This is an original-distribution replay, not a new prediction or fit. Existing native-price admission/current-market review logic supplies raw per-line probabilities, actual odds and settlement/calibration warnings. EV/edge is withheld when settlement/OT scope or calibration evidence is insufficient. Later quotes retain their actual clocks and are explicitly separate from original forecast inputs.

**Roster/injury source:** a bounded official website adapter discovers injury-report links and timestamped structured article text. It validates official origins, body hashes, source clocks, publication age and relevant team text. It can display actual official news quotations; **it does not manufacture structured OUT/AVAILABLE player records, player IDs, confirmed lineups, suspensions, minutes or medical verification from prose**. Existing trusted fixture/time-bound roster packets remain visible as the original prediction evidence. No hypothetical API-Basketball injury endpoint was invented.

Current review requests have bounded deadlines, per-provider quotas/caches and shared-domain 403/429 cooldown. Repeat clicks use the same observation for 120 seconds; paging does not fetch again. Source/callback failures preserve the original analysis with an explanatory code. Once tipoff is reached, no new current API/news request or retrospective PREMATCH observation is made; any earlier cached observation is shown as archive data.

NBA's existing source and callback routes are retained. European source/model engine files and the 27-file challenger protocol are unchanged; no model re-preparation is required solely for this adapter patch.

## Actual official-source access result — BLOCKED

The separate anonymous public-source audit ran on GitHub:
[run 44143828751](https://github.com/Girayzeynal/zeynal-bot-core/actions/runs/44143828751), source job 134253440821.

At 2026-11-17 18:04 UTC all four attempted official EuroLeague/EuroCup pages returned **HTTP 429**. See `docs/evidence/europe-source-access-phase954-20261117.json`. No HTML/player body was retrieved, so no real player status or native article schema is claimed validated. A subsequent code change adds shared-origin cooldown so the first 403/429 prevents further automatic page requests during the wait period.

The diagnostic job's successful completion means the access attempt was recorded, **not that an injury feed worked**. It runs only on explicitly tagged research pushes, not on every regression test or Telegram request. It uses no API keys, Fly credentials or production resources.

Actual authenticated European market coverage is also not proven in this Cloud session: the runtime is unavailable and the private UserLAnd provider keys were not requested or copied. The connected adapters must report the actual account/catalog/fixture result when run in the existing isolated process. Live official player records remain **BLOCKED by source access**; source news observations are not a replacement for independently verified player availability.

## Tests and limitations

New tests cover both European league quote pipelines, native sample replay, correct source clocks, exact fixture/name matching, refusal of NBA-specific clock offsets, catalog absence, missing keys, caching, post-tipoff refusal, 429 cooldown, source hashes, news-vs-player-data separation, callback binding, timeouts and immutable forecasts. Existing European callback tests use an explicit synthetic official-source getter so CI remains hermetic. The existing launcher test exercises the new diagnostic mode without credentials. Full exact-head CI/Docker/resource results are reported on PR #89; no local run is claimed because Cloud failed to start.

## UserLAnd

Stop only the isolated test bot with Ctrl+C, then restart:

```bash
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh
```

For a genuinely future archived fixture, press Piyasa and Kadro/Sakatlık. A completed game's empty current panel must not be bypassed using a new historical prediction. Use verified `/euroleague YYYY-MM-DD` or `/eurocup YYYY-MM-DD` fixtures, generate/save a legitimate new forecast before tipoff, then inspect the panels.

A safe terminal diagnostic is available after stopping the isolated bot:

```bash
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh --europe-data-check EUROLEAGUE E2026_<actual_game_code>
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh --europe-data-check EUROCUP U2026_<actual_game_code>
```

Replace placeholders with an actual archived fixture ID. The command reads an existing forecast and reports provider/source states without printing keys, creating predictions or changing production. After-tipoff records correctly return `POST_TIPOFF_NO_CURRENT_BACKFILL`. If The Odds API does not list EuroCup for this account, that market coverage remains unavailable. No subscription or secret deployment is performed.

**Actual Telegram E2E of these new adapters is pending. NO-GO for production promotion.** Existing raw probabilities remain NOT_CALIBRATED. No main merge, Fly.io deployment, database reset, snapshot deletion or paid subscription.

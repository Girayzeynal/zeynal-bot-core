# Isolated provider integration: phase 92.2

The existing Fly secret names (`API_SPORTS_KEY` and `ODDS_API_KEY`) are valid.
Their presence on Fly does not provide credentials to UserLAnd or Cloud. The
reported `API_SPORTS_KEY` is staged; no secret deployment was performed.

## Confirmed code causes

1. `hybrid_engine.test_bot.main` clears the legacy `API_SPORTS_KEY` before
   constructing the production application's bootstrap. Previously no separate
   credential capture existed for research data access.
2. The hybrid `/analyze` route returns before the legacy Faz17 market path in
   `main.py`. Merely constructing Faz17 did not connect it to hybrid analysis.
3. The isolated market panel previously read ESPN receipts/manual evidence only.
4. Keys, source verification, settlement compatibility, and calibrated model
   probabilities are separate requirements. Adding an API cannot prove an edge.

## Implemented behavior

- Capture dedicated data credentials before blanking the legacy bootstrap key;
  keep production bootstrap and scheduler isolation intact.
- Optional private file `~/.zeynal-test-providers.env`: literal `NAME=value`
  allowlist, owner-only mode, same owner, no symlink, maximum 8 KiB, no shell
  evaluation. Existing process environment is also supported. No automatic Fly
  secret export, generic `.env` loading, or Telegram token access.
- Supported aliases: `ODDS_API_KEY` / `THE_ODDS_API_KEY`, and
  `API_SPORTS_KEY` / `API_BASKETBALL_KEY`. Conflicting aliases stop startup with a
  fixed diagnostic and no values.
- Fixed HTTPS origins; authentication headers; no API key in a URL. Redirects
  are refused. HTTP errors, exception strings, and response bodies cannot expose
  a credential in diagnostics. Secret-echoing successful responses are refused.
- The Odds API: check active sport catalog; exact home/away/start-time match;
  request event-specific decimal `h2h`, `spreads`, and `totals` in one region.
  Real bookmaker IDs and published timestamps are retained; stale/future prices,
  incomplete opposing sides and mismatched handicaps are refused.
- Alternative totals/spreads, team totals and quarter/half totals are supported
  by the parser. Requests for those extra markets require the local setting
  `ZEYNAL_TEST_ODDS_EXTENDED=1`, because more markets may consume more credits.
  A response is not a guarantee of every market or bookmaker's coverage.
- API-Basketball: discover the exact league ID, cross-check the exact fixture and
  unstarted status, and capture home/away season statistics only after verifying
  the returned fixture's season. Those aggregates are labeled current extra
  observations, not retroactive model inputs, measured pace, injuries or lineups.
- Positive cache preserves original receipt bytes/identity and observation time.
  Per-provider failure cooldown; quota-zero refusal; 24 requests/provider/process/
  UTC-day local budget, maximum 12 cached documents of 2 MiB each. Local budgets
  reset on process restart; provider quota headers remain authoritative. Three
  seconds per request and a shared 12-second collection deadline; no automatic
  retries. API errors leave the original score visible.
- Current retrieval receipts and review manifests are hash-pinned, append-only
  files under the isolated data directory's `provider-evidence`. Existing
  prediction ledgers/assets are not updated. Completed games make no provider
  requests and receive no current-data historical backfill.
  Provider evidence storage is capped at 256 files / 32 MiB; a full evidence
  budget stops this additional provider panel without deleting old records.
- NBA `/analyze` has a provider panel in the existing Piyasa button, with source
  availability, auth/plan/quota/identity errors, observed lines and raw coherent
  regulation probabilities. No settlement rules, EV, confidence percentage or
  calibration are invented. A source acquired after an archived prediction is
  explicitly labeled as later evidence, never as information available at issue.
- The current source panel says missing/unverified data is not `NO EDGE`. The
  existing sealed decision evaluator still reserves `NO_EDGE` for an actual
  comparable EV calculation; its policy and implementation remain unchanged.

## Safe UserLAnd operation

The canonical launcher remains:

```bash
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh
```

Once this branch update is present, credentials can be checked without starting
or stopping Telegram, changing Git, deploying secrets, or printing key values:

```bash
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh --provider-check
```

This queries only the provider sport catalog/account-status endpoints if a key
is locally configured. It does not copy Fly secrets. Configure credentials
privately in UserLAnd's dedicated file or process environment; do not send values
to chat or commit them. No new plan, paid subscription or production restart is
part of this change.

## Verification and remaining limits

Tests exercise synthetic provider responses and an actual PTB application over
local HTTP with exact frozen Philadelphia samples. This is not real Telegram or
real authenticated provider E2E. Full suite/CI results are recorded in the PR.

Local full regression: **977 passed, 0 failures/errors**, retaining the previous
942 tests and adding 35 provider/Telegram integration checks. Provider-only probe:
35 passed, peak RSS 90.82 MiB; the Cloud host has 8 GiB/2 CPUs and therefore this
local run does **not** certify a 256 MiB cgroup. CI adds a separate provider + PTB
probe with an enforced 256 MiB/1 CPU container; only its completed results count
as hard-limit evidence.

Cloud has neither provider key: real authentication, remaining quota and account
coverage are BLOCKED. Actual new-head Telegram delivery is also BLOCKED. Existing
UserLAnd-delivered prior-version commands are not proof of the new integration.

NBA is the wired Telegram path in this increment. EuroLeague provider mappings
are conservative but live EuroLeague wiring/coverage is not claimed. SportsDataIO
and balldontlie are not newly connected; their plan, schema and PIT behavior need
their own validation. The existing balldontlie script expects `BDL_API_KEY`, unlike
the user's Fly name `BALLDONTLIE_API_KEY`; no production configuration is changed.

No calibrated player/pace adjustment, refit, model promotion, OOS improvement,
new confidence index, verified bookmaker settlement rule, or OT simulation is
claimed. Production promotion remains NO-GO pending those independent gates and
real-provider/test-bot validation.

## Provider references

- [The Odds API v4](https://the-odds-api.com/liveapi/guides/v4/): header
  authentication, event listing, event odds, quota headers and market costs.
- [API-Basketball documentation](https://www.api-basketball.com/documentation):
  basketball league, game and statistics endpoints. Endpoint reachability is
  not a substitute for account-specific authentication and schema verification.

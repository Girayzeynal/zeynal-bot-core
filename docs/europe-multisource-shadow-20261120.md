# Public EuroLeague injury-source adapter integration — 20 Nov 2026

## Source scope and security

The current isolated Telegram test bot has five **bounded index-observation**
adapters on a verified future EuroLeague `Kadro / Sakatlık` button:

1. Basketball Sphere's public EuroLeague injury index
2. Eurohoops EuroLeague news index
3. Basketlogy's public EuroLeague injury report index
4–5. Both teams' **exactly named** official news indexes from the existing
2026/27 official 82-club manifest (when names can be bound unambiguously).

The existing official EuroLeague injury/news index (with 403/429 handling)
and native EuroLeague season player directory remain separate. The club
directory is a URL manifest, **not** proof of injury status. No generic
team-name fuzzy matching is permitted.

Each newly added public-source request is HTTPS-only, redirects disabled,
strict robots.txt allow required before any HTML, 256KiB maximum HTML,
32KiB robots cap, response MIME checked, short read/connect timeouts and
a 15-minute shared observation cache. No login, anti-bot bypass, paid API,
RotoWire credential or bulk HTML storage. Social media / X is NOT queried:
an authorized API and account scope would be needed. Editorial page
metadata and body SHA (not full copyrighted page text) are cached in
memory and the current provider review as non-model evidence.

The current-public source adapter intentionally captures **source index
availability**: timestamp of receipt, HTTP status, title and body hash.
It does **not** claim a player's participation/absence in a specific
future fixture, nor an original publication timestamp. Multiple editorial
pages do not independently verify player injury if sourced from the same
club release.

## Android test-process activation

The existing single-poller launcher exports:
`ZEYNAL_PUBLIC_EURO_NEWS_ENABLED=1` by default, unless explicitly set
to `0`. On the UserLAnd process, restart the existing isolated bot
using the normal launcher and inspect a future real EuroLeague
`Kadro / Sakatlık` button; the command `/features` reports individual
source HTTP/robots states after that review.

No new credential required. No automatic dashboard source fetch occurs
in `/features`. The initial /features status may be NOT_QUERIED.
The official EuroLeague index may still return HTTP 403/429; the new
public sources cannot override those errors or substitute for official
fixture eligibility.

## Telegram evidence

`tests/test_europe_public_telegram.py` drives the real
`python-telegram-bot` command/callback handlers and the existing
six-button premium UI using an **offline synthetic Telegram Bot API
double**. The upstream reviewer is not mocked: official source 429,
native roster unavailable and three editorial sites' robots+HTML
receipts are injected deterministically. The new source panel is
rendered and immutable forecast files verified. This is an integration
test, NOT a live message delivered to the user's Telegram account.
Live UserLAnd delivery and process release SHA must be verified
separately, and cannot be claimed from CI.

## Simulation / measurement

The already existing `compare_verified_rotation` is the
player-trained posterior + 10,000 RQMC-Halton baseline/adjusted
rotation comparator. The new CLI:

```bash
python -m hybrid_engine.europe_multi_source_simulation_measure --output /tmp/ze-synthetic-qmc-measure.json
```

runs NBA, EuroLeague and EuroCup on explicitly synthetic
historical/fixture/injury ID/usage data and measures the baseline
and adjusted projected totals against an artificial final score.
CI attaches the JSON result as `europe-multisource-synthetic-qmc`.
A numerical difference is an *engineering test*, not a validated
betting improvement, injury effect calibration or real MAE.

**Real-world injury-adjusted score MAE/RMSE cannot yet be computed**:
there is no independently verified first-captured match-specific
official player status with full pregame minute projections and a
trained historical player-exposure cohort in these data. Existing
live forecasts are immutable and must not receive retrospective
injury claims. The safe outcome remains NOT_CALIBRATED/ABSTAIN,
rather than a made-up point impact or percentage.

## Release gate

Run offline adapter and Telegram callback tests, perform 3 x 10k
QMC comparisons, then full Python/Docker CI. Merge to isolated
test branch only after passing. Real Telegram checks require
the running UserLAnd test-bot credentials and process restart.
Do not confuse a GitHub merge with live Telegram or Fly.io deployment.
No original archive, volume, model, production bot or secret mutation.

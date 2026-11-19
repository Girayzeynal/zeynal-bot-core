# ZEYNAL BOT CORE — Official club sources, 2026/27 pilot

Parent task: #96. **This is an isolated source-discovery experiment, not a production/Telegram feature or a new forecasting model.** It does not alter existing first-published NBA, EuroLeague, EuroCup forecasts, final scores, settlement, calibration, or the Fly.io volume.

## Six publicly verified club news sources

| League | Pilot club | Official news page | Native team identity |
|---|---|---|---|
| NBA | Denver Nuggets | https://www.nba.com/nuggets/news | NBA 1610612743 |
| NBA | Boston Celtics | https://www.nba.com/celtics/news | NBA 1610612738 |
| EuroLeague | Olympiacos Piraeus | https://www.olympiacosbc.gr/en/news/announcements/ | UNBOUND until native league ID verified |
| EuroLeague | Žalgiris Kaunas | https://zalgiris.lt/naujienos | UNBOUND until native league ID verified |
| EuroCup | TOFAŞ Bursa | https://tofasspor.com/haberler | UNBOUND until native league ID verified |
| EuroCup | Cedevita Olimpija Ljubljana | https://cedevita.olimpija.com/en/news/ | UNBOUND until native league ID verified |

Registry: \`hybrid_engine/official_club_sources.json\`. The source registry is **not** a claim of rights to automated crawling. Official 2026/27 league memberships are audited separately from URLs and must be associated with native team IDs before any fixture-level observation. The sites have different content structures, languages and publication-time metadata.

## Working commands on isolated test checkout

Dry-run / zero network (safe default):

\`\`\`bash
PYTHONPATH="$PWD" python -B -m hybrid_engine.official_club_pilot
\`\`\`

Explicitly opt in to one club's public news index and robots.txt (at most two same-origin network requests; redirects refused; no HTML stored):

\`\`\`bash
PYTHONPATH="$PWD" python -B -m hybrid_engine.official_club_pilot --live --club eurocup_tofas
\`\`\`

Optional, metadata-only immutable receipt under \`~/zeynal-test-isolated/data/club-pilot-evidence\`, **not** the existing prediction/result ledger:

\`\`\`bash
PYTHONPATH="$PWD" python -B -m hybrid_engine.official_club_pilot --live --club eurocup_tofas --save
\`\`\`

Each live probe reports access status, HTTP status (if available), observed time, body SHA256, HTML page title, publication-time verification status. It **does not** extract player roster statuses, market odds, or parse JS, and never asserts that a missing news item means an active player. It is not automatically scheduled and does not send Telegram messages.

Robots.txt: 403/429/timeout/uncertain policy blocks the page; explicit 404/410 policy absence is handled as no robots file. No follow-redirect, no alternate third-party domain/redirect, no proxy/source bypass, one public listing per club, 512 KiB max HTML and five-second timeout per request, serial calls only. Sites' contractual terms/licensing may impose additional restrictions; use must still comply.

## Critical example and prospective-proof barrier

TOFAŞ official 17.11.2026 match preview:
https://www.tofasspor.com/haber-3715-tofas_eurocupta_chemnitz_deplasmaninda

The club states that **Yiğitcan Saybir** and **Efe Postel** would be unavailable against NINERS Chemnitz on 18.11.2026. That article is a strong illustration of why club sites matter; it is **not an automatically verified model input**. The public page as seen provides a **date**, not a timezone-aware precise publication hour; verifying an exact pregame timestamp is essential before comparing with a frozen prediction, and the claim needs a team/player ID + fixture ID binding. This pilot does not retrospectively modify an archived prediction.

Other first-party examples: Denver's official 18 Nov Nuggets–Celtics preview including injury report (https://www.nba.com/nuggets/news/nuggets-look-to-bounce-back-against-celtics); Žalgiris official injury update (https://zalgiris.lt/en/naujienos/injury-update-on-williams-goss-and-tubelis).

## Remaining work (not done, must pass before promoting)

1. Test actual HTTP access on the UserLAnd device in opt-in mode (robots/403/429/MIME/canonical URL), record statuses without secrets. Site access via ChatGPT's browsing is *not* proof of Python bot access.
2. Verify current league participant IDs for all teams in the official 2026/27 registry. The manifest covers only six pilots, not all ~82 league entries.
3. Site-specific article discovery and parsers, explicit article-level timezone-aware publication time and first-observed receipt; claim extraction with player roster ID and unambiguous absence/return status; match-specific scope, conflict detection and source freshness policy. Handle multiple languages and unknowns.
4. At 45 minutes before tipoff, collect a separate new observation without rewriting an earlier forecast. Create a separately versioned prospective model with player effects only after evidence and calibration gates, then compare outcomes with the frozen baseline.
5. Add bounded opt-in scheduling, team/site coverage counters, Telegram diagnostic UI, provider license and source quality metrics. Confirm E2E on actual Telegram test bot before any release.

No production merge, Fly deploy, new secret, paid subscription, automatic forecast promotion, or overwrite of immutable archives.


## 19 Nov 2026 — NBA real-device permalink discovery and read-only adapter

Real UserLAnd result from `--live --summary --club nba_denver_nuggets --diagnose-links`: Denver official index HTTP 200; Next.js JSON has **28 `permalink` fields**, **15 official same-team URL candidates**, but HTML anchor article count was zero. Source post record fields include `id, permalink, slug, status, date, timestamp, category`. News dates include April, October and November 2026; these are not all current games.

PR #97 now includes `hybrid_engine/official_club_nba_posts.py`: bounded, zero-extra-request `__NEXT_DATA__` native post discovery. Only explicit native `status=publish` objects with `id`, valid slug and strict official same-team permalink are accepted as URL *candidates*. At most 24 links; blocks cross-team/other-host, querystring, unlisted paths, known Celtics Insiders landing. Sorts by consistent **unverified** `date`/`timestamp` metadata. Never treats those as proven pregame publication time. No automated article download.

The original `official_club_sources.probe()` merges anchored articles and native NBA post candidates. The explicit one-article `official_club_article_probe` now also accepts an index-pinned native NBA link after robots checking; still at most three controlled network requests. It never claims native player ID, match fixture, verified injury, forecast input or historical eligibility.

New Android UserLAnd check after branch fetch:

```bash
PYTHONPATH="$PWD" OPENBLAS_NUM_THREADS=1 ~/zeynal-hybrid-844/.venv/bin/python -B -m hybrid_engine.official_club_pilot --live --summary --club nba_denver_nuggets
```

Optional explicit single official article check only after index/robots approval:

```bash
PYTHONPATH="$PWD" OPENBLAS_NUM_THREADS=1 ~/zeynal-hybrid-844/.venv/bin/python -B -m hybrid_engine.official_club_pilot --live --summary --club nba_denver_nuggets --article-url https://www.nba.com/nuggets/news/nuggets-conclude-road-trip-pelicans
```

GitHub Actions run `44461994839`, commit `253a557643ff82b3d0fe810ae511a1d0af5bc030`: **66 offline tests passed**. New integrated NBA candidate discovery has not yet been verified via Android UserLAnd. Historical forecasts/archive, Telegram, Fly.io, secrets and production remain untouched.

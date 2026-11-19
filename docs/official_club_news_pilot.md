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


## 19 Nov 2026 — Native NBA live E2E, player status candidates, and prospective-only receipt / as-of gate

**Actual Android UserLAnd live findings supplied by user:** Denver NBA official news `HTTP 200`, **15** same-team article URLs, Boston news `HTTP 200`, **19** candidates. Separately Denver article `https://www.nba.com/nuggets/news/nuggets-conclude-road-trip-pelicans` returned `HTTP 200` with `status=OFFICIAL_ARTICLE_OBSERVED_NOT_ROSTER_VERIFIED`; robots -> pinned current index -> article flow completed. The earlier `article_candidate_count=0` on a successful single-article summary was a display bug, fixed in PR #97.

**New source-text parser (only Denver, opt-in):** `hybrid_engine/official_club_nba_claims.py` recognizes the official `INJURY REPORT` / `Denver:` section. Keeps explicit statuses `OUT`, `DOUBTFUL`, `QUESTIONABLE`, `PROBABLE`, `AVAILABLE` as source-text candidates; does not turn all absence into injuries. **G League on-assignment/two-way == NON_INJURY_G_LEAGUE**, whereas `Left Knee Sprain` is `INJURY_REASON_REPORTED`. Stops at opponent section such as `New Orleans:`. Extracted players receive no native player ID and are not allowed into any existing model, ledger or historical forecast. Public example: Denver official 14 Nov 2026 Pelicans preview listed DaRon Holmes II, Ryan Nembhard and Cam Whitmore as G League-related OUT, Julian Strawther as OUT for knee injury. The full live parser result on Android is still **unverified**; tests use synthetic text shaped on that article.

**Prospective-only first capture option:** `hybrid_engine/official_club_capture.py` creates an immutable *article version* metadata receipt in only `~/zeynal-test-isolated/data/club-pilot-evidence`. It stores the source URL, raw article SHA256, initial actual fetch time and first disk capture time, plus a payload SHA256. No copyrighted text, player names, document rewrites or production input. On later re-observation of the **same URL+body hash**, the earliest original receipt is reused. A changed page gets a separate new version receipt. This is local audit evidence, not an independent timestamp authority.

Only when opting in to capture a **future actual pregame observation**, use:

```bash
PYTHONPATH="$PWD" OPENBLAS_NUM_THREADS=1 ~/zeynal-hybrid-844/.venv/bin/python -B -m hybrid_engine.official_club_pilot --live --summary --club nba_denver_nuggets --article-url <EXACT_CURRENT_INDEXED_NBA_NEWS_URL> --save-article
```

Do not run `--save-article` on a postgame source to claim a pregame observation. A first capture on 19 Nov of an article dated 14 Nov can **never** be retrospectively credited to the frozen 14 Nov forecast. No scheduler, auto-crawl, article batch fetching or model use is introduced. `--save` still means a different, index-only receipt.

**Review screen:** `hybrid_engine/official_club_prematch_gate.py` compares a captured article with the *existing pinned* first-issued forecast (`fixture_id`, NBA/EuroLeague/EuroCup league, 2026/27 season, home/away `provider_id`, `fixture_start_utc`, `prediction_generated_at_utc`, `created_at_utc`, snapshot SHA), the source club team native ID, a separately supplied fixture/player native identity binding and a validated capture receipt. Requires article HTTP200, exact timezone-aware publication clock, consistent first capture before forecast issuance and tipoff, match/team/person agreement and a nonstale 72h injury OUT claim. G League assignment or QUESTIONABLE cannot become physical-injury OUT. Without all inputs: `ABSTAIN` and explicit reasons. **Even on a complete schema pass: `SHADOW_REVIEW_ONLY`, `model_input=false`, `historical_forecast_modified=false`.** This does not independently authenticate a partner's player identity; those documents, genuine pre-tipoff data availability, and resulting separate calibrated model still need verification.

GitHub Actions run **44464837275**, commit **d0b33f80d410ee6909d9bc612c6d14416c811422**: **95 offline tests passed** (`0.39s`), Python 3.11; this does **not** demonstrate new real-device NBA parser outputs, native identity matching or Telegram E2E. PR #97 remains DRAFT. No changes to Fly volume, production bots, immutable frozen ledger, or scores.


## 19 Nov 2026 — Real NBA injury extraction validated; NBA.com/ESPN ID namespace safeguard

**Android UserLAnd live article evidence**: Denver official November 14 Pelicans preview read HTTP200; body SHA256 `2f4340e7d365e80eac924ade4b8c33d8ac2c4c064d9583f62d89a6bfe8c70c61`; 237016 bytes and 3978 visible text characters. Native index post ID `1070083`, raw timestamp `2026-11-14T17:34:07Z` and epoch milliseconds `1794677647000`; index clock self-consistent but first-publication clock **not independently verified**.

Live text-only NBA injury report candidates: DaRon Holmes II OUT / G League Assignment; Ryan Nembhard OUT / G League Two-Way Assignment; Julian Strawther OUT / Left Knee Sprain; Cam Whitmore OUT / G League Two-Way Assignment. These four are source report text candidates only. `fixture_verified=false`, `player_status_verified=false`, `publication_time_status=NO_VERIFIED_PUBLICATION_TIME`, `model_input=false`. Observed on November 19, cannot be backdated to a 14 November prediction.

**High-severity research integration risk found**: `official_club_sources.json` uses NBA.com official team ID e.g. Denver `1610612743`, whereas the project's canonical NBA `season_archive_inventory` / `universal_analysis` fixture source is **ESPN** with different numeric IDs. Direct equality of these namespaces would cause wrong ID joins or false rejections.

`hybrid_engine/official_club_team_crosswalk.py` now refuses NBA.com-to-ESPN ID comparison without a separately pinned, season-scoped `SEASON_PARTICIPANTS_V1` snapshot from the existing participant provider. It uses exact source official club name and the as-of `ingested_at_utc` cutoff, with no guessed or fuzzy crosswalk. `official_club_prematch_gate.py` requires this bridge for NBA, or reports `NBA_OFFICIAL_TO_ESPN_TEAM_CROSSWALK_UNVERIFIED` and ABSTAINS. Fixture and player IDs remain separately required and never inferred.

`hybrid_engine/official_club_identity_pilot.py` is a new opt-in, read-only field probe, separate from the existing club-news CLI. It requests *at most* the two fixed ESPN 2026/27 season membership and names JSON sources plus robots.txt (max 4 requests total, no 30-team fallback, no redirects, 5-second timeout/request, 512KiB/source, no on-disk source text). Source permissions, original IDs, exact-name uniqueness and season are enforced. It returns a **candidate bridge**, not a verified roster/game or historical forecast input. Explicit 403/429/robots denial, changed API schema or incomplete source -> ABSTAIN; do not bypass.

Standalone opt-in UserLAnd test after fetching current PR #97 HEAD:

```bash
PYTHONPATH="$PWD" OPENBLAS_NUM_THREADS=1 ~/zeynal-hybrid-844/.venv/bin/python -B -m hybrid_engine.official_club_identity_pilot --live --club nba_denver_nuggets
```

Successful output should say `READ_ONLY_TEAM_CROSSWALK_CANDIDATE` with `nba_com_team_id`, `espn_team_id`, verified source snapshot hash and the observation UTC. If blocked/unavailable, `ABSTAIN` is a valid secure outcome. This command does not need the earlier NBA article probe re-run. `--live` absent => zero HTTP dry-run.

**CI:** run `44468521840`, commit `9a3df3a1e0f67a4d3c1fdafc16babba84ff20db4`, Python 3.11, **112 offline tests passed**. The new 2-ESPN-source field probe has NOT yet been tested over the Android network; only prior real club article and injury text tests are confirmed.

PR #97 remains DRAFT / no Fly, no Telegram production, no old frozen snapshots, no settlement or model changes. Next missing step: player provider IDs and exact fixture binding using independent, as-of pinned sources, followed by pre-tipoff shadow tests.


## 19 Nov 2026 — ESPN robots stage ABSTAIN on real UserLAnd; do not bypass

Actual device result from `python -B -m hybrid_engine.official_club_identity_pilot --live --club nba_denver_nuggets`: `status=ABSTAIN`, `reason=ESPN_ROBOTS_UNAVAILABLE_OR_REFUSED`, `requests=1`, `model_input=false`, `production_changed=false`. No provider participant JSON request was made, and no NBA.com↔ESPN ID crosswalk was established. Old CLI did NOT expose which transport failure caused the refusal: 403, 429, redirects, MIME mismatch, network timeout, and other uncertainty must not be invented as observed facts.

New branch adds fields `failed_stage`, `failed_source_role`, `failed_source_host`, `robots_transport_status`, `robots_http_status` and `robots_decision` for any subsequent explicit `--live` attempt. It still refuses uncertain/disallowed robots policy; NO automatic repeated attempts, redirects, proxy or alternate domain bypass.

**Preferred next step: ZERO NETWORK**. Existing saved season participant JSON could be used only if it was genuinely captured and independently pinned before the relevant forecast. No assumption that such a file exists. CLI `--scan-local` searches only `~/zeynal-test-isolated/data` with bounded traversal and returns file paths and claimed metadata as `UNTRUSTED_SNAPSHOT_CANDIDATE_NOT_ASOF_PROOF`. It never reads NBA/ESPN over HTTP or modifies ledgers.

```bash
cd ~/zeynal-club-pilot-97 || exit 1
test -z "$(git status --porcelain)" || { echo 'Local modifications: stop'; exit 1; }
git fetch -q origin feature/official-club-news-pilot-20261119 && git checkout --detach -q FETCH_HEAD || exit 1
PYTHONPATH="$PWD" OPENBLAS_NUM_THREADS=1 ~/zeynal-hybrid-844/.venv/bin/python -B -m hybrid_engine.official_club_identity_pilot --scan-local --club nba_denver_nuggets
```

Result `NO_LOCAL_SEASON_SNAPSHOT_IN_BOUNDED_SCAN` means the bounded isolated JSON scan found no candidate; it does not establish that the user has no ESPN data in SQLite, another directory or another machine. A found snapshot also cannot be trusted because its own hash repeats within its own file.

Optional explicit offline validation exists only for a user-selected local snapshot path with a **separately pinned pre-existing SHA** and explicit UTC as-of cutoff: `--offline-snapshot <file.json> --trusted-sha256 <independently-recorded-hash> --asof-utc <unix-second> --club nba_denver_nuggets`. This mode sends 0 network requests and cannot backfill after-cutoff observations into earlier forecasts. Neither offline path verifies fixture/player IDs or authorizes model input.

CI run `44469785390`, job `135376159941`: **121 offline tests passed** on Python 3.11, commit `0660a13f053570e577dafdc9b5d5e84d5eb4ea3e`. Actual local snapshot scan result from the Android device is not yet known. PR #97 still DRAFT; no production, Telegram, Fly volume or immutable forecast/archive changes.


## 19 Nov 2026 — Android offline JSON inventory reached 500-file cap, not a negative evidence result

Actual UserLAnd report: `--scan-local --club nba_denver_nuggets` yielded `candidate_files=[]`, `scanned_json_files=500`, `scan_capped=true`, `requests=0`, `model_input=false`, `production_changed=false`; old code displayed `NO_LOCAL_SEASON_SNAPSHOT_IN_BOUNDED_SCAN`. This is **incomplete**, not proof no 2026/27 NBA source is archived. It was also blind to SQLite files such as `~/zeynal-test-isolated/data/live-nba/nba-hybrid.sqlite`.

New source inventory `hybrid_engine/official_club_local_inventory.py`: bounded no-network metadata walk (20,000 file names / 4,000 dirs / depth 6), source-identity filename-prioritized JSON inspection (up to 3,000 reads and 32 MiB), and **read-only SQLite immutable schema-only** introspection of up to 16 local `.sqlite/.sqlite3/.db` databases. No SELECT from table rows, database writes, remote HTTP, source payload export, model input, or production access. WAL content may be absent under SQLite immutable readonly mode. SHA within a discovered JSON file is explicitly not independent prior attestation.

The scanner reports `LOCAL_IDENTITY_SCAN_INCOMPLETE_NO_MATCH` if no match but any cap/error was hit, `LOCAL_IDENTITY_SOURCE_CANDIDATES_UNVERIFIED` when source-snapshot JSON or plausible SQLite schema table is found, and `NO_IDENTITY_SOURCE_FOUND_IN_SCANNED_LOCAL_SCOPE` only for completed bounded scan, never as a global no-source assertion. Outputs `scan_cap_reasons`, `json_files_enumerated`, `sqlite_database_paths`, and optionally `sqlite_schema_candidates`. These schema hints do not prove provider identity or preforecast availability.

To inspect again after fetching PR #97 HEAD from the same clean isolated worktree, without network requests by the scanning command:

```bash
PYTHONPATH="$PWD" OPENBLAS_NUM_THREADS=1 ~/zeynal-hybrid-844/.venv/bin/python -B -m hybrid_engine.official_club_identity_pilot --scan-local --club nba_denver_nuggets
```

GitHub Actions commit `64fb99ddd6ef8451120a011745972ea40e3b0393`, run `44472940804`, job `135386544767`: Python 3.11 offline tests **128 passed in 0.81s**. New scan has NOT yet been executed on Android; no assertion of archive findings. PR #97 remains DRAFT. The user's Fly production volume, Telegram and frozen NBA/Europe forecasts/results are unchanged.


## 19 Nov 2026 — Android local scan observed two forecast stores, not native team identity

User's actual local `--scan-local` output: `json_files_enumerated=3221`, `scanned_json_files=321`, `json_bytes_read=33493871`, `scan_capped=true`, `scan_cap_reasons=[JSON_READ_BYTE_BUDGET]`. Three local SQLite files were inspected schema-only: `faz23_storage.sqlite` with `snapshots`, `live-nba/nba-hybrid.sqlite` with `live_analysis_snapshots`, and `telegram-delivery.sqlite` with no matching identity-table name. JSON candidate_files was empty. **This was NOT a complete absence test**: 2,900 JSON files were not parsed, and schema table names do not prove team/player/fixture identity.

Repository source inspection clarifies the two SQLite tables: `faz23_engine/faz23_engine.py` creates `snapshots(ts, fixture_key, payload)` to hold analysis/market records, while `live_analysis_ledger.py` creates `live_analysis_snapshots(league, fixture_id, model_digest, created_utc, payload, sha256)` as frozen forecast snapshots. These are NOT separately verified ESPN `SEASON_PARTICIPANTS_V1` source snapshots; do not join NBA.com official 16106127xx IDs to arbitrary ESPN fixture IDs by field name or guesswork.

PR #97 now marks known `snapshots`/`live_analysis_snapshots` as `FORECAST_SNAPSHOT_SCHEMA_ONLY` rather than identity source proof. If JSON remains byte-capped and only these tables are observed, the scan status becomes `LOCAL_IDENTITY_SCAN_INCOMPLETE_NO_MATCH`, not `LOCAL_IDENTITY_SOURCE_CANDIDATES_UNVERIFIED`. The existing immutable forecast records remain untouched.

**Next targeted Android step (ZERO HTTP, zero JSON inventory reads, zero SQL data rows)**: CLI `--inspect-db-schema` accepts only three fixed filenames and queries only `PRAGMA table_info` on known tables using `mode=ro&immutable=1`. It returns column names/types/primary key flags, no row values, and emphasizes that any `payload` is opaque and not an authenticated source ID record.

```bash
cd ~/zeynal-club-pilot-97 || exit 1
test -z "$(git status --porcelain)" || { echo 'Local modifications; stop'; exit 1; }
git fetch -q origin feature/official-club-news-pilot-20261119 && git checkout --detach -q FETCH_HEAD || exit 1
PYTHONPATH="$PWD" OPENBLAS_NUM_THREADS=1 ~/zeynal-hybrid-844/.venv/bin/python -B -m hybrid_engine.official_club_identity_pilot --inspect-db-schema --club nba_denver_nuggets
```

CI commit `0db524b63c7163ecaddbeeaa7e8c970d07ca931c`, run `44474353203`, job `135391163326`: **134 offline tests passed in 0.89s**. Android schema detail has not yet been run. No modifications to Fly.io, Telegram, frozen results or archive; no model input or robots bypass.

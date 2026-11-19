# Issue #90 — NBA finals, dynamic research and controlled learning

Research branch: `feature/issue90-nba-verification-20261118`.
Review base: `feature/hybrid-market-roster-evidence-20261114` at `2fac4a20a9fb8ec17a37d985444f542d7cb1823d`.
This is a stacked change; it does not merge PR #89 or change its base.

**Release decision: NO_GO.** No main merge, Fly deployment, secret change,
paid provider request, or production data access occurred. External Telegram
delivery, the user's UserLAnd archive, NBA-authority finals and future model
superiority are not verified in this Cloud environment.

## Findings and changes

| Area | Verified source finding | Change / evidence |
|---|---|---|
| Replay | `test_bot.NBAReplayReadOnlyReports` intentionally has no result ingestion. `NOT_INGESTED` is not proof of a live NBA ingestion defect. | Preserve replay semantics; live health explicitly identifies its separate ledger. |
| Live NBA | `test_bot.ready.collect` runs `nba_ledger_settlement.settle` against `nba_service.ledger`; live `/accuracy` and `/compare` read that same ledger. | Existing native identity, snapshot/commit proof, version, clock and regulation checks preserved; add started-versus-future pending health in `/test nba`. |
| Masked failure | `result_poll.poll_once` previously marked a successful Python return `CHECKED` even when its result said `SOURCE_INCOMPLETE`. | Propagate source failures/abstentions and actual completion clocks; keep subsequent league collectors running. |
| Production | `main.build_app` and `production_reports` share `PREDICTION_LEDGER_DB`. `VerifiedAnalyzeService` reconciles NBA history during analysis, but normal production startup had no dedicated verified-result timer. | Add a separate opt-in 300-second worker using the existing release/volume/schema-guarded ledger factory. `ZEYNAL_VERIFIED_RESULT_POLL` defaults to **off**. It has not been enabled or deployed. No new forecast is created by this worker. |
| V1 model | Frozen full-game attack/defense coefficients, absent measured pace/player impact, and deterministic quarter allocation are actual limitations. They do not establish the cause of any individual miss. | Separate V3 fit/publications; never refit or replace V1/V2 artifacts. |
| Calibration | `quality_monitor` is observation-only; existing calibration code deliberately requires explicit offline calls. | A new automatic background **shadow** fit, with separate future publications and exact original-fit scope. Existing calibration plans and raw originals are unchanged. |

Regression evidence is in `tests/test_issue90.py`, the existing native SQLite
settlement tests in `test_handoff_hardening.py`, and the real PTB/local HTTP
command test in `test_nba_overnight.py`.

## Five games on 18 November, Istanbul calendar

Captured public HTTP receipts are in
[`evidence/issue90-native-20261118.json.gz`](evidence/issue90-native-20261118.json.gz).
The SHA of its payload is
`faf9b6e0252042bae4349bbc53e19a26c8263765fc2e0c0223b4d0dcf8ddccc0`.
It contains one ESPN scoreboard, five separate ESPN summaries, actual retrieval
clocks/document hashes, two NBA CDN HTTP 403 probes and a post-result audit.

| Match | ESPN ID | Regulation | Final including OT |
|---|---|---|---|
| Toronto – New York | 401910002 | 102–111 | 102–111 |
| Minnesota – Portland | 401910003 | 106–105 | 106–105 |
| San Antonio – Detroit | 401910004 | 93–105 | 93–105 |
| LA Clippers – Utah | 401910006 | 107–132 | 107–132 |
| LA Lakers – Charlotte | 401910005 | **111–111 (222)** | **118–114 (232)** |

All five summaries agree with the scoreboard's per-quarter scores. These are
two endpoints of **one third-party provider**, not independent league-authority
verification. NBA CDN requests returned 403; `nba_official_verification` remains
`NOT_VERIFIED`. No guessed official NBA game IDs or fabricated NBA receipts were used.

The user's original phone ledger/assets are not present here. Reported forecast
totals, screenshots, bets and later market quotes were **not** converted into
prematch evidence. No new accuracy/win-rate figure was computed for those five
forecasts. The audit CLI can link actual originals by native fixture identity,
snapshot SHA, fitted version, production/publication clocks and replayed source
assets when run against that existing archive. It does not ingest results or
make predictions. Existing ESPN-ledger eligibility and NBA-authority verification
remain different claims.

## Separate V3 model

`nba_dynamic.py` fits recency-weighted attack/defense efficiency per estimated
100 possessions with opponent adjustment and Gaussian partial pooling. A
14-day half-life and actual six-hour preparation slots update the full-game
mean from newly available results. Minimums: 30 native regulation box games,
six games per target team, recent team history within 14 days. Future labels,
cross-season/league targets, target-training overlap and the final 15 minutes
are refused.

The sampler produces 10,000 MC or eight-dimensional randomized Halton paths.
Quarter/team residual covariance is shrunk and combined with projected
parameter uncertainty. Periods are stochastic and correlated, rather than a
deterministic allocation of one full-game draw. These are research distribution
assumptions, not demonstrated coverage or calibrated confidence.

**Pace remains a box estimate**, `FGA + .44 FTA - ORB + TOV`, not measured PBP
possession boundaries. Strict all-feature inference explicitly abstains.
Native measured-PBP ingestion is not implemented by this PR. The existing
verified-annotation possession research is not relabeled as a live PBP feed.

`nba_schedule_features.py` captures eight dated native calendar documents before
tipoff. It derives start-to-start gap and NBA-calendar back-to-back status. It
only derives venue geodesic distance when both native venues have coordinates;
missing coordinates are `None`, never zero travel. Geodesic distance is not a
measured itinerary, and start gap is not physiological rest. The separate
exploratory context-rate ablation needs 30 prospectively recorded, later-labeled
contexts and varying exposures before fitting coefficients. It is not the
registered primary. No fixed rest/travel score adjustment is invented.

V3's primary has **no fitted player coefficient**. The unchanged V2 player study
still requires verified prospective minutes, player identity, official absence
corroboration, later native labels, 100 eligible games and exposure variation.
No unverified injury text is translated into a guessed points penalty. A joint
PBP/player/context efficiency model remains a subsequent data-dependent study;
the current fallback is explicitly narrower.

`issue90_research.py` registers a separate source-pinned plan, admits future
originals before results, fits in the background, rechecks the native fixture
after simulation and publishes immutable candidate records linked to the
original SHA. V2 and V3 run serially to avoid concurrent model work. `/analyze`
never trains. Restart/retry/crossing the safety boundary cannot replace a first
publication. Existing 27 V1 source pins and 13 V2 source pins match the review
base; their registered experiments have not been reset.

## Controlled learning and comparison

`shadow_learning.py` fits winner reliability cells only from 100 independently
authenticated, settled originals in one NBA season and **exact original fit**.
It checks source audit, snapshot SHA, model-training exclusion and all
availability/publication/final clocks. A bin needs 30 observations. The candidate
has a new actual preparation/publication time; it does not backdate a calibrated
probability into the original forecast. Probability-only learning does not
depend on box-model readiness.

V3 future acceptance requires 100 matched unseen games, 20 Istanbul match dates,
80% coverage of admitted settled games, at least 2% team-MAE improvement and a
paired day-cluster interval below zero. Different original fit/season cohorts
are separated. Team/total/margin/quarter/half MAE, RMSE and bias, three-class
Brier/log loss, coverage and interval scores use verified regulation outcomes.
The calibration study separately requires 100 future games / 20 days, Brier
gain at least .01 and simultaneous paired Brier/log-loss intervals supporting
improvement. An inadequate candidate is rejected. Even a passing candidate is
only eligible for manual review; **automatic promotion is always false**.
Repeated-team dependence across dates remains a limit of day-cluster intervals.

**Real V3 versus old-model performance: NOT_YET_EVALUABLE.** No new prospective
V3 cohort from the user's archive has been evaluated here. Existing V2
retrospective figures are not substituted for this V3 acceptance experiment.
Synthetic positive/rejection tests establish gate behavior, not model superiority.

## Market audit

`joint_market_audit.py` reuses native quote/rule guards for winner, handicap,
total, team totals, halves and quarters. Scope, exact fixture, source time,
prices, rule compatibility and actual final/snapshot/model identity are checked.
It reports raw probabilities and realized line deviations/returns only when
the relevant evidence exists. Calibrated joint probabilities and confidence
remain absent. Missing lines do not become `NO EDGE` or invented probabilities.

ML + total research uses Boolean intersection on the **same** paths. A
regression test has marginal probabilities .5/.5 but joint probability .5,
proving the implementation does not report the incorrect product .25.
No combined bookmaker price, parlay push rule or overtime model is invented.
Non-full-period overtime contracts are refused. Existing original market
snapshots, provider bindings and quote-time evidence are unchanged.

## Validation and external limits

Actual test outputs, command lines and log hashes are saved in
`evidence/issue90-validation-20261118.json`; the raw local full-suite log is
stored alongside it as gzip. The first full integration run passed 1,527 tests;
the next passed 1,530. The final full local run passed **1,532 tests in 141.220
seconds**. The latest standalone Issue #90 regression run passed
38 tests in 6.540 seconds. CI runs the full suite in the deployment image and
the provider/PTB suite under hard 256 MiB / one-CPU Docker limits.

The local provider probe passed 561 tests in 73.102 seconds with peak process
RSS 127.08 MiB. That host had an 8 GiB / two-CPU cgroup; it is **not** proof of
the hard production limit. Exact-head GitHub Actions results are recorded in
the PR, including any failures.

Development failures were not hidden: the initial new tests found a nested
publication lock error (two errors), and one negative fixture changed the
wrong native identity field (one failure). Those were corrected. A later
synthetic calibration test initially overlapped a training ID and correctly
abstained; its future fixture was corrected. A network-restricted local test
invocation was interrupted during executor shutdown, then passed with the
loopback access needed by these asynchronous tests.

The real PTB/local HTTP flow exercises `/start`, `/nba`, empty `/analyze`, a
complete archived `/analyze NBA ...`, `/accuracy NBA`, `/compare NBA ...`,
`/predictions NBA`, `/test nba` and `/test research`. It checks replies and
Telegram UTF-16 limits while retaining original SQLite snapshot bytes. Europe
integration/40-minute/automatic-prematch/callback suites remain included.
**Local HTTP is not external Telegram acceptance.**

Actual preflight returned:

```json
{"status":"NOT_CONFIGURED","missing":["ZEYNAL_TEST_BOT_TOKEN","ZEYNAL_TEST_BOT_ID","ZEYNAL_TEST_BOT_USERNAME","ZEYNAL_TEST_CHAT_ID"],"actual_telegram_delivery_verified":false}
```

No real Telegram sends or provider-authentication successes are claimed.
No token value is requested, printed or committed.

## UserLAnd verification after checking out this research branch

The launcher accepts the existing isolated branch and this Issue #90 branch;
it refuses other branches. Its diagnostic modes do not fetch Git, start a
poller, train a model or register a new plan:

```bash
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh --issue90-status
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh --issue90-audit
```

The audit reads the existing phone ledger/assets, queries the public ESPN
scoreboard and writes **new audit receipts/reports only** under `data/issue90`.
It does not recreate missing originals. After a normal isolated-bot restart,
V3 uses `data/nba-research-v3`; old NBA/V2/European paths are preserved.

Send each Telegram command as a separate message:

```text
/start
/nba
/analyze
/accuracy NBA
/compare NBA 401910005
/test nba
/test research
/predictions EUROLEAGUE
/predictions EUROCUP
```

Also replay one complete NBA analysis command from `/predictions NBA` or the
verified `/nba` menu. Check actual API delivery records and replies, not just
the local test output. Live UserLAnd delivery and those original five forecasts
remain external acceptance work. Production deployment/secret changes require
explicit approval and were not performed.

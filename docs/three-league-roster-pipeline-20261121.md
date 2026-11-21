# 2026-11-21 — Three-league roster-to-forecast evidence integration

Research-only draft PR #145. NBA, EuroLeague and EuroCup are three independent competition/season identities. No existing first forecast is rewritten; no Telegram or Fly production change.

## Existing actual coverage

- 2026/27 competition inventory: NBA 30, EuroLeague 20, EuroCup 32 = 82.
- Only six official club news page pilots are currently verified, 76 are not connected; club membership is NOT club-news connector coverage.
- NBA injury/roster review, source metadata, news pilot and historical postgame player boxes exist. No complete NBA native roster source is wired to this new bridge and the trained scoring artifact contains no player effects.
- Official EuroLeague and EuroCup native season club player registration endpoint exists; status is SEASON REGISTRATION, not proof of eligibility/availability/minutes.
- Existing time-bounded transfer_evidence module is research-only. News item does not automatically confirm player transfer to a club. No live all-82 club transfer news monitor or continuous scheduler.

## New actual code

1. hybrid_engine/three_league_roster_bridge.py: identical canonical SHA-pinned source observation contracts for NBA/EUROLEAGUE/EUROCUP; europe_pair() consumes the existing native E/U season registration adapter. Refuses unresolved player ID, fixture/league/season conflicts, invalid source clocks and duplicate athlete IDs across opponents. It does NOT claim all NBA players are already sourced.
2. compare() evaluates consecutive same-club official season registration snapshots. It reports new and no-longer-listed player IDs without inferring that a contract was signed, a trade completed or a player is medically cleared. No retrospective backfill.
3. fixture_gate() requires separate pregame official roster membership, fixture-bound AVAILABLE/OUT/QUESTIONABLE data, expected minutes and prefit player exposure evidence. If any input is absent or unknown, this does not create numeric player effects. Even a synthetic complete gate is marked RESEARCH_CONTEXT_PRECHECK_ONLY, with no production model input.
4. hybrid_engine/roster_registration_observer.py: optional direct official Euro native GETs using existing adapter; opt-in append-only on-disk SHA-pinned club registration observations and automatic differences between later and earlier visits. HTTP 429 or other missing source gives UNKNOWN, not a cleared roster. No automatic background schedule.
5. Command-line --readiness returns true code/source integration status with explicit missing full NBA roster and fitted player effects.

## Android/UserLAnd isolated test (no original checkout or Fly change)

    cd ~/zeynal-hybrid-844 &&
    git fetch origin feature/three-league-roster-integration-20261121 &&
    ROSTER_TEST="$(mktemp -d)" &&
    git worktree add --detach "$ROSTER_TEST/checkout" FETCH_HEAD &&
    cd "$ROSTER_TEST/checkout" &&
    PYTHONDONTWRITEBYTECODE=1 "$HOME/zeynal-hybrid-844/.venv/bin/python" -B -m unittest -v tests.test_three_league_roster_bridge tests.test_roster_registration_observer

Three league source readiness (no network or writes):

    PYTHONDONTWRITEBYTECODE=1 "$HOME/zeynal-hybrid-844/.venv/bin/python" -B -m hybrid_engine.three_league_roster_bridge --readiness

Optional Euro official registration smoke (actual current player names; no saved data):

    PYTHONDONTWRITEBYTECODE=1 "$HOME/zeynal-hybrid-844/.venv/bin/python" -B -m hybrid_engine.roster_registration_observer --league EUROLEAGUE --season 2026/2027 --home ZAL --away PAN

Optional separate future-only immutable registration observations, NOT production or predicted lineup:

    PYTHONDONTWRITEBYTECODE=1 "$HOME/zeynal-hybrid-844/.venv/bin/python" -B -m hybrid_engine.roster_registration_observer --league EUROLEAGUE --season 2026/2027 --home ZAL --away PAN --save-directory "$HOME/zeynal-test-isolated/data/player-registration"

The club codes here are optional source-test example parameters; the code does not hardcode team names in the /analyze scoring algorithm. Repeating --save-directory records new official registration versions automatically, but polling must be configured separately; it is not always-on.

## Pending and required before genuine injury/player-adjusted forecast

1. Live official NBA complete current player identity/roster; validated all 82 official club source endpoints, licensing and 403/429 boundaries.
2. Transfer/registration identity matching, signed transfer effective date and genuinely official registration approval; no headlines promoted automatically to active.
3. Verified fixture-specific injury/AVAILABLE/QUESTIONABLE statuses and precise source-first-observed times.
4. Independently fitted, leak-free player lineup/on-off/pace impacts, coach/rotation and projected minutes; league-specific 48 vs 40 minute constraints.
5. Separate prospective player-feature-bearing NBA/E/U numeric model integrated into score, quarter and exact market distribution, with no overwrite of frozen first forecasts.
6. Forward-only evidence on true market lines and final results, regression tests and explicit deployment approval.

**New bridge and observation store do NOT mean full production model integration.** When a claim is unverified, it blocks rather than fabricates numeric impact.


## Reuse discovered working modules, do NOT rebuild them

Additional source audit found already implemented but not production-promoted modules:

- hybrid_engine/player_minutes.py, player_inputs.py: native NBA source/roster + six prior box games + corroborated OUT status -> exact prospective, SHA-pinned PLAYER_MINUTES_PROJECTION_V1; output is a *projected prior*, not confirmed playing time.
- hybrid_engine/player_shadow.py: separate own-team scoring regression using prospective minute projections, a frozen team control and player Bayes candidate. Not used by existing production Bayes and fit is blocked when no genuine prospective minute archive. This module has its own >=100 record research policy, not a validation of predictive edge nor a reason to wait instead of fixing data flow.
- hybrid_engine/adaptive_models.py / adaptive_research.py: separate pace-efficiency and team strength variants across leagues; no trained player effects for EuroLeague or EuroCup. These are research-only and not a trained unified ensemble.

The bridge now exposes existing_nba_minutes_candidate(): a direct call to player_minutes.projection followed by validate_minutes, returning the original canonical output packet untouched if real game-specific inputs pass. Any missing roster/availability/historical boxes aborts with specific BLOCKED status. This is the actual code-level reuse contract; it does not fit a player model or publish a Telegram forecast. Europe still requires independent league-appropriate player minutes and 40-minute model fitting; no NBA parameters are copied.

GitHub Actions initial full test run #44931798031 showed 1999 passed / two synthetic regression failures: a stale example player ID and a duplicate synthetic player assigned to both sides. Both test data problems were corrected on the same isolated branch and rerun; do not report the later full CI as successful until its completed conclusion is observed.


## Real Telegram E2E diagnostic wiring (production + isolated test)

Code now binds same read-only /test integrations to production_parity.py real production handler and test_bot.py isolated authorized test-chat handler.
Displays current bot process service status, observed analysis metadata, archive reader configured, reported release SHA, source coverage and explicit unconnected player/coach scoring impact status. This diagnostics call does no network fetch, fit, scoring or archive mutation.

- /test runtime: existing runtime identity and analysis probe
- /test integrations: newly added live process and source-model stage audit
- /features /sourceplayers /injurynews /predictions NBA /results all /accuracy all: old commands testing their own coverage, not a claim that injury data alters score

## Protected Fly release conditions

See .github/workflows/fly-existing-machine-deploy.yml: main branch only, exact release SHA, single existing AMS machine and its /data volume, existing volume snapshot, previous image rollback and after-deploy /ready proof. Automatic workflow_run additionally checks a historical fixed commit subject ZEYNAL_PRODUCTION_RELEASE_20261119; GitHub Actions manual dispatch requires confirm_deploy=DEPLOY.
Draft PR #145 is not merged or deployed. No Telegram delivery observed by the assistant; current live Fly image/version not yet verified. Synthetic CI passing is not proof of live player data or fitted model output. Do not bypass source readiness or deploy unverified numeric model coefficients.

## Phone: ACTUAL isolated Telegram bot E2E (after its last CI code pass)

Terminate an already running isolated bot with Ctrl+C in its original UserLAnd shell; never run two getUpdates pollers using the same test token.

From existing checkout:

    cd ~/zeynal-hybrid-844 &&
    git fetch origin feature/three-league-roster-integration-20261121 &&
    git worktree add -b feature/three-league-roster-integration-20261121 "$HOME/zeynal-3lig-test" FETCH_HEAD &&
    cd "$HOME/zeynal-3lig-test" &&
    bash scripts/run_isolated_test_bot.sh

Existing launcher enforces a single local poller, a separate test token, isolated test data/models and a branch allowlist; this research branch has now been added to the allowlist only.

Inside the authorized Telegram **test** bot:

    /test integrations
    /test runtime
    /features
    /test data
    /sourceplayers EUROLEAGUE 2026/2027 ZAL PAN

The sourceplayers command only tests official current season registration for those exact test parameters and may be unavailable/429. Neither it nor the diagnostics proves a current active five, injury absence, trained player effect or accurate future scoring. Real bot delivery can only be confirmed by actual Telegram response on user device. Do not disclose tokens or use Telegram Bot API directly in chat.

**Production is separate:** main.py is the Fly poller, not the isolated test bot; moving this branch to main alone does not auto-deploy due the existing protected Fly release workflow. Never overwrite Fly volume or deploy unverified numeric parameters. This PR is draft until real source coverage and latest full CI confirmed.

## 2026-11-21 User requested activation of player_minutes, player_shadow and adaptive_models

Code on this isolated branch now gives source-first **automatic RESEARCH execution** precedence: `ResearchCycle.once` begins with `AdaptiveWorker.tick()` (adaptive_models native box/pace candidate and NBA `player_inputs.collect` -> existing `player_minutes`), then original V3 model and current assessment, always serial (never concurrent V2/V3 source fits). At restart, actual `test_bot.py.ready` schedules the same ResearchCycle.run task. This replaces earlier V3-first ordering that could leave V2 unobserved on a cold Android process.

New authorized `/test engines` shows genuine runtime `AdaptiveWorker` sequence, exact research cycle stage, the latest V2 result, available source/box counts by league, player minute acquisition success or specific blockage, and `player_shadow.readiness()` from the isolated research directory. It also exposes whether a prospective NBA player Bayes candidate was archived; **the main numeric score input remains off** until a real validated player model and actual available minutes exist. There is no fabricated +/− impact, no auto promotion based on passing CI, and no overwriting original first predictions.

Use the live isolated Android test bot after new branch is fetched/restarted:

    /test engines
    /test research
    /test integrations
    /models NBA ACTUAL_FIXTURE_ID

Do not confuse an installed candidate or a single `CHECKED` work attempt with a calibrated player effect in production. If the device reports `NO_PREGAME_MINUTES_ATTEMPT_OBSERVED` or `BLOCKED`, we must fix the exact source/identity/first-archive issue from that report; no numerical output can be declared trustworthy until the data exists.

Tests now include `tests/test_active_engine_status.py` and change `CycleTests` to check V2-before-V3 serial startup. Latest full CI conclusion and user-device execution must be observed before reporting activation successful. PR remains DRAFT, no protected Fly `/data` change or production rollout.
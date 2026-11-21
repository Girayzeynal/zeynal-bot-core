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

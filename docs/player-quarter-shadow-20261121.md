# Player + quarter-first NBA possession shadow — 2026-11-21

**STATUS: ISOLATED RESEARCH IMPLEMENTED, 12 SYNTHETIC TESTS PASSED LOCALLY.** Source/test GitHub blob IDs exactly equal those of locally tested files. Not deployed; no real player feed or fitted player coefficients attached. No 2026/27 archived forecasts, protected positive signed-error cases, Telegram settings or production files changed.

Linked root-cause issue: #142.

## Actual change to the algorithm

The old path generates full-game team totals first and deterministically allocates them to quarters with historical weights. The new independent research module hybrid_engine/lineup_possession_shadow.py:

1. Requires SHA-pinned, timestamp-valid complete player availability, projected **five-man lineups per stint**, an already-fitted player/coach/pace model and a verified fixture identity declaration.
2. Refuses OUT or questionable players in a predicted five, missing player coefficients, future-arriving sources, training on the target fixture and incomplete four-quarter minute coverage.
3. Generates an effective shared **possession count independently for each lineup stint** from a Poisson process. Each team's 0/1/2/3/4 points per offensive possession depends on its on-court offensive player coefficients, the opponent's five defensive coefficients, quarter-specific coach model coefficients and home-court model coefficients.
4. **Only then** sums stints to Q1/Q2/Q3/Q4, to 1H/2H and to the full game. There is no old largest-remainder allocation. Every score path, total and the raw ALT/UST line-based probability share the same quarter-generated simulation.
5. Checks coherent score paths, 12 minutes per team/quarter, 240 player-minutes per team/game, 48-minute player cap, 5 distinct AVAILABLE players in every stint, finite numeric values and timestamp/hash constraints.

This is a **stint-level effective-possession model**, not a full play-by-play engine or independently verified NBA estimate. It does not fit coefficients, download real data, authenticate a medical source, create odds, or claim a coach tactic was truly observed. Sources in the input bundle are explicitly labelled DECLARED_SOURCE_NOT_INDEPENDENTLY_VERIFIED. A valid hash proves an unchanged envelope, not a verified news report. Output flags production_changed=false, deployable=false, verified_predictive_accuracy=null and no independently verified source authenticity.

## Required input bundle

The standalone module requires these exact top-level keys:

- format = LINEUP_POSSESSION_QUARTER_SHADOW_V1
- fixture: league NBA, fixture_id, home_team_id, away_team_id, decision_utc, tipoff_utc
- model: {payload, sha256} with payload format PREFIT_LINEUP_POSSESSION_PARAMETERS_V1; previously-available training game IDs and training cutoff; team possession rates per 48; two sets of 0..4 point-category probabilities; fitted per-player attack/defense/pace coefficients; quarter-specific coach attack/pace; home effect coefficients. Every player must have coefficients, including those marked OUT (but OUT must never play). Existing NBA PreparedBayes has no fitted player effects.
- roster: {payload, sha256} with payload format PREGAME_NBA_ROSTER_STATUS_V1, same fixture identity, prior observed/available UTC, source HTTPS URL and SHA, complete relevant player identities and explicit AVAILABLE/OUT statuses. QUESTIONABLE without a valid separate status-scenario model is refused.
- rotation: {payload, sha256} with payload format PREGAME_LINEUP_ROTATION_ESTIMATE_V1, prior source time and SHA, PREGAME_PROJECTED_NOT_CONFIRMED status, for each quarter time-bounded lineup stints with minutes and five home/five away IDs. Quarter durations must sum to 12.

Each SHA is a SHA-256 digest of the canonical JSON payload (keys sorted, compact separators, allow_nan=False). All sources must have attestation DECLARED_SOURCE_NOT_INDEPENDENTLY_VERIFIED; the running code cannot establish external authenticity. No model terms or projected minutes are filled with guesses.

## Test on Android/UserLAnd — no checkout, deploy or original-data writes

    cd ~/zeynal-hybrid-844 &&
    git fetch origin feature/player-quarter-possession-shadow-20261121 &&
    TMPDIR_SHADOW="$(mktemp -d)" &&
    git show FETCH_HEAD:hybrid_engine/lineup_possession_shadow.py > "$TMPDIR_SHADOW/lineup_possession_shadow.py" &&
    git show FETCH_HEAD:tests/test_lineup_possession_shadow.py > "$TMPDIR_SHADOW/test_lineup_possession_shadow.py" &&
    cd "$TMPDIR_SHADOW" &&
    PYTHONDONTWRITEBYTECODE=1 "$HOME/zeynal-hybrid-844/.venv/bin/python" -B -m unittest -v test_lineup_possession_shadow

The 12 synthetic tests cover independent quarter scores, active/OUT exclusion, 12-minute quarters, 240 team player-minutes, sample sums, deterministic seed, current clock/cutoff, SHA mismatch, missing learned player coefficients, unresolved status and market probabilities.

One deliberately **synthetic** example produces approx 23 / 35 / 35 / 29 home-team points across quarters from independently simulated possessions. These are not real NBA forecasts or calibrated probabilities.

## Real-data blockers, not completed

- Independently verify real NBA pretipoff roster + injury status and provider player IDs; current_roster.py is only an information review and is NOT a score-input adapter.
- Acquire point-in-time historical projected minutes/lineup exposures; **fit actual player coefficients** under a training cutoff with proper forward evaluation. Do not invent fitted effects.
- Acquire historical quarter and coach rotation data; estimate pace, point-category probabilities, coach pace/attack, opponent defensive impacts and home effect with leakage-proof fitted provenance. A declared synthetic coefficient is NOT sufficient for real model use.
- Create an injury-absence lineup substitution engine based on observed rotations, not arbitrary replacement or missing player minutes.
- Verify original pregame bookmaker lines and bookmaker overtime contract before reporting market wins.
- Store prospective original + new-shadow probability/direction records before tipoff; evaluate same future fixtures, no posthoc outcome tuning or arbitrary 100-match gate.
- Production, Telegram and Fly.io integrations require separate explicit approval and verified source coverage.

**This version contains the executable shadow math, not the verified live basketball data adapters or a fitted real-world model.** No real historical/model-accuracy improvement is claimed.

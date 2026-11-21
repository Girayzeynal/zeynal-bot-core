# Team-specific game dynamics — observation first, no universal scorer pattern

Status: **separate read-only research module**. The user explicitly clarified that the 22-point Q1 / 35-point Q2 example was evidence that different teams behave differently, **not an instruction to make every team follow that profile**.

## What this implementation does

`hybrid_engine/team_dynamics_evidence.py` does **not fit a predictive model** and does **not create ALT/ÜST decisions**. Instead, for each separately identified team, it keeps the original four regulation quarters from historical matches available before a requested decision timestamp and divides observations by team, venue and specific opposing team ID. Results include the raw chronological matches, each period's for/against mean, median, SD, min/max and the observed frequency of each quarter being the high-scoring quarter.

There is no preset 55/55/55/55 sequence, no 22/35/35/29 pattern, no fixed universal period threshold, no built-in team scoring bonus and no arbitrary model calibration. Two teams with opposite original historical profiles remain opposite in the output. The same team has separate observed **home vs away**, opponent and raw chronology, without claiming these are independent predictive drivers.

Native integration is offered through `from_native_cut(cut)` using the existing `hybrid_engine.data.Cut`, `STRICT` evidence class and `available_at(row, STRICT)`; it depends on a valid original native runtime cut, not an invented user-historical dataset. A separate normalised-JSON CLI exists for approved, already prepared inputs, but hashes and timestamps on arbitrary JSON do not independently prove real-world authenticity. Data must be validated at ingestion.

A team with zero historical observations has no period statistics; nothing is filled. Missing four regulation quarters, duplicate fixtures, mixed seasons, records available only after the decision and target-game results are rejected.

## What this implementation does NOT know

The core archive fixture-period rows contain **no independently verified active player five, player status, actual rotation minutes or coach game plan**. The output explicitly marks these as unavailable and is **not a player-aware model**. It also does not measure possessions, 3-point attempt share, referee effect or travel fatigue. The previous experimental lineup/possession simulator (draft PR #143) is **not made the mandatory answer** or deployed: its synthetic 22/35 example is an engineering demonstration only, not a fitted NBA scoring law.

To study true team-specific dynamics, a future empirical study must source original timestamped player identities, matchup-specific 5-man rotations, period pace, shooting/rebounds/turnovers, injuries, home/away and coaching decisions, keep missing coverage explicit, and only then fit and evaluate a model in chronological prospective shadow mode. No prechosen quarter template or invented player/coach coefficients are acceptable.

## Verified local synthetic tests

**12/12 passed in the local container**. Cases cover opposite team period profiles, opponent and home/away attribution, no prediction issuance, stable evidence digest independent of input order, leakage after decision, rejected duplicate/mixed-season/invalid periods, overtime-excluded normal-time totals, empty evidence and no writes to the original data.

Exact local Git blob SHAs were checked against GitHub:
- Source: `8ed294e4312a99a7c21c5127a0f0b21f5dc508c6`
- Test: `4e8e0b3fc226ee09b5ecf30922f27f0c8e944856`

The tests are **synthetic** and do not establish actual predictive accuracy or live source ingestion.

## Android/UserLAnd isolated test

This command downloads just the two file contents from this research branch into a temporary folder; it does not check out a branch, touch saved NBA forecasts or deploy anything.

```bash
cd ~/zeynal-hybrid-844 &&
git fetch origin feature/team-dynamics-pregame-evidence-20261121 &&
T_DIR="$(mktemp -d)" &&
git show FETCH_HEAD:hybrid_engine/team_dynamics_evidence.py > "$T_DIR/team_dynamics_evidence.py" &&
git show FETCH_HEAD:tests/test_team_dynamics_evidence.py > "$T_DIR/test_team_dynamics_evidence.py" &&
cd "$T_DIR" &&
PYTHONDONTWRITEBYTECODE=1 "$HOME/zeynal-hybrid-844/.venv/bin/python" -B -m unittest -v test_team_dynamics_evidence
```

Original 54 forecasts, 46 validated outcomes, 33 original TOTAL quote lines, 21 positive signed score-error original forecasts, and all production/Telegram paths are unchanged. **The research component cannot be promoted to production as an NBA direction predictor: it intentionally has no betting decision or fitted player/coach parameters.**


## Actual original NBA data path (not synthetic, device execution pending)

Added `hybrid_engine/team_dynamics_native_census.py`: accepts the **same original read-only** signed native quality report, SQLite ledger and original source assets already used for the NBA 54/46/33 research. For every NBA original first-forecast record, it reads the exact pre-tipoff original ledger snapshot in SQLite read-only mode, checks quality-to-snapshot SHA and exact original input-cut asset SHA, then runs existing `hybrid_engine.prediction_audit.audit_snapshot` source/feature reconstruction before extracting period scores from the **saved original preforecast history**, not present-day downloaded archives or reconstructed final-game data. Snapshot and original historical source availability must precede the first prediction. An error aborts the audit instead of filling missing history.

The result is an **observed coverage census**: original forecast count, count of historical evidence profiles, counts of both teams having history, and the actual saved Q1–Q4 mean for each team **on its own prior games** (not universal weighting), plus home/away counts, distinct observed opponents and direct head-to-head count. The first eight example fixtures are printed unless `--examples` is set. No prediction, bookmaker line or directional accuracy is produced. The same historical game can occur in several different forecast input cuts: summed source-game observations are *not* independent distinct NBA games.

### Isolated actual-device run

Run from `~/zeynal-hybrid-844`, without switching branches or touching the original saved SQLite database:

```bash
cd ~/zeynal-hybrid-844 &&
git fetch origin feature/team-dynamics-pregame-evidence-20261121 &&
TD_TMP="$(mktemp -d)" &&
git show FETCH_HEAD:hybrid_engine/team_dynamics_evidence.py > "$TD_TMP/team_dynamics_evidence.py" &&
git show FETCH_HEAD:hybrid_engine/team_dynamics_native_census.py > "$TD_TMP/team_dynamics_native_census.py" &&
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$TD_TMP:$PWD" .venv/bin/python -B "$TD_TMP/team_dynamics_native_census.py" \
  --report "$HOME/zeynal-test-isolated/data/quality-phase924/reports/quality-4b2be633584586dd439fcfc3f6414001217ac4d9f8c60a9d8fc68c6e17a7a2f1.json" \
  --ledger "$HOME/zeynal-test-isolated/data/live-nba/nba-hybrid.sqlite" \
  --assets "$HOME/zeynal-test-isolated/data/live-nba/assets" \
  --examples 6
```

The source-vs-original forecast snapshot reconstruction is intentionally strict and may reject unsupported/missing original records. **No user-device result was observed yet; no NBA player data was connected.**

Additional synthetic regression tests for exact source pins and clock leakage bring the local total to **17/17 passing**: the two test files are standalone in the test folder. Local Git blob SHAs of the native census and new test have been matched to the GitHub versions:
- `hybrid_engine/team_dynamics_native_census.py`: `63580bc621fb2f38f009f2fcb26fe2dc25076339`
- `tests/test_team_dynamics_native_census.py`: `289b36df934a027365ff413f5cd491c6add6819f`

**Crucial:** This is empirical observation inventory, not training, a future score recommendation, a new betting pick, injury adaptation, or a real player-aware model. Nothing has been deployed or backfilled.


## User-device observation received: 54/54 original first forecasts

On 2026-11-21, user executed the source-pinned **actual NBA** `team_dynamics_native_census.py` successfully. The original, immutable report showed:

- `original_native_forecasts=54`, `native_profiles=54`,
  `profiles_with_both_team_histories=54`.
- `total_original_history_fixture_observations=1069`: total repeated
  *forecast-input historical match references*, **NOT 1,069 independent NBA fixtures**.
- Every displayed side in six sampled fixtures used 10 own historical games,
  with each side's own observed periods, opponent identities and venue counts.
- An original fixture had team ID 15 home 10-game Q1–Q4 means
  `[22.9,21.6,31.7,26.1]` and team ID 1 away
  `[26.9,32.5,28.5,27.6]`. This is observational evidence of distinct
  previous-game patterns, NOT a rule for other teams or a future score prediction.
- `current_player_injury_coach_context_available=false`,
  `directional_betting_accuracy=null`, `original_forecasts_changed=false`,
  `positive_original_cases_changed=false`, `production_changed=false`.

**Now added (not yet executed on user's actual original files)**:
`--player-coverage-only` on the *same* SHA-pinned native census checks
`cut.features[home/away].boxes`. These are prior completed-game
ESPN player box records, time-eligible at the original forecast. The report
counts the historical games with box scores, player rows, distinct historical
athlete IDs and minutes *display* fields for each team. No missing box scores
are filled. Players who appeared in prior box scores must NOT be asserted to
be on a current playable roster, nor should their observed postgame minutes
be substituted for a time-eligible projected rotation.

The source and corrected synthetic test file were checked by exact Git
blob hashes against the committed GitHub files. **19/19 synthetic regression
tests pass locally**, including player rows in an original historical Cut,
rejecting duplicate player IDs and historical side mismatch, historical
prediction SHA and input asset pins, no false current lineup status.

### Single Android device check for historical player box availability

```bash
cd ~/zeynal-hybrid-844 &&
git fetch origin feature/team-dynamics-pregame-evidence-20261121 &&
TD_TMP="$(mktemp -d)" &&
git show FETCH_HEAD:hybrid_engine/team_dynamics_evidence.py > "$TD_TMP/team_dynamics_evidence.py" &&
git show FETCH_HEAD:hybrid_engine/team_dynamics_native_census.py > "$TD_TMP/team_dynamics_native_census.py" &&
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$TD_TMP:$PWD" .venv/bin/python -B "$TD_TMP/team_dynamics_native_census.py" \
  --report "$HOME/zeynal-test-isolated/data/quality-phase924/reports/quality-4b2be633584586dd439fcfc3f6414001217ac4d9f8c60a9d8fc68c6e17a7a2f1.json" \
  --ledger "$HOME/zeynal-test-isolated/data/live-nba/nba-hybrid.sqlite" \
  --assets "$HOME/zeynal-test-isolated/data/live-nba/assets" \
  --examples 2 --player-coverage-only
```

The preforecast player-box count cannot establish true 5-man lineup rotations,
pregame injury status, coach tactics, or causal player strength. Do not
promote this evidence census to production direction forecasting.

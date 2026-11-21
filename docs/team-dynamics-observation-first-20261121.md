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

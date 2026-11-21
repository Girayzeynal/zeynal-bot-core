# First priority: original ALT/ÜST direction evidence, not numeric P95 adjustments

The user explicitly redirects analysis away from widening upper-score intervals:
**find out if the bot gave the right ALT/ÜST direction at each market line**.
This must use only native **pre-forecast** quote evidence and the **unchanged
original** prediction. No outcome-informed pseudo-decisions may be credited.

## What was actually available in the existing code

- `hybrid_engine/market_direction_ui.py` computes per-quote raw model tilt
  for a display, but a generated historical display is **not an immutable
  originally published pick**.
- `hybrid_engine/decision_metrics.py` already offers actual original
  market-decision settlement audit when there are **prepublished, recorded
  decisions**, a quote tied to the same fixture and model, and authenticated
  book settlement rules. That is the authoritative path for a genuine market
  direction hit rate.
- ESPN-native total quotes are parsed by
  `hybrid_engine/observed_markets.py`, but their
  `settlement_scope` is `UNKNOWN` (the native field does not certify whether
  overtime counts). They cannot automatically be called settled bookmaker
  wins/losses on NBA regulation-only scores.
- The previous `quality-4b2be633...` report verifies 46 regulation
  finals for 54 original forecasts; it **does not** prove 46 originally
  logged ALT/ÜST market selections.

## Read-only pregame evidence census

`hybrid_engine/pregame_direction_evidence.py` loads one SHA-authenticated
private quality report, reads the *exact original* NBA snapshots from the
SQLite database using `mode=ro`, hashes the original snapshot IDs, and
reuses `observed_market_evidence()` to decode pre-forecast ESPN native
bookmaker total lines from original pinned source assets. It reports:

- number of original NBA forecasts and native results,
- number of fixtures with original bookmaker TOTAL quotes at the original
  forecast time, and how many were already stale (>300 seconds),
- for each observed quote: bookmaker, line, observed time, original frozen
  total score and what **mean-vs-line ALT/ÜST tilt would be inferred today**,
- separate actual *regulation-only* side relative to that line when available,
- no invented line, no new forecast, and **no original published-pick
  accuracy claim**. `actual_original_direction_decision_hit_rate` remains
  `null` unless there is separate original pregame decision evidence
  from the authoritative decision-batch audit. The module never claims book
  settlement success when rule evidence is missing.

### Android/UserLAnd: run without checkout or merge

```bash
cd ~/zeynal-hybrid-844 &&
git fetch origin feature/pregame-direction-evidence-20261121 &&
git show FETCH_HEAD:hybrid_engine/pregame_direction_evidence.py |
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B - \
  --report "$HOME/zeynal-test-isolated/data/quality-phase924/reports/quality-4b2be633584586dd439fcfc3f6414001217ac4d9f8c60a9d8fc68c6e17a7a2f1.json" \
  --ledger "$HOME/zeynal-test-isolated/data/live-nba/nba-hybrid.sqlite" \
  --assets "$HOME/zeynal-test-isolated/data/live-nba/assets"
```

This reads existing files. It does not modify the user's current test branch,
the original 21 positive-error cases, 25 negative-error cases, score model,
P95 values or production. All prospective direction-vs-price metrics must
preserve exact league, book, line, period, overtime settlement rule, original
decision publication clock, non-tied outcomes, and **one independent
fixture per cohort**.

If the census shows **zero valid original quotes**, the correct result is
that the current **local source snapshots** contain no matching original
bookmaker total quotes, not a 0% direction hit rate. It does not exclude
other files, provider receipts or Fly production.

Test on the branch after checkout:
```bash
.venv/bin/python -B -m unittest tests.test_pregame_direction_evidence -v
```
Synthetic tests do not establish real market direction accuracy.

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


## Direction-first mismatch breakdown (new in this branch)

The device census previously showed 33 **unique** settled NBA fixtures with a
fresh original bookmaker TOTAL line. User's original frozen-mean-vs-line
research comparison on those 33: **14 matches vs 19 mismatches**, 42.42%
descriptive regulation-only agreement. No publishing record or official
bookmaker full-game overtime rules were verified; **not live tip/pick ROI**.

The updated census now adds `direction_research` with:
- `confusion_matrix`: `ALT_ALT`, `ALT_UST`, `UST_ALT`, `UST_UST`,
  so false-ALT vs false-ÜST problems can be distinguished;
- `by_original_mean_line_gap`: fixed, descriptive buckets 0–3, 3–7 and
  7+ score points, **not fitted decision thresholds**;
- `by_bookmaker` and `by_score_error_sign`: which side and error sign
  the mismatches occur on; positive score-error originals are **read only**;
- `by_overtime_status`: original regulation-only result with
  known additional OT points distinguished from no OT / missing evidence;
- deterministic mismatch rows sorted by the *original pregame model–line
  distance*, not selected by outcome, so even large-advantage mistakes are
  exposed.

The headline counts **one independent settled fixture only if exactly one
fresh original bookmaker TOTAL quote** is present. Ambiguous multiple
books/lines, push outcomes, model exactly on the line and missing/stale
quotes are separately excluded, **not assumed correct**. No market settlement
profit, calibration, published-pick hit rate or automatic reverse-pick policy
is computed.

To see only the important fields, repeat the command above with
`--summary-only` at the end (after the `--assets` argument). In the output,
start at `direction_research.confusion_matrix`, then
`direction_research.by_original_mean_line_gap`, and the mismatch examples.

No historical snapshots, positive original forecasts, score parameters or
market prices are modified by these read-only queries.

## Actual frozen simulation ALT/ÜST test (optional)

The earlier **42.42% (14 of 33)** statistic compares the *original predicted
mean* to a verified original bookmaker total line and the **regulation-only**
realized total. That is useful diagnosis but it is **not necessarily the model's
actual raw probability direction**, which the original display constructs from
the frozen QMC sample counts (`p_under` vs `p_over`).

For this stronger **read-only** original-input replay, run the exact same
`git show FETCH_HEAD:hybrid_engine/pregame_direction_evidence.py | python ...`
command above, adding both `--summary-only --replay-qmc` at the end.

The replay:
1. Requires an original model snapshot with **exactly one fresh preforecast
   TOTAL quote** and already verified regulation result.
2. Uses the existing `decision_audit.replay_snapshot` + local pinned assets.
   This validates the **original prepared fitted model**, historical input
   availability, frozen algorithm source SHA, unmodified predicted quarter
   means and the **exact original 10,000 QMC score-sample SHA**.
3. Compares raw counts of simulated regulation `total < original_line`
   versus `total > original_line` (and pushes) at that exact line.
4. Reports a separate QMC-direction confusion matrix, difference count
   from the mean-based side, and descriptive agreement to regulation
   results. This replay **does not claim an original published Telegram
   decision**, bookmaker-certified settled win, validated confidence, or
   future predictive success. The replay is performed after labels are
   known, but every score-sample digest is checked against the archived
   original preforecast digest, preventing outcome-dependent refitting.

On any SHA, source-clock or QMC sample mismatch it fails closed rather than
printing a direction accuracy. Positive originals are never overwritten;
no new sample distribution or market line is installed. On mobile the
SHA-verified 10,000-sample replays for 33 fixtures may use more CPU time
than the original quote-only census.

The tested headline of 14/33 is not promoted as the official direction hit
rate until original published direction and exact bookmaker overtime
settlement evidence are present.

## Paired original QMC vs observed bookmaker direction probability (2026-11-21)

The optional `--replay-qmc` audit additionally reads only **the same pinned
native price observation** that yielded each authentic original pre-forecast
TOTAL line. It computes, on the exact same 33 eligible fixtures:

- Original QMC regulation-only conditional `P(ÜST | no push)`, from the
  SHA-verified 10,000 fixed simulation paths.
- Timestamped bookmaker **proportional no-vig** ÜST price-implied fraction,
  from both original decimal odds (`1/decimal_price` normalized).
- Original realized regulation-only ÜST indicator for that identical line.
- Separately for original QMC and price reference: paired **Brier score**,
  **binary log loss**, and mean raw implied ÜST probability; and actual
  regulation ÜST fraction.

For Brier and log loss **lower is better**, but this is only a small,
historical, *non-random, already used* cohort, the bookmaker overtime
settlement contract is not independently verified, and no bookmaker price is
proof of the true betting event probability. Results are **diagnostic only**,
not validated prediction accuracy or permission to tune a market edge.

No arbitrary score correction, no reverse-the-model policy, no P95 widening,
no outcome-dependent cutoff selection, and no modification of original
positive signed-error forecasts. To collect actual results on UserLAnd run
`--summary-only --replay-qmc` with the same pinned report and source paths.

## 2026-11-21: prioritize pre-forecast feature responsiveness, not speculative price corrections

User-device original QMC selected-side results on 33 fixtures:
- QMC said ALT in 21: mean raw selected ALT probability 56.02%, original
  result matched 8/21 (38.10%), mismatch 13/21.
- QMC said ÜST in 12: mean raw selected ÜST probability 56.94%, matched
  6/12 (50.00%), mismatched 6/12.
- Market original no-vig selected-side mean near 50% in both groups; this
  is **not a reliable betting edge** and these probabilities are uncalibrated.
- Bad-confidence examples include Wizards–Grizzlies (QMC ALT 68.96%,
  actual regulation ÜST), Pelicans–Warriors (QMC ÜST 67.57%, actual ALT).

**Next read-only candidate diagnostic**: compare the QMC original raw direction
against the **historical preforecast raw-scoring cross mean** retained in the
existing frozen input profile. The reference is named
`PREGAME_LAST_N_FOR_AGAINST_CROSS_MEAN`. The code enforces original exact
fixture SHA, model digest, generated-at clock and reference fields
`published_forecast=false`, `fitted_on_outcome=false`,
`eligible_for_live_performance=false` before use. It was **never published
as a forecast**, and no new original forecasts are created.

Run the command shown above adding `--history-summary-only` (instead of
`--prob-summary-only`):

```bash
git fetch origin feature/pregame-direction-evidence-20261121
git show FETCH_HEAD:hybrid_engine/pregame_direction_evidence.py |
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B - \
  --report "$HOME/zeynal-test-isolated/data/quality-phase924/reports/quality-4b2be633584586dd439fcfc3f6414001217ac4d9f8c60a9d8fc68c6e17a7a2f1.json" \
  --ledger "$HOME/zeynal-test-isolated/data/live-nba/nba-hybrid.sqlite" \
  --assets "$HOME/zeynal-test-isolated/data/live-nba/assets" \
  --history-summary-only
```

Report separates exact pair count, QMC-only correct, reference-only correct,
both correct/both wrong, prefit age bands 0-3/3-7/7+ days and count of fresh
games after fit 0/1-4/5+, and all missing original input profiles. **This is
a history-only research reference, not evidence to select a better model
based on 33 already-known finals.** It does not establish any causal effect
of model fit age, omitted injury or pace; those effects must be forward tested.
Positive original signed-score errors are inspected only as immutable
outcomes on original lines and are never overwritten, refitted, shifted or
published as revised historical predictions.

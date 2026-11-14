# Hybrid NBA market, roster and evidence integration — acceptance contract

Status: DEVELOPMENT ONLY. No production deployment or model calibration claim.

## Existing verified gaps
- `hybrid_engine/live_nba.py` creates a Bayesian/QMC forecast but marks `verified_pace`, `injuries`, `lineups`, `rotation` and `market` as missing.
- `hybrid_engine/markets.py` supports per-line conditional raw probabilities and independently audited exact-line calibration, but is not called by the live NBA service.
- `hybrid_engine/observed_markets.py` parses observed ESPN bookmaker totals/spreads with timestamps; the parsed market's settlement scope is `UNKNOWN`, so it cannot be represented as equivalent to the model's `REGULATION_ONLY` predictions.
- `hybrid_engine/confidence.py` requires disjoint calibration, prior model error audit, verified roster/rotation and model agreement. Missing evidence must return `NOT_ESTIMABLE`.

## Implementation order
1. **Read-only market observation.** Bind ESPN odds to canonical fixture ID, team IDs, start timestamp, provider, source URL, observed/ingested timestamps and native quote digest. Reject started games, stale or conflicting quotes. Do not create synthetic bookmaker lines.
2. **Research display.** Show observed bookmaker, market, line, timestamp, model's *regulation-only conditional* under/push/over probabilities, and explicit `NOT_COMPARABLE` when settlement scope is unknown. Never label a raw probability as a verified confidence index, edge or recommendation.
3. **Verified roster feed.** Add an independently sourced, timestamped injury/status and probable-starter snapshot. Distinguish official inactive, doubtful, questionable, probable and confirmed starter. Do not infer a player's availability from absence in a source. Apply minutes/rotation changes only when team and player identities, report time and model feature provenance are validated.
4. **News and analyst evidence.** Store official/team reports separately from editor opinions; deduplicate by event, enforce publication-before-prediction, keep attribution and do not turn subjective claims into quantitative weights without out-of-sample evidence.
5. **Calibration and quality.** Compare pre-tipoff frozen predictions against official final results on a time-ordered, out-of-sample audit. Show MAE, RMSE, coverage and Brier by market; use the existing exact-line calibration gates. Only display confidence index after all required gates pass.
6. **Telegram end-to-end.** Verify `/analyze`, `/accuracy NBA`, and `/compare NBA <fixture_id>` on the dedicated test bot with actual Telegram receipts. Preserve existing prematch snapshots. Keep production FAZ13 unchanged until explicit promotion.

## Non-negotiable acceptance tests
- Missing odds => market unavailable; no fabricated bookmaker, line, edge or confidence.
- An ESPN quote with unknown overtime/settlement rules cannot be compared to regulation-only totals as an actionable edge.
- Missing/uncertain roster => uncertainty reported; no asserted confirmed starting five.
- News after prediction cutoff never affects an archived prediction.
- Existing archived predictions are never overwritten or recomputed after tipoff.
- The same fixture's historical truth never leaks into its prematch model features.
- Research failures cannot silently fall back to a production model while retaining the hybrid label.
- No Fly.io deployment, production volume modification or main-branch merge as part of this branch.

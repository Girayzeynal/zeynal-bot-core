# Development validation — 2026-11-04

Branch: `feature/nba-command-20261104`; draft PR #12 targets
`fix/faz22-force-guard-20261104`. No merge or production deployment performed.

## Decision integration

Commit `45f84db` makes FAZ23 respect FAZ22's final confidence, explicit
unlocked state, risk/uncertainty filters and approved segments. Invalid or
nonfinite numbers, missing gate metadata and FORCE signals cannot become
normal strong signals. A segment rejected by FAZ22's simulation-dependent
threshold cannot reappear under FAZ23's lower edge threshold.

The five new regression methods reproduced 31 failing subcases and two errors
before the fix. Afterwards all 358 regression tests passed. These are synthetic
contract tests, not evidence of predictive accuracy or real-data calibration.

## Provider transport and live checks

Initial ESPN checks failed: team identity was unresolved and the multi-date
check returned RuntimeError. The environment requires an HTTP proxy. A direct
request using the environment proxy returned HTTP 200, while the owned aiohttp
sessions ignored proxy variables. Enabling `trust_env=True` fixed live access.
Caller-injected sessions retain their existing lifecycle and configuration.

Three session regression methods include two failures reproduced before the
transport fix. All **361 tests** passed after the fix (Python 3.12 locally;
GitHub CI is configured for Python 3.11).

Successful read-only commands after the transport fix:

```sh
python -m providers.espn_multi_date_smoke 20261101 20261102 20261103
python -m providers.espn_history_gate_live_smoke
```

- Multi-date check: 19 unique completed fixtures, distributed 4 / 15 / 0.
  No duplicate fixture identities, date mismatches or conflicting records were
  reported. November 3 returned an empty response: it supplies no completed-game
  coverage and is not evidence of a populated date's completeness.
- History check at `2026-11-04T16:00:05.127720+00:00`: San Antonio Spurs and Utah
  Jazz each supplied seven accepted regular-season historical score records.
  Both passed the score-history gate. Both failed the pace-dependent baseline
  gate with `pace_unavailable`; `production_ready` remained false.
- These checks validate one provider's response against internal contracts.
  Independent cross-provider score reconciliation has not been performed.

## League and release gaps

| League | Current evidence | Remaining gates |
| --- | --- | --- |
| NBA | Registered profile; decision gate tests; live ESPN scores as above | Authentic possessions/pace, point-in-time baseline binding, immutable pre-tipoff prediction/outcome sample, walk-forward calibration |
| EuroLeague | Registered profile; upstream confidence/lock regression coverage | Live fixture/season/team identity, historical score and pace feeds, full FAZ13 pipeline validation, calibration |
| EuroCup | Schedule configuration only; no registered analysis profile | Verified provider mapping, history, measured profile and full pipeline validation |
| Other configured leagues | Schedule configuration only | Per-league provider verification, history, profile and calibration |

Schedule IDs and a registered `LeagueProfile` do not establish provider accuracy
or empirical calibration. Unsupported leagues continue to fail closed rather
than inherit another league's parameters. No new profiles were fabricated.

No production prediction ledger was supplied. Therefore no verified accuracy,
MAE/RMSE, Brier score or calibration claim is made. Existing Monte Carlo
regressions pass as part of the full suite, including reproducibility,
probability conservation, marginal variance and covariance checks; the model
remains regulation-only. See `calibration-data-contract.md` for ledger gates.

At the time of this record, GitHub CI run 41862875926 for `45f84db` was queued;
local success must not be substituted for that CI result.

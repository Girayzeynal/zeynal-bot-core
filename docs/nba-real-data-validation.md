# Real NBA finals audit and calibration availability — 2026-11-04

Initial GitHub verification: PR #12 open/draft, unmerged, head
`e3cc9085a895c15d740a7895573d99d9975fb2a9`, branch
`feature/nba-command-20261104`. Both `unit-tests` and `docker-build` succeeded
in push run 41909529217 and PR run 41909536412. Base remains
`fix/faz22-force-guard-20261104`; no main-branch change was made.

## Actual source observations

Fetched ESPN scoreboard for 2026-11-03: zero events. Fetched 2026-11-02:
15 completed NBA games. Fetched all fifteen fixed ESPN summary routes and
independently replayed their final-status/identity/time/orientation/score
parsers against scoreboard records. All fifteen agreed. This is cross-route
consistency within ESPN, **not an independent provider confirmation**.

NBA CDN schedule and Basketball Reference November schedule returned HTTP 403.
Neither supplied accepted data; no bypass or paid provider was used. Their
failure does not validate or invalidate ESPN scores.

Each accepted result retains ESPN fixture/team IDs, canonical NBA team IDs,
UTC start, integer final score, observation time, scope and replayed pace
calculation. All fifteen box scores supported the existing 48-minute normalized
`FGA + 0.44*FTA - ORB + TOV` estimate (OT duration handled by its validator).
These are box-score estimates, not measured possessions. The trimmed regression
fixture deliberately omits stats and verifies that missing pace remains null.

The first replay stopped at the unmapped source abbreviation WSH. The downloaded
record identifies ESPN team 27 as Washington Wizards; the explicit WSH-to-WAS
alias resolves it to the existing NBA team ID 1610612764. It does not guess
numeric provider fixture IDs or use fuzzy team names.

Cross-provider counting uses resolved NBA team IDs plus exact start. Same
fixture observations with different provider IDs count once. Disagreeing
scores/orientation, reused provider IDs, unknown canonical teams and conflicting
same-team starts are rejected. A synthetic second source exercises this gate;
no actual second-source verification is claimed. Different claimed start times
need independent identity resolution, not an automatic fuzzy match.

## Forecast and calibration limitations

There are **no original pre-tipoff FAZ13/22/23 forecasts or timestamp-available
input snapshots for these fifteen completed games**. Current downloads cannot
be retroactively labeled available before their starts. No historical forecast
was fabricated, no observation was backdated and no retrospective replay was
presented as measured accuracy.

The separate existing original NBA research projection (401909924, BOS–MIL)
starts 2026-11-05 00:30 UTC. Its strict bound report still has one original
prediction, zero verified completed outcomes and null metrics. It cannot be
paired with these fifteen unrelated results. Original injuries and pre-tipoff
rosters for the completed sample are unavailable; current summary rosters do
not prove historical availability.

Accordingly FAZ13 score MAE/RMSE and FAZ22/23 stage comparisons remain unavailable.
No archived original win probabilities were found for these finals, so Brier,
log-loss and probability calibration are null as well. Heuristic confidence is
not a win probability. Regulation-only Monte Carlo probabilities must not be
scored against overtime-inclusive finals. Existing synthetic metric tests verify
calculations but cannot establish real-data accuracy.

## Reproducibility and scope

Raw fetched inputs and observation manifest are preserved locally under
`/workspace/scratch/nba-validation-20261104`. The committed evidence report
contains file SHA256 values, endpoint addresses, exact result and pace inputs,
and explicit missing-data/metric statuses. Hashes detect local corruption;
they are not provider signatures. Re-run offline:

```sh
python -m nba_real_data_validation /workspace/scratch/nba-validation-20261104
```

This command is a dated research audit, not a production downloader. The
canonicalization helper assumes adapters have already validated provider data;
it is not itself proof of authenticity. Existing ledgers and forecasts were
preserved. Source-bound prospective collection, independent source access,
archived injuries/rosters and sufficient calibration samples remain open.
No deployment, merge, messaging, paid service or secret change occurred.

Local validation: 541 regression tests passed (19.762 seconds), including six
new tests for a trimmed real final, explicit Washington mapping, absent pace,
provider-alias deduplication, score/time/identity/orientation conflicts, reused
IDs, same-team start conflicts, unknown teams and boolean scores. Compilation
and diff checks passed. No evidence of calibrated real-game accuracy was found.

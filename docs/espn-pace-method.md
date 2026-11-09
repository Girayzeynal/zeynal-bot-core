# ESPN historical pace estimate

ESPN scoreboards provide final scores, not possession counts. The free NBA
summary endpoint also supplies team box-score totals. `espn_boxscore_pace.py`
derives an explicitly labeled **estimate**, not a measured possession count:

```
team_possessions = FGA + 0.44 * FTA - ORB + totalTurnovers
game_possessions = (home_possessions + away_possessions) / 2
pace = game_possessions * 48 / (48 + 5 * overtime_periods)
```

The 0.44 free-throw coefficient is a modeling assumption. `totalTurnovers`
includes team turnovers; substituting individual-player turnover totals would
undercount. Neither scores alone nor a constant 100 supplies possession data.

Before calculating, the parser reconciles summary event ID, exact start time,
home/away team IDs and final scores against the parsed scoreboard event. It
requires regular-season final status, NBA period lengths, matching complete
period-score arrays for both teams, and score reconciliation from made field
goals, made threes and free throws. Missing or duplicate statistics, impossible
shot totals, inconsistent duration and identity mismatches return no estimate.
There is no default pace. The original raw counts, method and source URL are
returned for auditing. Source labels are not independent authentication.

## Live evidence, 2026-11-04

Read-only command:

```sh
python -m providers.espn_pace_live_smoke 'San Antonio Spurs' 'Utah Jazz'
```

At `2026-11-04T16:07:39.571176+00:00`, all seven historical score records per
team reconciled with summary totals. The two histories share two fixtures, so
these represent **12 distinct games**, not 14 independent games. Fixture
`401909890` has five periods; its pace estimate is approximately 96.7245 per
48 minutes after a 53-minute game. Results and source inputs are retained in
`evidence/espn-pace-20261104.json`.

The trimmed fixture `tests/fixtures/espn-summary-401909903.json` preserves the
relevant source fields retrieved from
`https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event=401909903`.
It yields an estimated pace of 94.4, with team possession estimates 94.36 and
94.44; made-shot totals independently reconcile to the 97–108 final score.

Seven new tests cover real fixture reconciliation, synthetic overtime duration,
identity/time/scope mismatches, missing and malformed counts, period evidence,
nonfinal status and transport absence. Full local suite: **368 passing tests**.

These checks establish internal source consistency, not accuracy against
play-by-play possessions or a second provider. The existing measured-pace
history gate remains closed: adopting an estimate requires explicit policy,
and the live smoke intentionally reports `production_ready: false`. No
prediction was backfilled and no production data was written. Predictive
accuracy and walk-forward calibration remain unestablished.

GitHub CI for prior commit `0b9ca4f`, run 41863468012, was still queued for both
`unit-tests` and `docker-build` when checked before this work.

## Subsequent module: baseline adapter

The old `fetch_team_recent_games` path supplied a constant `100.0` even when
no possession data existed. It now returns `pace=None` by default; an integration
test confirms that the real baseline bootstrapper writes no such score-only
records. It also uses the shared completed-event reader to exclude conflicting
duplicates and preserves source fixture ID and exact timestamp precision.

Research callers may explicitly construct
`ESPNAdapter(allow_estimated_pace=True)`. Each accepted summary then supplies
the derived pace, `BOX_SCORE_ESTIMATE` kind, raw calculation inputs and method
as its source. Missing summaries still return no pace. Production construction
does not enable this option. Five additional regressions verify default gating,
explicit adoption, missing evidence, invalid options and baseline-store refusal.
Full local suite after this integration: **373 passing tests**, compilation and
`git diff --check` clean.

Durable point-in-time evidence for retained game rows has subsequently been
implemented; see `pace-evidence-storage.md`. Binding those inputs immutably to
each prediction, comparing estimates against independently counted possessions,
and collecting a prospective prediction sample remain required before production
or verified calibration. No existing baseline files were rewritten or silently
relabeled.

# EuroLeague / EuroCup 2026–27 source audit

Prior commit `92fdc0c`: GitHub CI run 41872672965 completed successfully.

## Verified source routes

The unauthenticated public Live API responded at:

```
https://api-live.euroleague.net/v2/competitions/{E|U}
https://api-live.euroleague.net/v2/competitions/{E|U}/seasons/{E2026|U2026}
https://api-live.euroleague.net/v2/competitions/{E|U}/seasons/{E2026|U2026}/games
https://api-live.euroleague.net/v2/competitions/{E|U}/seasons/{E2026|U2026}/games/{gameCode}
https://api-live.euroleague.net/v2/competitions/{E|U}/seasons/{E2026|U2026}/games/{gameCode}/stats
```

Competition metadata reported `E / Euroleague` and `U / Eurocup`; season
metadata and each game consistently reported `E2026 / EuroLeague 2026-27` or
`U2026 / EuroCup 2026-27`. These are source-reported mappings, independently
cross-checked across that provider's routes, not a second-provider confirmation.
FIBA EuroCup is explicitly a different competition and is rejected by this
adapter. No API-Sports numeric ID was inferred from these codes or changed.

Exploratory v1 routes returned 404. An old `live.euroleague.net` box-score route
returned HTTP 200 with an HTML not-found page. Neither was accepted as JSON
data or used as a fallback. The new adapter rejects non-JSON/error responses,
uses environment proxies with bounded timeouts, and closes only owned sessions.

## Identity and score gates

- Require explicit league and starting season year. Validate competition code,
  season code/year/label, season-scoped fixture identifier and source UUID.
- Use confirmed `utcDate` with explicit UTC timezone. Never infer UTC from a
  local date or timezone offset field. Reject virtual/ambiguous team identities.
- `gameStatus: Confirmed` also appears on unplayed games. Only `played: true`,
  a past start, decisive integer score and complete consistent period totals
  supply a played-score candidate. It is not a final-buzzer timestamp.
- Overtime keys must be contiguous and agree for both teams. Each overtime
  requires a preceding tie. Duplicate/conflicting identities and reused UUIDs
  are excluded; raw, accepted, duplicate, conflicting and invalid counts reconcile.
- A collection whose declared total differs from its returned length is
  rejected rather than treated as a complete season.

## Box-score pace evidence

The stats route supplies team totals and player/team components. The adapter
checks player IDs, club codes and seasons, then reconciles player-plus-team
totals, points and made shots against the identity-bearing game detail. Team
turnovers and offensive rebounds are included; absent values never become zero.

```
possessions = FGA + 0.44 * FTA - ORB + total_turnovers
pace = mean(home_possessions, away_possessions) * 40 / game_minutes
game_minutes = 40 + 5 * overtime_periods
```

Totals must contain the corresponding full game-clock seconds for both sides.
The free-throw coefficient is a modeling assumption; these are labeled
`BOX_SCORE_ESTIMATE`, not measured possessions or empirically calibrated pace.
The stats payload lacks a root fixture ID, so its binding relies on the fixed
request route plus matching game detail, clubs/seasons, points and duration.

Research observations retain the minimal original source fields, calculation
inputs, observation time, source URLs and a digest. `replay_pace_evidence` checks
them offline. No player biographies or images are needed. The digest detects
corruption; it is not a source signature.

## Live checks and tests

```sh
python -m providers.euroleague_live_smoke --year 2026 \
  --leagues EUROLEAGUE EUROCUP --samples 2
```

The retained report is `evidence/euroleague-eurocup-audit-20261104.json`.

| Source-reported season | Parsed fixtures | Played-score candidates | Unplayed | Box-score samples |
| --- | ---: | ---: | ---: | ---: |
| E2026 | 380 | 90 | 290 | 2 reconciled |
| U2026 | 224 | 85 | 139 | 2 reconciled |

No invalid or duplicate/conflicting records were observed in these collections.
Samples were the latest played game and a distinct overtime game per league:
`E2026_87` (40 min), `E2026_66` (45 min), `U2026_91` (40 min), `U2026_60` (45 min).
Only these four sampled box scores were checked; this does not establish
box-score coverage of all 175 played-score candidates.

Two additional trimmed real fixtures exercise `E2026_1` and `U2026_12` offline.
Twenty new tests cover identity/season/UTC validation, unplayed games, source
statistics, duration, overtime, roster conflicts, catalog completeness,
duplicate rejection, evidence replay and HTTP/session behavior. Full local
suite: **429 passing tests**; compilation and diff checks passed.

## Integration limits

This adapter is read-only and is **not registered with production baseline
bootstrap or Telegram analysis**. NBA's ledger continues to reject other
providers/leagues. EuroCup still has no analysis profile; none was fabricated.
The existing EuroLeague profile remains registered but is not empirically
validated by this source audit.

Source-specific baseline storage and per-team availability checks are now
implemented; see `euroleague-baseline-binding.md` for passing and incomplete
live cases, including the HTTP 429 limitation. League-specific
fixture/prediction binding, prospective calibration and independent
possession/source reconciliation remain open. No verified accuracy or
production readiness is claimed. No
merge, deployment, paid service or secret change occurred. The existing NBA
research fixture was separately checked and still returned `awaiting_tipoff`.

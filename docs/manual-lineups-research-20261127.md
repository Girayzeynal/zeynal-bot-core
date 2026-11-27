# Lineups manual projection research

License: https://www.lineups.com/about/license/ permits personal non-published,
non-commercial use and manually copying CSV where provided; it explicitly
prohibits scraping. Projected minutes page:
https://www.lineups.com/nba/nba-player-minutes-per-game/.
The page exposes a projection table, but a native CSV schema, source publication
clock, API license and free API access have not been established.

This CLI never calls Lineups or ESPN. It accepts a **user-normalized** UTF-8 CSV
with header `player,team,opponent,projected_minutes`, using the full official
team names (not assumed abbreviations), both sides of one fixture, decimal
minutes, no invented zero rows. It is not a parser for any native export.
Use only personally obtained data under the license. Do not put real source
rows into the repository. Optional `--home-roster` and `--away-roster` must
point to existing content-addressed ESPN roster receipts, within 300 seconds
of local import. Both or neither are required. Missing roster rows remain
unknown; the 240-minute difference is a diagnostic, not a normalization.

```sh
python3 -m hybrid_engine.manual_lineups_research --personal-use \
  --ledger PATH_TO_ISOLATED_NBA_LEDGER --fixture ESPN_EVENT_ID \
  --csv PATH_TO_MANUAL_CSV
```

Optional `--output-directory PATH/manual-lineups-research` saves a separate
immutable local research observation. No source publication time or independent
fixture identity is claimed from the user transcription. Even with matched
player identities, records are never fit-eligible, never written to MinutesArchive,
never used for active score predictions, and never claimed as actual minutes.
The exact archived forecast is verified read-only, and new capture is refused
at T-300 or later. No automated fetcher, API keys, player effect or deployment.

Future gates: authorized feed or explicitly permitted manual sample; independently
verified game/date and source time; native injury and roster identity; full
rotation coverage; paired out-of-sample minute and score comparison. No
promotion merely because a file was imported.

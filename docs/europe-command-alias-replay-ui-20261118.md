# European command aliases and archived presentation

This change is isolated from NBA inference and the prepared European models.
It targets `feature/critical-integrity-audit-20261118`; it does not merge to
`main`, deploy Fly.io, rotate secrets or change original forecasts.

## Confirmed causes

The native season participants already contain the clubs. The strict identity
registry accepts source names and abbreviations, not arbitrary variants. The
preserved, SHA-verified EuroCup season-club receipt in
`docs/evidence/eurocup-city-alias-phase951-20261117.json.gz` reproduces all five
reported missing variants with the previous registry. `JL Bourg` already works;
the missing name in that pair is `Napoli Basket`.

| Command variant | Native club name | Provider club ID |
| --- | --- | --- |
| Derthona Basket | Baglietto Derthona Tortona | TRT |
| Rigas Zelli | Riga Zelli | RIG |
| Frankfurt Skyliners | Skyliners Frankfurt | FRA |
| Reyer Venezia | Umana Reyer Venice | VNC |
| Napoli Basket | Napoli Basketball | NAP |

`EuropeanService.render()` is the source of the reported long Beşiktaş output,
including `ARŞİV REPLAY`. Its score and original production timestamp describe
an existing forecast. The isolated bot's outer presenter normally converts this
report to a compact summary with six buttons. The pasted output alone does not
prove whether that device ran an older process, exceeded the presentation
deadline, or used another call path. The exact device forecast with SHA
`fbaa308e9447d546431707f767114db41309f5d7e47d71d61bd52f8e0177dbce`
is not available in this Cloud checkout, so this report does not claim to have
reproduced that specific device failure.

One concrete presentation cost was confirmed in code: displaying one archived
forecast reread and validated *every* publication and its source assets. The
presenter now directly locates the requested SHA and its matching first-publication
slot, verifies the payload, original clocks, publication kind and all input assets,
then validates its original source fixture. It writes no index or archive data.

## Changes and safeguards

- `europe_command_identity.py` adds an explicit command-boundary adapter. A
  curated alias requires the correct league, a current verified season member,
  the native provider code and an exact native name anchor. Native conflicts
  are refused. There is no fuzzy search, substring search or word sorting.
- Newly introduced aliases do not become historical participant evidence.
  Archived lookup uses an alias *at the time of the current request* against
  the original source. It does not assert the alias was known at forecast time.
- Archived lookup preserves date, league, home/away direction and unique club
  identity. Restart and busy-lock paths retain the same original forecast.
- The summary, periods, ranges, market, roster and audit buttons use archived
  projections and bands. Missing current market/injury evidence remains explicit.
- `/test euroleague` and `/test eurocup` now identify the running alias and
  presentation versions and the last presentation outcome. An exception still
  exposes an explicit `EUROPE_UI_UNAVAILABLE` message, preserving the plain archive.
- The launcher and CI allow this isolated feature branch. The 36-hour automatic
  capture window and final 15-minute no-new-forecast rule are unchanged.

The native participant parser and snapshots, identity core, `europe_live.py`,
`europe_models.py`, 27 V1 research source pins and 13 V2 pins remain unchanged.
No production database or UserLAnd archive was accessible or modified here.

## Validation

`tests/test_europe_command_identity.py` uses the preserved native club receipt
for identity tests and explicitly synthetic games for inference/replay tests.
It checks all reported pairs, native conflicts, code/name binding, league and
season isolation, alias cutoffs, NBA identity, wrong dates/directions, restart
and post-tipoff replay without network, simulation or archive changes.

`tests/test_europe_premium_ui.py` additionally runs the reported short commands
through real PTB handlers with a synthetic Bot API, checks all six callbacks,
busy-lock replay, selective publication reads and tampered publication clocks.
These are not external Telegram delivery tests. Full-suite and resource results
are recorded in the PR and accompanying validation evidence.

## UserLAnd and real Telegram checks

Stop only the isolated test poller with Ctrl+C, then in Ubuntu:

```bash
cd ~/zeynal-hybrid-844
git fetch origin feature/europe-alias-replay-ui-20261118
git switch feature/europe-alias-replay-ui-20261118
bash scripts/run_isolated_test_bot.sh
```

Send each of these as a **separate Telegram message**, not in the Ubuntu shell:

```text
/test eurocup
/test euroleague
/analyze EuroCup 2026-11-18 Derthona Basket vs Rigas Zelli
/analyze EuroCup 2026-11-18 Frankfurt Skyliners vs Reyer Venezia
/analyze EuroCup 2026-11-18 JL Bourg vs Napoli Basket
/analyze EuroLeague 2026-11-18 Besiktas vs Real Madrid
```

Expect `EUROPE_COMMAND_ALIASES_V1` and `EUROPE_COMPACT_ARCHIVE_V2` in the
diagnostic output. After an analysis, `/test` should show `READY` for that league.
The Beşiktaş archive must retain 90.36–94.59 and its original 17 November timestamp
if it is the same original SHA reported by the user. Check all six buttons.
No pre-existing record means explicit abstention after the cutoff, not a new
retrospective prediction. Also check `/predictions`, `/compare` and `/accuracy`
for each league and an unchanged NBA archive command.

External Telegram delivery remains **NOT_VERIFIED** without isolated test bot
credentials. The user-device Beşiktaş replay remains **NOT_VERIFIED** until
tested on the archive that contains that exact SHA. No model accuracy improvement
or production-readiness claim follows from an identity/presentation fix.

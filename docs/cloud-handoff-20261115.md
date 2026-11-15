# Codex Cloud handoff audit — 15 November 2026

## Branch and scope

Started at `fea79f6e9ee8317ee8f3fa0e7b82c6c867117f59` on existing branch
`feature/hybrid-market-roster-evidence-20261114`, PR [#89](https://github.com/Girayzeynal/zeynal-bot-core/pull/89).
Its base remains `feature/hybrid-telegram-optin-20261114`; it does not target main.
PR #84 was already merged when this work started. The Cloud checkout was still
at `b897cee` on its old research branch, with no uncommitted changes. Existing
GitHub development was fetched and preserved; no separate replacement project or
branch was created.

The starting unit suite passed **755/755**. Existing settlement (`cb39d41`,
`fea79f6`), single-fixture compare, compact UI, source evidence and staging helpers
were reused. All **46 pre-existing files under docs/prospective and docs/evidence**
remain byte-for-byte unchanged. All six named SHA-pinned model/data sources and
`main.py` are unchanged. See [verification manifest](handoff-verification-20261115.json).

## Root cause: Indiana–Philadelphia

A fresh ESPN native scoreboard identifies **401909985**, **Philadelphia 76ers
(home) vs Indiana Pacers (away)** at **2026-11-15 18:00 UTC / 21:00 TSİ**, explicitly
`STATUS_SCHEDULED`. The reported command used the opposite home/away order.
Refusing to predict was correct; the missing behavior was an explanatory answer.

The isolated wrapper now verifies both intersecting scoreboard partitions,
native identities, document hash, source binding and freshness. It explains
reversed teams or another TSİ calendar day and offers an explicit corrected
command only for a future scheduled match. It never retries with changed input
or promotes a diagnostic into an authorized prediction. Missing source evidence
is distinguished from a verified empty candidate set. The six model pins were
not changed to implement this fix.

Correct command, while that fixture remains scheduled and unstarted:

```text
/analyze NBA 2026-11-15 Philadelphia 76ers vs Indiana Pacers
```

In live isolated mode `/nba YYYY-MM-DD` now includes ESPN IDs and ready-to-copy
commands only for future scheduled fixtures. The new opt-in `/euroleague` listing
uses official identities, TSİ dates and the same 30-minute/24-hour capture window.

## Real native-source NBA capture

The frozen prepared NBA model was loaded through the existing pinned staging
helper. A real-source call with the reversed matchup abstained; the corrected
call produced and committed one forecast, with no fitting:

| Field | Value |
|---|---|
| Fixture | Philadelphia 76ers – Indiana Pacers, ESPN 401909985 |
| Expected regulation score | 112.4811443306 – 109.3077737074 |
| Total / home margin | 221.7889180380 / +3.1733706232 |
| Method | RQMC_HALTON, 10,000 paths, seed 20261112 |
| Model | ELITE_HYBRID_NBA_BAYES_QMC_RESEARCH_V1 |
| Generated | 2026-11-15T11:14:05Z / 14:14:05 TSİ |
| Tipoff | 2026-11-15T18:00:00Z / 21:00 TSİ |
| Snapshot SHA-256 | 30e32e06461cc83123fcc99b46a79d9dbaf1be3b0f2c5ebc6448341ed25a5343 |
| Calibration | NOT_CALIBRATED; no validated confidence index |

The original snapshot and all native assets/SQLite commit proof are preserved in
[the new capture capsule](evidence/handoff-nba-prospective-20261115.tar.gz), with a
[readable immutable snapshot](prospective/handoff-20261115/nba-30e32e06461cc83123fcc99b46a79d9dbaf1be3b0f2c5ebc6448341ed25a5343.json).
A second real-source request returned `new_record=false`, the same snapshot SHA
and unchanged commit proofs. SQLite: `ok`, one confirmed snapshot, zero finals.
No match outcome or predictive success is claimed for this upcoming game.
Native-process peak RSS was 77.55 MiB; that separate real-network run was not a
hard-cgroup resource test.

## Results and reporting fixes

- Settlement checks native URL/provider/document digest, integer clocks,
  freshness and post-tipoff final timing **before writing**. Forecasts are
  validated read-only first. Future-only cohorts cause no result downloads.
- Multiple games, retries, wrong identities, incomplete periods and overtime
  are regression-tested. Normal-time metrics exclude extra periods.
- Independent serial collectors prevent an EL source/schema/disk failure from
  skipping the NBA collector. Failures record fixed error types without raw
  API exception/token text; the 300-second default remains.
- `/compare NBA` safely handles archive/database errors. It still auto-selects
  only one unique fixture, never arbitrarily chooses among multiple matches.
- Live reports additionally expose bias, total RMSE, 1Q–4Q/1H–2H errors,
  raw three-class Brier/log loss/calibration bins and realized quantile coverage
  when those fields actually exist. Missing probabilities/intervals stay missing.
  These are descriptive measurements; no calibration fit or confidence score
  is created. Report messages split at a UTF-16 budget instead of truncating.
- Forecast scans are capped at 1,000 records, 512 KiB/payload and a query deadline.
  Existing native finals and original forecasts are never rewritten.

## EuroLeague bridge and measured forward results

`--forward-euroleague-directory` now connects the existing ForwardRegistry to
Telegram analysis and reports. It first reuses the earliest saved forecast,
keeping original clocks and sample-derived intervals. The old five-match replay
route stays intact. A new capture requires one fresh official matching fixture,
no target training overlap, all available history before inference, a second
fixture check and a durable publication before tipoff. It reuses the frozen
Bayesian coefficients and existing Faz13/possession components; it is not a
trained ensemble. No new EL match was captured in this audit: the official
schedule had no eligible fixture in the next 24 hours. Actual new-match EL
Telegram delivery therefore remains unverified; the bridge has command/runtime
and native-payload regression coverage, not that real E2E claim.

The three **13 November** forward records were settled against fresh official
finals. All existing forecast bytes remained unchanged:

| Match | Bayesian total | Faz13 total | Actual regulation score / total |
|---|---:|---:|---:|
| Anadolu Efes – Virtus Bologna | 172.70 | 173.20 | 103–91 / 194 |
| Panathinaikos – FC Barcelona | 169.58 | 170.70 | 74–76 / 150 |
| ASVEL – Besiktas | 179.91 | 179.95 | 91–95 / 186 |

| Metric, same 3 fixtures | Bayesian/QMC | Faz13 MC |
|---|---:|---:|
| Team MAE | 7.8282 | 7.9250 |
| Team RMSE | 9.1860 | 9.4188 |
| Total MAE | 15.6563 | 15.8500 |
| Margin MAE | 6.6629 | 6.5500 |
| Brier, home/tie/away, regulation | 0.54403 | 0.54934 |
| Log loss | 0.76195 | 0.77430 |

Bayesian total P25–P75 coverage: **1/3**, Wilson95 **[0.0615, 0.7923]**.
P05–P95: **3/3**, Wilson95 **[0.4385, 1.0000]**. These intervals assume independent
games and are not corrected for shared teams; three matches on one TSİ day cannot
establish calibrated coverage or superiority. Model-difference confidence
intervals are withheld for insufficient sample/day clusters. Nothing was fitted
on these outcomes. The old five-match descriptive cohort remains separate.
Full period errors/coverage/native receipts: [result audit](evidence/handoff-el-results-20261115.json.gz).

Per-forecast outcomes now support multiple research versions without overwriting
older results; reports use **FIRST_ISSUED_PER_FIXTURE** to avoid inflating the
cohort. Every read replays the outcome against its pinned native source instead
of trusting a recomputed local result hash. Forward publication reads also
validate source/generation/snapshot/archive clocks and PREMATCH classification.

## Telegram presentation, markets and evidence

Existing buttons are retained. Summary adds original generation/model and
sample-derived P50/P25–P75/P05–P95 plus half scores when available. Detailed views
continue to use frozen values. Long detail sections split into bounded messages.
Market assets must match their content hash and remain inside the isolated asset
folder. Existing observed lines remain **NOT_COMPARABLE** where overtime and
settlement rules are unknown: no invented line, direction, edge or confidence.
Roster evidence remains display-only, fixture/time gated; no verified lineup,
rotation or player-impact feed is claimed. Relative quarter-score labels are
explicitly distinguished from measured possessions/pace.

## Tests, resource scope and Telegram evidence levels

- Baseline: **755 passed, 0 failed**.
- Full local regression run during development: **787 passed, 0 failed**.
- One additional semantic-clock forgery regression was then added; changed
  guard/report/staging suites: **32 passed, 0 failed**. Head CI runs the complete
  final suite (expected 788); see PR checks for its actual result.
- An earlier full run had two failures because old market unit fixtures lacked
  the newly required asset hashes. Fixtures now supply their real digest and a
  new regression ensures invalid/missing/path-escaping assets are refused. No
  test was disabled and no production behavior was relaxed to hide a failure.
- Local actual PTB command flow with a loopback HTTP Bot API double: 10 requests,
  all delivered; `/nba`, `/analyze`, `/accuracy`, `/compare`; unauthorized chat
  rejected. Three verified EL finals reported, zero new forecasts. One CPU
  affinity, RLIMIT_AS 268435456, peak RSS **86.98 MiB**, shutdown completed.
  This host's cgroup was 8 GiB/2 CPUs; **do not call it a 256 MiB cgroup test**.
- CI adds the same forward workflow to the existing Docker checks using actual
  `--cpus=1 --memory=256m --memory-swap=256m`, network disabled, read-only root.
- No new official Telegram delivery in Cloud: all four dedicated settings are
  absent. Status **BLOCKED** for this head's real Bot API E2E.
- Earlier Philadelphia replay screenshots remain user-run visual delivery
  evidence. The handoff separately reports user-observed Pelicans–Nuggets live
  analysis and `/accuracy NBA` / `/compare NBA`; those reports are not replaced
  by, or relabeled as, this session's local mocks. The remote UserLAnd ledger was
  not accessible here, so its 3.22 MAE was not independently re-read.

## Isolated rollout commands (no Fly deployment)

Use existing dedicated test-bot settings privately, never production fallback.
Do not launch a second poller against an already-running test bot; use its normal
service update procedure. The following starts only the isolated process and
requires the existing validated prepared path/pin:

```sh
REPO_DIR="$PWD"
ISOLATED_DIR="$HOME/zeynal-isolated-hybrid"
python3 -m hybrid_engine.test_bot --preflight
python3 -m hybrid_engine.stage_forward_archive \
  --packet "$REPO_DIR/docs/evidence/handoff-forward-el-20261115.tar.gz" \
  --directory "$ISOLATED_DIR/forward-euroleague"
python3 -m hybrid_engine.test_bot \
  --archive-directory "$REPO_DIR/docs/prospective/euroleague-20261112" \
  --data-directory "$ISOLATED_DIR" \
  --nba-model "${NBA_PREPARED_PATH:?validated prepared model path required}" \
  --nba-model-sha "${NBA_PREPARED_SHA:?validated prepared SHA required}" \
  --forward-euroleague-directory "$ISOLATED_DIR/forward-euroleague"
```

Do not add `--replay-only` to this live-research configuration. An unchanged
replay-only startup remains available for archive-only use. All original packet
hashes and publication times remain intact when staged; copying does not create
new PREMATCH predictions.

Test chat commands: `/nba 2026-11-15`, corrected `/analyze` above while unstarted,
`/accuracy NBA`, `/compare NBA` (or explicit fixture ID if multiple),
`/accuracy EUROLEAGUE`, `/compare EUROLEAGUE E2026_109`,
`/euroleague 2026-11-17` (listing only until the capture window opens).

## Decision and remaining blockers

**GO: isolated research testing. NO-GO: production model promotion.**
Reasons: this head lacks a new real Telegram E2E receipt; live calibration sample
is insufficient; verified settlement scope/odds, lineups/injuries/rotation and
player effects are not connected; possession components still abstain where box
inputs are absent. EuroCup strict OOS remains insufficient in the existing
research evidence. Historic walk-forward results were preserved, not rerun and
not presented as new live performance. No automatic recalibration, score model
or quarter uncertainty promotion was made from three finals.

No main merge, Fly deployment, production DB/disk/snapshot/secret operation or
paid service was performed. No UserLAnd process was stopped by this work.

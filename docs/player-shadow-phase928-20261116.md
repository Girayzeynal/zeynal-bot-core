# FAZ 92.8 — Separate player-scoring research, never a silent score adjustment

This change preserves the active prepared NBA model, score/per-period outputs,
old forecasts, SQLite ledgers, production bot, Fly disk and snapshots. It adds
a prospective player-minute input archive and a separately fitted research pair.
It does not deploy, merge, alter secrets, fit on a Telegram request or calibrate
from the ten recently completed games.

## What is available, and what is still missing

Before the Cloud executor failed, the read-only repository/artifact inspection
found two prepared artifacts with a players field; both contained zero players.
No JSON expected_minutes files were found in that inspected material.
This is not an inventory of the private UserLAnd database or every remote archive.

The existing HierarchicalStrength already supports pregame projected exposure.
It is reused unchanged. Joint team/player fitting reduces the risk of subtracting
a missing player's points twice from a team average that already includes absences.
This remains an empirical-Bayes own-team player scoring coefficient model, with
team-level opponent defense. Individual player defense, measured pace, uncertain
minutes, confirmed lineups and role-specific replacement effects are NOT fitted.
Proportional replacement minutes are an explicit assumption, not learned roles.

Qualified real training games with prospectively archived player minutes: **0**.
Qualified real future paired forecasts/outcomes for this new model: **0**.
There is no newly trained real player artifact, measured accuracy gain, calibrated
probability or numerical confidence index to claim.

## Prospective minutes and source clocks

- NBA only; exact fixture, team IDs, season and original snapshot SHA.
- Fresh current roster/source review; both team directories must reconcile.
- Latest six available non-overtime prior games per team. The target game's actual
  minutes are never accepted as a pregame feature.
- Past box-score actual minutes are used only as historical rotation information.
  The native collector already labels them POSTGAME_ACTUAL_NOT_PREMATCH_LINEUP.
- Explicit DNP may contribute zero; missing/unknown display values do not imply DNP.
- Display-minute totals reconcile to 240 with a three-minute tolerance for source
  rounding. Projection normalizes to exactly 240, with no player exceeding 48.
- An OUT/suspended exclusion requires both ESPN and NBA official report source
  observations. This is not independent medical verification.
- Unknown identity, conflicts, questionable/doubtful/probable/day-to-day status,
  a new player without prior minutes, missing boxes or sources cause abstention.
- An unreported status is not assumed confirmed available. This limitation is
  retained in the input packet and UI.
- Generated, source access, ingestion and first archive times are explicit UTC.
  First publication must precede tipoff. Replay preserves first publication.
- Input witnesses are content-addressed, replayed and checked. Rehashed but changed
  minute/history packets fail the witness replay. SHA is integrity evidence, not
  an externally trusted timestamp/signature.

## Offline fit, inference and forward comparison

The baseline and candidate fit on identical available outcomes and pregame-minute
fixtures. Zero-only exposures are omitted from the player design to avoid
unidentified coefficients. Positive target players need five past exposures.
Default fit minimum is 100 games; tests may use 30 manufactured cases.
Model files bind source code, coefficients, covariance, label cutoff, season,
training fixtures and projected-minute provenance. No cross-season pooling.

An explicit offline capture runs TEAM_BAYES, PLAYER_BAYES and the existing
FAZ13_REFERENCE with coherent sampled score/per-period distributions. Existing
capture replays without simulation. Training is separate from capture.
New captures after tipoff and stale minutes are rejected.

The performance reader uses only these prospectively published pairs and the
existing native-verified later results from a read-only ledger. It reports score,
period, probability and interval metrics and paired clustered uncertainty against
both baselines. Fit versions remain separate; distinct-fixture totals do not count
a repeated model build as another game. The private ten old games are not converted
into prospective player-model tests after observing their outcomes.

At least 100 future paired games and eight day clusters are required for the next
research review. These thresholds do not alone prove improvement. A disjoint
acceptance/calibration review and explicit approval remain necessary. No automated
promotion, confidence index or calibration occurs.

## UserLAnd commands

Stop the isolated poller with Ctrl+C before the single-terminal launcher commands.
Use a genuinely future, already archived NBA ESPN game ID; do not backfill old
games. Replace the placeholder with its actual numeric ID.

    bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh --player-inputs ESPN_MAC_KIMLIGI

This updates only the existing research branch and collects separate source/minute
files. It does not change the forecast or fit a model. BLOCKED is a legitimate
result when current official status, exact player IDs or six past boxes are missing.
No API key/token needs to be printed or sent.

    bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh --player-shadow-review

This audits minute witnesses/readiness. It does not start Telegram or train.
Restart the standard isolated poller afterward:

    bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh

The Kadro panel adds a short separate-model readiness note. It does not collect
past boxes, calculate player adjustments, or fit online.

For qualified archived inputs, offline tools are:

    python -m hybrid_engine.player_shadow --directory SHADOW_DIRECTORY --history-manifest HISTORY_MANIFEST
    python -m hybrid_engine.player_shadow --directory SHADOW_DIRECTORY --capture-manifest HISTORY_MANIFEST --fixture-id CANONICAL_ID --model-artifact ARTIFACT_JSON --model-sha TRUSTED_SHA
    python -m hybrid_engine.player_shadow --directory SHADOW_DIRECTORY --report-ledger READ_ONLY_LEDGER

No model is prepared until prospective training inputs exist. Use pinned manifests
and the artifact SHA from the offline fit. The capture CLI cannot fit in the same run.

## Verification and limits of evidence

Before executor failure, the original 34 new tests plus six existing roster Telegram
tests passed locally (40/40). Recovery from the conversation added two cross-team
player identity regressions. The executor then failed to restart: no local final
full-suite result is asserted. GitHub Actions on the final commit is authoritative;
see the PR for actual counts, failures and resource measurements.

The explicit one-CPU/256MiB provider runtime suite includes the three new test
modules, in both normal and optional PDF Docker images. This is synthetic provider
and local HTTP Telegram transport verification, not real Telegram delivery.
The default production image/dependencies and frozen sampler/model sources remain
unchanged.

A public past-box source probe was started before executor loss; its result was not
retrieved and is not reported as successful. Private archive checks and actual
Telegram delivery on this revision remain BLOCKED outside UserLAnd. EuroLeague
and EuroCup roster-effect inference are not wired by this NBA-only increment.

Decision: **NO-GO for switching the production/default model**. Real prospective
player inputs, offline fitting, independent OOS and calibration evidence are missing.

Final source review also pins the roster directory retrieval in the maximum source
availability clock, tests it explicitly, and checks that multiple fit versions do
not inflate the distinct settled fixture count. The existing Telegram callback
regression asserts the separate-model limitation text.

The offline CLI rejects simultaneous training/capture flags before it reads inputs,
fits or writes artifacts; a regression checks that fail-closed ordering explicitly.

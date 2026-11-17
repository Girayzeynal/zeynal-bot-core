# FAZ 94 — same-input challengers and a prospective validation path

Continues PR #89 from f86d1f2 on the existing research branch. No production,
Fly, main, secret, default model, old prediction or sealed source packet changes.
This closes development/measurement gaps, not the outstanding accuracy gate.

## What the 18-game phone evidence actually establishes

The user ran the native read-only report on their private UserLAnd SQLite:
18 settled predictions, three TSİ day clusters; frozen total MAE 16.68559664,
RMSE 21.32507867; same-input retrospective cross-mean baseline total MAE
16.48888889, RMSE 21.23492276. Those are descriptive development results, not
a registered holdout. The private SQLite/assets are NOT available in Cloud.
No replacement 18-game dataset was manufactured from the chat transcript.

All 18 input profiles report no measured pace, no fitted player impact, frozen
team strengths despite new history, and deterministic period co-movement.
These are confirmed implementation limits, not established causes of any
particular realized score. More MC samples do not repair missing predictors.

## Implemented offline comparison

`hybrid_engine.challenger_review` reuses existing audited native snapshots,
Faz13, Bayesian MC/QMC, possession and stochastic-quarter implementations.
The target final is never an argument to the predictor; native labels are joined
after inference. First-publication, actual result availability, season/model
cohorts, source hashes and original input clocks use existing validators.

Compared components:

- FROZEN_ARCHIVED: exact original prediction and interval fields, not reissued.
- FAZ13_REFERENCE: existing Faz13 historical score/MC path, not a new baseline.
- UPDATED_BAYES_QMC / MC: distinct past-game posterior update, described below.
- UPDATED_BAYES_STOCHASTIC_PERIODS: existing quarter-shadow model; preserves
  every regulation total path and point mean, changes allocation uncertainty.
- POSSESSION_ANALYTIC / MC: existing possession engine only when the original
  cut has sufficient timestamped, regulation-eligible box statistics. Missing
  boxes abstain. Estimated possessions are never called measured PBP tempo.

All outputs report team/total/margin/quarter/half errors; raw winner Brier,
log loss and reliability curves; P25–P75/P10–P90/P05–P95 empirical coverage and
interval scores when supported. Paired comparisons against both frozen and
Faz13 use exactly their shared fixture IDs. A missing candidate is never a
zero-error case. Analytic laws without sampled paths do not invent quantiles.
Three-way Brier is the sum of three squared class errors (range 0–2), not the
binary 0–1 convention. No live performance or calibration cohort is replaced.

The report explicitly aggregates an offline policy across traced parameter
updates. It is NOT a single-fit calibration cohort. All historical candidate
replays are marked exploratory, generated after development outcomes were
examined. They cannot become retrospective PREMATCH captures or acceptance.

## The 19-row versus 170-row issue and bounded posterior update

The preserved Philadelphia input cut contains 19 recent games. The original
prepared model used 170 training games. The cut is not a complete league archive;
lowering the hierarchy's minimum or claiming a full refit would be misleading.

The new `posterior_refresh` retains the existing Gaussian posterior sufficient
statistics and adds only distinct native games absent from the original fit.
For the preserved example that is two additional games, for 172 total. With
fixed likelihood variance v, prior posterior mean m and precision P, it computes
P_new = P + X'X/v and m_new = solve(P_new, Pm + X'y/v).
An independent scalar Kalman update test verifies the algebra. Existing training
games cannot be double-counted; revised old labels and previously unseen teams
abstain and require a full refit. Original parameters/artifacts are not mutated.

This is a FIXED-NOISE POSTERIOR UPDATE, not complete league retraining, learned
recency weighting, player impact, pace fitting or full hierarchical Bayes.
Recent target-team histories miss some other teams' newest games. Full league
refresh still requires an accessible, verified complete training manifest.

## Prospective experiment — implemented, actual sample still zero

`challenger_forward` registers the code/policy before fresh original captures.
Its one declared primary candidate is UPDATED_BAYES_STOCHASTIC_PERIODS versus
FAZ13_REFERENCE on team MAE. No winner is chosen among candidates after results.
Minimums: 100 new common games per league/season/original-model cohort, 20 TSİ
day clusters, 80% primary coverage, at least 2% relative improvement, and a
negative upper bound on the primary paired day-cluster 95% difference interval.
The single primary interval is separate from exploratory multiple-model panels.
Cross-day repeated-team dependence remains a limitation; passing one statistic
does not satisfy all release requirements or authorize deployment.

The original feature cut must be after registration and at most one hour old;
capture admission requires at least 15 minutes to tipoff. Training/update is
only in an explicit offline CLI, never a Telegram request. At most four games
per batch; 180 seconds is checked BETWEEN games, not a hard process timeout.
Existing per-inference simulation budgets and sampler limits remain.

Existing ForwardRegistry handles content-addressed assets, first publication,
tipoff races and append-only records. Repeated capture replays the first record.
Official results later join by the exact original snapshot SHA/native ledger
identity. No pending label, late publication, pre-plan capture or conflicting
source can count as a prospective success. Old 18-game outcomes cannot enter
this new experiment. No blend weights or calibrator are fitted to those results.

Registration time is the actual local clock, not a backdated historical clock or
an independent signed timestamp. Code-pin changes block an old protocol; use a
new explicitly named experiment directory, retain the old plan/files and its
versioned code. No automatic plan reset or record deletion occurs.

## UserLAnd commands — isolated installation only

Stop the isolated poller with Ctrl+C before these CPU/IO-bound offline jobs.
The launcher fetches the existing research branch before dispatch; the model
review/capture itself makes no sports-provider or Telegram network requests.

Inspect the actual private 18-game archive (no replacement records):

```bash
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh --challenger-review
```

Prints matched component counts, total/team errors, total interval coverage,
abstentions and a content-addressed detailed report path. Default maximum 24;
the Python CLI exposes --maximum up to 200. Remaining records are explicit;
the default chronological subset must not be described as the entire archive.
Primary SQLite and an existing WAL are hashed before/after the review. Concurrent
change is BLOCKED, never rolled back or overwritten. Reports cannot be written
inside the source ledger/assets directory. No large raw sample arrays are saved.

Register once before NEW /analyze captures:

```bash
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh --challenger-plan
```

Start the isolated bot normally and collect NEW future fixtures with existing
Telegram commands. Then stop the poller and, while the input/lead window is valid:

```bash
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh --challenger-capture
```

After the normal isolated result collector has verified finals:

```bash
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh --challenger-results
```

An empty cohort is zero, not fabricated success. These modes need no bot token
to run and do not install dependencies or touch Fly. Restart normally afterward.
Future experiment records are separate from live-nba and cannot overwrite its
forecasts. The new modes do not change the Telegram score or narrow-band UI.

## Real evidence and remaining release gates

Cloud can reproduce one ORIGINAL preserved Philadelphia forecast and its native
ESPN final, in a new isolated replay COPY. The native final adapter verifies
identity and period scores; only its result is appended to that copy. Original
source packets and stored forecasts remain unchanged. New candidates are
post-result research, not independently captured forecasts. The detailed native
report is in `docs/evidence/challenger-phase94-native-20261117.json.gz`.

| Gate | Current state |
| --- | --- |
| Native same-input challengers / real first-publication regressions | Implemented; tests/CI reported on PR |
| Fixed-noise posterior refresh / stochastic per-period candidate | Implemented in offline research only |
| Private 18-game challenger comparison | BLOCKED in Cloud; run the new UserLAnd command |
| Fresh prospective challenger outcomes | 0 at implementation; collection cannot be accelerated by backfill |
| Complete league model refresh | Needs verified full training archive; recent 19 rows are insufficient |
| Measured pace / fitted player impact | Not provided by posterior update; input/model gates remain |
| Possession input coverage in preserved native cut | Missing; ABSTAIN |
| EuroLeague / EuroCup | Existing separate engines/archives/tests retained; no new NBA evidence is pooled into them |
| Historical three-league coverage | Existing strict report: NBA 7, EuroLeague 77 test games; EuroCup strict-fold 0. Older exploratory/prequential work is not fresh confirmation |
| Calibrated confidence / market EV | Still blocked by disjoint calibration and verified settlement/input coverage |
| Automatic phone injury-report discovery | Still incomplete; explicit fresh-PDF bridge is not automatic discovery |
| Actual new-mode UserLAnd and Telegram E2E | BLOCKED until run in the private test installation |
| Hard 1 CPU / 256 MiB and full regressions | Exact final-head CI evidence on PR; loopback/native replay is not live Telegram latency |
| Main merge / production deploy | Not performed; separate explicit approval still required |

No accuracy, confidence or calibration improvement is claimed from the single
replay or the already inspected 18-game development cohort. **Production NO-GO.**
There is no honest fixed completion date: the protocol alone needs at least
20 distinct game-day clusters, and source/player/calibration gaps may take longer.

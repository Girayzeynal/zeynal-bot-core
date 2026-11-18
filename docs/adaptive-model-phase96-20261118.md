# FAZ 96 — Separate scheduled tempo/efficiency and player research

The active frozen hierarchy does not update its whole-game mean from recent
score averages. This change implements a separate candidate pipeline instead
of rewriting that hierarchy or the existing registered NBA challenger plan.

## Data and fitted policies

The authenticated isolated test bot starts `AdaptiveWorker` alongside existing
NBA/European capture and settlement tasks. It runs in the background, never
inside `/analyze`, and covers NBA, EuroLeague and EuroCup in separate season
cohorts. Existing immutable source receipts supply historical catalogs. Fresh
native observations add recent NBA scoreboards and European season catalogs;
bounded serial acquisition collects missing **past** final box scores.

Every source reference is replayed against its native document/hash and real
observation/ingestion clocks. A newly downloaded box is available now, not at
the historical game date or original forecast time. Target labels, foreign
seasons, unverified score arithmetic, future observations and overtime boxes
cannot become regulation-possession training inputs. Missing data abstains.

The first successful fit in each six-hour UTC slot is immutable. Models use
their actual training/preparation times, not an invented slot-start timestamp.
At least 30 native games with valid regulation boxes are required. Native
observations continue accumulating after a fit, but its parameters do not
silently change inside that slot. A later slot incorporates newly available
results. Data availability, fitting and each forecast precede its tipoff.

The saved candidate components are:

- `UPDATED_TEAM`: a new team hierarchy on the currently available native corpus.
- `TEAM_ON_BOX_COHORT`: a team hierarchy restricted to the available box corpus.
- `EFFICIENCY_FIXED_PACE`: the existing absorbing reward/rate construction with
  a fixed league/corpus possession-count distribution.
- `PACE_EFFICIENCY`: identical reward-rate construction, with possession counts
  estimated from the target teams' available recent regulation boxes.
- `FROZEN_ORIGINAL`: the unmodified first forecast, where available, for a
  descriptive comparison with a different information timestamp.

The corpus and effective rate-history IDs are retained. Rate estimates use
the declared recent-team feature window; available corpus IDs do not imply
every row contributes to every parameter. The fixed-pace versus team-pace
comparison isolates the possession-count-law change. Contrasts against team
hierarchies also change model structure/recency and are not a causal attribution
to one feature. No ensemble weights are learned or selected after results.

Possessions use **FGA + 0.44 FTA − ORB + total turnovers**. These are box-score
estimates, not measured play-by-play possessions. The inherited reward model
assumes inferred two-free-throw trips, no and-one/three-free-throw trip model,
conditional team reward independence and independent quarters. Real bounded
10,000-path samples and the analytic law are retained; raw probabilities and
intervals remain uncalibrated. The possession law is conditional on fitted
rate point estimates; rate-parameter uncertainty is not integrated. This is
explicit in the saved forecast metadata, rather than called a fully Bayesian
or calibrated possession distribution.

## Player contribution is a separate paired publication

NBA prospective player-input collection runs automatically, with bounded
retries. Current rosters, supported status corroboration, real observation
times and past player boxes remain mandatory. Uncertain or unsupported absences
are not assigned guessed playing probabilities or arbitrary score offsets.

The existing joint team/player hierarchy is fitted only after at least **100
eligible prospective minute inputs** have later native results. Exposures must
vary; constant minutes cannot identify a changed player contribution. Player
and team-only controls use exactly the same training games. Unseen/unsupported
players, insufficient prior exposures or stale minute projections abstain.

Player forecasts have their own immutable `player-forecasts` first publication,
under the separate V2 policy and their actual later input time. Thus an early
pace forecast with no player data does not prevent a later valid player pair,
and no early forecast is overwritten. Player-only scoring effects are not
added on top of pace predictions; no combined or player-defense effect is
invented. European player-minute adapters are not fabricated; that branch
remains blocked where evidence is absent.

## Forward evaluation

The newly authorized V2 policy registers in `data/adaptive-v2`, with its own
source pins and actual registration time. Every eligible original encountered
in the future 36-hour window is admitted before results. Failed data/model
attempts remain in the coverage denominator rather than being cherry-picked
out after a result. The first successful prediction is saved before the final
15 minutes, with a fresh exact native fixture/status recheck after inference.

Primary: `PACE_EFFICIENCY` versus `TEAM_ON_BOX_COHORT`, team MAE, at least 100
matched future games, 20 distinct Istanbul match dates and 80% coverage of
settled admissions. The declared gain threshold is 2% with a negative upper
bound of the paired day-cluster interval; the three league hypotheses use a
predeclared multiplicity factor of three. Secondary contrasts are exploratory
and include refresh/original, efficiency/control, pace and player/control.
Repeated-team dependence across days is not fully resolved by day clustering.

Parameters can refresh under this predetermined policy; records are grouped
by policy/league/season and retain individual fit hashes. This is not a claim
that different fits are one fixed calibrated model. Later native result readers
join the original fixture and snapshot identities. No calibration or automatic
promotion occurs, even if a statistical gate passes.

The existing NBA protocol, its 12 pending cases reported by the user, active
model/sampler files, all prior forecasts and native result archives remain
unchanged. Existing `/accuracy`, `/compare` and `/predictions` continue to report
their original cohorts; the V2 study does not inflate the old 100-game count.

## Operation and validation boundaries

Use the usual isolated launcher after one Ctrl+C/restart:

```bash
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh
```

Separate Telegram messages can read the background status and a match:

```text
/test research
/research NBA
/research EUROLEAGUE
/research EUROCUP U2026_119
```

These handlers read saved research/status only; they do not fit or fetch data.
Missing historical V2 records are not backfilled for finished games. UserLAnd
must remain running and connected; no night-time capture command is required.
Optional read-only terminal status is available as `--adaptive-status` without
stopping polling. Bounded receipt/box/journal limits fail visibly; no archive is
automatically deleted to make room.

Automated evidence uses synthetic native receipts, real fits and samplers,
real paired-minute validation and local HTTP/PTB commands. It is not external
provider authentication or Telegram delivery evidence. Cloud lacks dedicated
test-bot configuration, so actual Telegram E2E of this release requires the
user's isolated restart and saved `/research` output. Production remains NO-GO;
there is no main merge, Fly deployment, production token/data change or paid
service.

Final local validation: **1,493/1,493** tests passed in **131.882 s**, zero failures/errors; all prior 1,463 retained, 30 added. The final source pins of all 27 existing registered NBA predictor files match the base commit. The evidence JSON records log and implementation hashes. Exact-commit GitHub/Docker/resource results are recorded in PR #89.

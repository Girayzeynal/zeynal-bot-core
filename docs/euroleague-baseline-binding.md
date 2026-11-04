# EuroLeague / EuroCup source-bound baseline storage

Previous commit `aa4e5e1`: GitHub run 41875082587 completed successfully.

## Storage gates

`providers.pace_evidence` dispatches validation by the declared source method.
Existing ESPN and legacy contracts remain available. Euroleague Live rows must
replay their complete observation before append and on every read. The league,
season-scoped game ID, exact source UTC start, source club code, home/away
orientation, scores and computed pace must all match. Only regular-season
records are admitted to these baseline series.

One Euroleague Live series may contain only this evidence-backed provider and
one season. Mixed seasons or providers are rejected on append and read; no old
files are overwritten or relabeled to make them fit. Use a separate directory
for another season. First observation times are immutable through the store
API: identical later fetches are idempotent, earlier replacement times fail.
The observation hash provides integrity, not third-party authenticity.

Historical selection and input capture use actual observation availability,
not merely game start. No rows observed at or after a historical cutoff may
support that cutoff. Source-specific validation also applies during numerical
reconciliation and FAZ13 input copying. EuroLeague input capture is exercised
with the real engine in offline tests. EuroCup baseline statistics do not
create or unlock an analysis profile.

## Explicit research adapter

The adapter defaults to **no estimated baseline fetching**. Adoption requires
both `allow_estimated_pace=True` and an explicit `baseline_season_year`. Team
resolution accepts source club codes or exact source names, with no guessed
aliases. Fetches select regular-season played games and reconcile every chosen
box score. A missing selected game rejects the whole fetch rather than silently
dropping an inconvenient observation. Fewer than six real records cannot be
manufactured into a six-game baseline.

Baseline operations reuse a validated catalog and identical game evidence for
at most 60 seconds per adapter instance. Cached observations retain their
original timestamps and are copied before returning them. HTTP 429 activates
an instance-level cooldown of at least 60 seconds, respecting a longer numeric
or HTTP-date `Retry-After`. No automatic retry, alternate identity or endpoint
bypass is used. Bounded diagnostics distinguish HTTP failures, invalid JSON,
transport failures, cooldowns and rejected selected fixtures.

The provider is still **not registered with production bootstrap or Telegram**.
The canonical prematch/result ledger remains NBA/ESPN-specific. EuroCup still
has no calibrated profile. No new predictions or calibration claims were made.

## Local and live validation

Full local suite: **449 passing tests**. New storage/adapter regressions cover
league/season/team binding, missing evidence, mixed-source reads/writes, replay,
point-in-time exclusions, idempotency/backdating, corruption, failed atomic
writes, short histories, opt-in, name resolution, source outages and FAZ13 input
copies. HTTP 429 cooldown and cache immutability are also tested. Compilation
and `git diff --check` passed.

Commands used new isolated directories, refusing any existing target:

```sh
python -m providers.euroleague_baseline_smoke --year 2026 --league EUROLEAGUE \
  --teams RED ZAL --directory /workspace/scratch/euroleague-baseline-e2026-research

python -m providers.euroleague_baseline_smoke --year 2026 --league EUROCUP \
  --teams KLA TRN --directory /workspace/scratch/eurocup-baseline-u2026-research
```

| Team/source | Retained actual source records | Aggregate/input window | Live storage replay |
| --- | ---: | ---: | --- |
| RED / E2026 | 9 | 6 | Passed |
| ZAL / E2026 | 0 persisted | None | Incomplete |
| KLA / U2026 | 6 | 6 | Passed |
| TRN / U2026 | 6 | 6 | Passed |

EuroCup's two team series share one fixture: they represent **11 distinct
games**, not 12 independent games. Each passed pre-observation exclusion and
source/input replay. Files and input copies are retained in the research
directories; summary artifacts are under `docs/evidence/`.

The initial ZAL batch did not return a usable complete fetch and its exact
cause was not retained. A later per-game diagnostic run reconciled all nine
selected games individually, but did not persist their evidence as a baseline.
A fresh-directory rerun failed at the catalog stage; subsequent instrumented
requests recorded HTTP **429** on the season and games endpoints at
`2026-11-04T17:23:59+00:00`. This confirms the later availability failure, not the
unrecorded cause of the first batch. Live requests were then stopped. Original
incomplete reports are retained rather than replaced with a successful status.

Evidence: `euroleague-baselines-first-20261104.json`,
`euroleague-baselines-recheck-20261104.json`, `eurocup-baselines-20261104.json`,
and `euroleague-rate-limit-20261104.json` in `docs/evidence/`.

## Remaining work

Recheck ZAL persistence after provider access is available. EuroLeague still
needs its provider-specific prospective fixture/prediction/result binding;
canonical name resolution into the analysis entry point is not enabled by
this research adapter. Independent possession/source reconciliation and
empirical calibration remain open. Production registration, deployment,
merging and secret changes were not performed.

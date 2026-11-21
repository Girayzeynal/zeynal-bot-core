# Phase 95 — European league routing, prediction capture and read-only reports

Existing PR: [#89](https://github.com/Girayzeynal/zeynal-bot-core/pull/89). Existing branch: `feature/hybrid-market-roster-evidence-20261114`. Starting HEAD: `b0e589f5807dfed265db83192b9d072650406e14`. No branch replacement, merge, production deployment, credentials operation or existing prediction/result deletion.

## Confirmed causes

1. `PredictionsCommand.handle` explicitly accepted only NBA, and the renderer required numeric ESPN IDs. The installation supplied only the NBA ledger reader. Five EuroLeague fixtures and their twenty component outputs existed in the sealed archive but were not connected to this command.
2. The live EuroLeague service was installed only when `--forward-euroleague-directory` was supplied. The UserLAnd launcher supplied the NBA model, but did not enable that path. Its fallback was `FrozenHybridService`, which searches the old EuroLeague archive.
3. That previous live path supported only EuroLeague, used an E2026 source/frozen model, and did not implement a separate EuroCup model. The frozen archive also accepts only EuroLeague.

The error was missing wiring and league support, not evidence that current NBA code or the historical archives should be replaced.

## Implementation and limits

- `europe_models.py` prepares separate league/season Bayesian artifacts from verified official E/U catalogs. Both receipt clocks must be real, not future, and the document hash, provider and exact season URL must match. Training uses only completed games with regulation periods and labels actually available at fit time. At least 30 training games are required; each target also needs the existing preflight's historical coverage.
- Preparation is an explicit offline job. `/analyze` never calls `fit`. Prepared coefficients, covariance, training identity/digest, native training receipt and source code pins are validated. Artifacts older than three days require offline preparation again. New artifacts are appended; prior artifacts are not overwritten.
- `europe_live.py` uses the existing universal league/team/time/history preflight. A verified official fixture, Istanbul command date and at least fifteen minutes before tipoff are required for a new forecast. Fresh receipt clocks, target exclusion from training, source identity before/after simulation and final publication clocks are checked. Source errors, missing models and insufficient history produce explicit abstentions.
- The existing Bayesian MC/RQMC and Faz13 reference implementations are reused. They are components, **not a trained ensemble**. The Bayesian model is team-based; verified player effects/possession inputs are not invented. Point projections and actual 10,000-sample intervals use existing simulation mathematics. No NBA coefficients are transferred to either European league.
- Per-league registries append immutable source/model/cut/forecast assets and first-publication receipts. Repeated requests return the first independently issued fixture record. Already-started fixtures cannot acquire a new PREMATCH publication. An existing record can be replayed after tipoff, without network access or a new simulation.
- Official results append separately. Regulation scores use the first four periods; overtime finals remain separate. Conflicting score corrections require review instead of overwriting history.
- `/predictions` supports NBA, EUROLEAGUE and EUROCUP, with paging, Telegram length splitting and league-specific provider IDs. European `/accuracy` and `/compare` use the same verified registries. Unknown legacy generation/first-publication times stay unknown, and those legacy publications are excluded from live accuracy claims.
- `/euroleague YYYY-MM-DD` and `/eurocup YYYY-MM-DD` expose verified official fixtures with ready-to-copy commands. Main production configuration is unchanged. The isolated launcher explicitly enables the new European directories.
- The NBA service, source-pinned sampler, SQLite ledger, existing archives and 27-file prospective challenger protocol are unchanged. The phone-registered protocol SHA remains `1e8f24a665a8b34a2ca22c37e408591ae8547b12788fe70c7150079b43249317`.

No probability calibration or confidence index is claimed: `NOT_CALIBRATED`, confidence `null`. No verified market/player data is fabricated. Future OOS observations are needed before any performance/promotion decision.

## Actual public-source and capture evidence

`docs/evidence/europe-phase95-native-20261117.tar.gz` contains the real public HTTP receipts, separate prepared models, feature cuts, forecasts, publication receipts and capture summary. Packet SHA-256:

`30fd3a08af2a1fd637889bc338b0ca25b1b13e0fe26d0ea433c74fc377c73f08`

The observed official catalogs contain 380 EuroLeague fixtures (110 completed) and 224 EuroCup fixtures (112 completed). These are the endpoint's observed scope, not a certification of exhaustive season coverage. Team/season participation also passed the existing official preflight.

| League | Official ID | Fixture | Start UTC | Prepared on actual past games | Bayesian/QMC score | Total | New capture elapsed |
|---|---|---|---|---:|---|---:|---:|
| EuroLeague | E2026_113 | Maccabi Rapyd Tel Aviv – Olympiacos Piraeus | 2026-11-17 17:00 | 110 | 82.62 – 88.22 | 170.85 | 2.57 s |
| EuroCup | U2026_117 | Turk Telekom Ankara – La Laguna Tenerife | 2026-11-17 16:30 | 112 | 81.17 – 84.29 | 165.46 | 2.05 s |

Both first publications occurred at 2026-11-17 16:11 UTC, before tipoff and with the required lead time. Snapshot SHAs:

- EuroLeague: `e8bf514124bb4b6c41b163564e0fff9f1a9b142352da573447d229367a49cb35`
- EuroCup: `5edc1bc33080b896a49dea5373cf37752cf376cf041de44e3e8702a3d7a42755`

Each repeated request returned `new_record=false`, with exactly one fixture publication and three stored components. Native evidence tests verify the packet, model/training provenance, pretipoff publication clocks, arithmetic and read-only replay. These captures are separate Cloud research evidence. They do not overwrite or automatically import anything into the private UserLAnd archive.

**This is real official-source/inference evidence, not real Telegram E2E or proof of predictive superiority.** No finalized scores are fabricated for these captures.

## Validation

- Initial complete regression run: **1,364 passed**, zero failures/errors, 146.981 s. This includes the existing 1,346 tests and the first 18 European tests.
- Expanded European suite: **21 passed**, zero failures/errors. Added native packet validation and both simulation-time/publication-time tipoff boundary tests.
- Final complete regression run: **1,367 passed**, zero failures/errors, 135.711 s. Final NBA/European loopback routing and the unchanged phone protocol were also checked together: **2 passed**. Branch Docker/CI results are reported separately on PR #89; a queued CI run is not a passed check.
- Coverage includes distinct E/U models; altered source/model hash refusal; wrong league/date/future clock; missing models/history; source outages; model age; no training in requests; alias deduplication; arithmetic; post-start refusal; fixture changes during inference; immutable repeated requests; additive official results and overtime separation; five preserved old matches/twenty components; NBA delegate preservation; replay-only safeguards; launcher preparation dispatch; and real PTB handler groups with local HTTP delivery.
- Real PTB loopback tests exercise NBA listing, old EuroLeague listing, E/U fixtures, new E/U analyses, EuroCup listing/accuracy/compare. They are explicitly **local HTTP tests**, not external Telegram delivery.
- The existing resource probe now includes the European suite. Its GitHub Docker job runs under `--cpus=1 --memory=256m --memory-swap=256m --read-only --network none`. Resource success must be taken from the completed job, not inferred from an unrestricted local run.
- `bash -n` and `git diff --check` pass. Existing pinned archive/model/protocol regressions are retained.

An old bad-argument test used EUROCUP as an invalid league. Its invalid input is now UNKNOWN_LEAGUE, preserving invalid-input assertions; new tests verify legitimate EuroCup routing. Early synthetic fixtures had tied regulation/final scores without overtime and were corrected to represent valid games; production parsing was not relaxed. An early restricted Cloud run could not complete threaded test operations; the permitted network/loopback environment completed the same tests successfully.

## UserLAnd setup and actual Telegram checks

Stop only the isolated foreground test bot with Ctrl+C. Then run these commands sequentially in the same terminal:

```bash
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh --prepare-europe
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh
```

The first command fast-forwards the existing branch, restarts an updated launcher if necessary, and prepares both independent European models under `~/zeynal-test-isolated/data/europe/models`. It does not require Telegram/provider keys and does not start a poller. If preparation reports BLOCKED, do not assume a league is ready. The second starts the same isolated bot with existing NBA settings plus `--europe-directory ~/zeynal-test-isolated/data/europe`.

In the authorized test chat, send each command as a separate message:

```text
/predictions NBA
/predictions EuroLeague
/predictions EuroCup
/euroleague YYYY-MM-DD
/eurocup YYYY-MM-DD
```

Replace the date with the desired **Türkiye calendar day**. Copy an eligible `/analyze EUROLEAGUE ...` or `/analyze EUROCUP ...` command from the verified fixture response. Use an actual not-started fixture; the two Cloud evidence games above may already have started by the time setup is completed. Repeat the same command to verify replay and use `/predictions` to confirm one fixture record. Then test:

```text
/accuracy EUROLEAGUE
/accuracy EUROCUP
/compare EUROLEAGUE E2026_<actual_game_code>
/compare EUROCUP U2026_<actual_game_code>
```

Real Telegram E2E: **BLOCKED in this Cloud workspace**. `test_bot --preflight` reports NOT_CONFIGURED for the dedicated test token/ID/username/chat configuration. No credential values were requested or printed. Existing user screenshots do not establish that this new code ran on their phone. The private UserLAnd SQLite file was not available here and was not created or impersonated.

## Decision

**GO for isolated test-bot validation only after successful offline preparation; NO-GO for production promotion.** Independent European capture is implemented and demonstrated against real official sources. External Telegram delivery of this change, future OOS performance/calibration, verified player/market scope and the explicit production acceptance gates remain outstanding. Faz13 stays the production default. No main merge or Fly.io deployment was performed.

The previous long PR description is preserved verbatim in `docs/pr89-evidence-history-through-phase942.md` so the current description can focus on the actual behavior without losing historical evidence.

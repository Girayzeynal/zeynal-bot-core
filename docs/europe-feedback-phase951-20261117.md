# Phase 95.1 — Telegram feedback and exact European city aliases

Continue PR #89 on `feature/hybrid-market-roster-evidence-20261114`, from `df5c4e6499b7bbe9bb3747a962bdbd924930b061`. No changes to the score engine, prepared European model pins, existing forecasts, SQLite, snapshots, production defaults or deployment settings.

## User-reported real Telegram observations

The user supplied the following command/response transcripts from their isolated bot. They are actual user-reported response evidence; this Cloud session did not itself execute Telegram commands or inspect the private delivery journal.

| Command/fixture | Reported outcome | Original generation (TSİ) | First archive (TSİ) | Reported prediction SHA |
|---|---|---|---|---|
| Dubai Basketball – Anadolu Efes, 2026-11-17 | `FIXTURE_ALREADY_STARTED_OR_COMPLETED`; no forecast | — | — | — |
| Zalgiris Kaunas – FC Bayern Munich, 2026-11-17 21:00 TSİ | New EuroLeague forecast, 92.69–83.97, total 176.66 | 19:42:54 | 19:42:55 | `5cc306346b2009f8ff1bf66cf7b70e55c34c50682d0a83ffd1448e5b89f2d02a` |
| Turk Telekom – Tenerife, 2026-11-17 | `TEAM_ALIAS_NOT_REGISTERED` | — | — | — |
| Roma Basketball – Bahcesehir College Istanbul, 2026-11-17 22:00 TSİ | New EuroCup forecast, 83.20–89.69, total 172.89 | 19:45:12 | 19:45:12 | `cd79a9935261b9db9559ec24087876b1585756b614d46d6c6b9b5581b7b9a8c7` |

These observations establish successful user-observed forecast responses in **both** European leagues. They do not establish the complete `/predictions`/result-settlement E2E sequence, predictive accuracy, calibration or this follow-up patch's Telegram delivery. The recorded SHA/time/score values above are transcribed evidence, not imported or reconstructed prediction-ledger rows.

## Root cause and fix

The actual official EuroCup season catalog reports:

- `TNF`: name `La Laguna Tenerife`, abbreviated name `LL Tenerife`, **city `Tenerife`**.
- `TTK`: name `Turk Telekom Ankara`, abbreviated/editorial name `Turk Telekom`, city `Ankara`.

The parser registered name/abbreviation aliases and name-with/without-city variants but **not the city alone**. Consequently `Turk Telekom` already resolved, while `Tenerife` did not. No fuzzy name guessing or fixture identity problem was needed to explain this refusal.

`providers/season_participants.py` now adds an exact `SOURCE_CITY` alias for European participant snapshots. The existing registry evaluates every season participant and rejects ambiguous shared cities and collisions with another team's name. It never selects the first approximate match. League/season scope, immutable internal/provider IDs, receipt hash validation and alias availability from the actual observation time are unchanged. No nickname is backdated into an older snapshot.

NBA continues to call the original alias behavior with city aliases disabled. The original NBA and European simulation files and the 27-file phone-registered challenger protocol stay byte-for-byte unchanged. **Existing prepared European models do not need to be regenerated for this alias patch.**

## Native source/time proof

Two public-source evidence packets are appended:

- `eurocup-city-alias-phase951-20261117.json.gz`: the actual official season and 32-club receipts; payload SHA `6d4964accd77af7d633b88a1bcc7016d1c1d436ddb2bd1971481496f66304f12`.
- `eurocup-city-time-phase951-20261117.json.gz`: fresh official season, participants and fixture receipts plus a real read-only preflight for the exact short command. The response resolves **TTK/TNF**, then correctly stops at **TIME / FIXTURE_ALREADY_STARTED_OR_COMPLETED**. It creates zero predictions and performs no Telegram send.

The fixture's verified start was **2026-11-17 16:30 UTC / 19:30 TSİ**. The user reported these commands after that time. Fixing the alias must therefore **not** generate a retrospective PREMATCH record. Tests replay the source/time evidence read-only; they are not new historical forecasts.

## Rounding assessment

No score correction or old-record rewrite is warranted from the pasted displays. Independent rounding to two decimals can produce small differences:

- Zalgiris's displayed home quarters sum to 92.68 versus the displayed unrounded-derived final of 92.69.
- Roma's displayed half totals sum to 172.88 versus the displayed final total of 172.89.
- For `n` individually rounded values versus a separately rounded sum, the absolute display difference is bounded by `(n+1) × 0.005` (plus floating-point tolerance). Four-quarter displays can therefore differ by up to 0.025. Three independently rounded percentages may sum to 99.9/100.1.

The existing tests verify raw score/quarter/half arithmetic and generated sample intervals. Those computations, recorded values, bands and raw probabilities were left unchanged. Duplicate timestamp labels are cosmetic output repetition and do not prove that a second forecast was generated.

## Validation and remaining checks

Eight new regressions cover real Tenerife/Telekom IDs; shared-city ambiguity; collisions with official names; substring and cross-league refusals; alias observation cutoffs; unchanged NBA alias behavior; source tampering; and native started-match refusal after successful short-name resolution. The resource probe includes the new module. Local full-suite run: **1,374 passed**, zero failures/errors, 133.160 s, before the final native time-replay regression was added. The final dedicated alias suite then passed **8/8**. Exact final-head full-suite and CI/resource results are reported separately on PR #89.

To install, stop only the isolated UserLAnd bot with Ctrl+C and restart using the existing launcher:

```bash
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh
```

No `--prepare-europe` rerun is required solely for this parser fix. Model preparation still has its normal age/source checks.

In the test chat, `/analyze EuroCup 2026-11-17 Turk Telekom vs Tenerife` should now resolve both identities and **refuse the already-started fixture**. For a new prediction, copy a genuinely future command from `/eurocup YYYY-MM-DD`. Also verify `/predictions EuroLeague` and `/predictions EuroCup`. To check read-only replay without relying on an abbreviated name after tipoff, use the full archived names: `/analyze EuroLeague 2026-11-17 Zalgiris Kaunas vs FC Bayern Munich` and `/analyze EuroCup 2026-11-17 Roma Basketball vs Bahcesehir College Istanbul`. Any private first-publication/delivery timestamps still require inspection in UserLAnd, not a fabricated Cloud copy.

**NO-GO for production promotion.** New EuroLeague/EuroCup predictions remain `NOT_CALIBRATED`; user-reported Telegram delivery is useful integration evidence, not proof of model superiority. No main merge, Fly.io deployment, secret change or archive deletion.

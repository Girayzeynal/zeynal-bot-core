# FAZ 95.6 — current European provider identity association

The UserLAnd report for `E2026_120` contains `Besiktas Istanbul` in the
official forecast and `Beşiktaş J.K.` in The Odds API's returned event list.
Both starts are `2026-11-18T17:00:00Z`. The bridge previously required literal
normalized team names, so it rejected the same club's legal-name form. The
same comparison also affected winner, spread and team-total outcome parsing.

The fix loads the current official competition/season club catalog when the
European market panel is opened before tipoff and provider credentials exist.
It verifies receipt URL, competition, season, document hashes, clock freshness
(300 seconds), complete membership, unambiguous aliases, and the archived club
IDs. Discovery and price details must retain one event ID and exactly the
archived UTC start. NBA's separately documented +600-second rule does not apply
to European matches.

Official source aliases are used as published. A single explicit legal-name
rule accepts `Beşiktaş J.K.` / `Besiktas JK` only when the current catalog
resolves `Besiktas` uniquely to `BES` and also supplies `BJK`. This legal suffix
is an application rule, **not** a claim that the official catalog publishes
the literal `Beşiktaş J.K.` string. No fuzzy, arbitrary sponsor, city-only
fallback, or start-time-only association was added. Ambiguous source aliases
are refused. Failure to verify the catalog leaves only the previous exact
canonical name comparison available, with an explicit Turkish diagnostic.

The catalog and identity evidence belong to a separate current source context.
Original issue/feature/archive clocks, model versions, score projections,
sample hashes and prediction bytes stay unchanged. Current observations cannot
enter the original forecast's performance cohort. Sources and current reviews
are content addressed; existing source receipts are checked and reused without
rewriting. Catalog memory is bounded to four league/season entries; current
reviews retain the existing 120-second cache. Post-tipoff and absent-key paths
do not fetch catalogs. The first market callback permits 45 seconds for two
bounded official catalog transports plus the existing 12-second provider
admission window; roster callbacks retain 20 seconds. This is a callback wait
limit, not a claim that Python worker cancellation terminates an HTTP request.

## Public native evidence and limitations

`docs/evidence/europe-provider-alias-phase956-20261117.json.gz` contains actual
HTTP 200 official E2026 season and club receipts captured in Cloud at
`2026-11-17T19:12:32Z` (`1794942752`). The full club catalog confirms:

- `BES`: `Besiktas Istanbul`, source abbreviation `Besiktas`, source TV code `BJK`.
- `MAD`: `Real Madrid`.

Packet file SHA-256:
`2a2edc1ceb6d31f8bc85f5e7871f358d76f13057130ed3c5af0bb23c02b1c7d8`.
Payload SHA-256:
`abf8b74ab0f5cc7a231d9b67dd92d7b6cc1509c2d461a09798685fc65a2e037b`.
Official receipt bundle SHA-256:
`b4627b5916f37b238bafa40221df24f7985c4d6ca82dffc0edd128038b57ba06`.

The provider's `Beşiktaş J.K.` event observation is user supplied. Cloud did
not authenticate to The Odds API or receive that native event document. Tests
of discovery, pricing and Telegram transport therefore use explicitly
synthetic provider events. The native catalog replay test advances only its
test clock to the actual receipt time; it creates no historical prediction.

The phone also reports these existing original forecasts; they were not
rewritten or newly independently audited in Cloud:

| Fixture | Phone issue/archive time (TSİ) | Forecast SHA-256 |
| --- | --- | --- |
| E2026_120 | 17.11.2026 22:07:53 | fbaa308e9447d546431707f767114db41309f5d7e47d71d61bd52f8e0177dbce |
| U2026_115 | 17.11.2026 22:08:51 | fc9e2dd5dee6f806ca556021b187fbffa65438f02e3c9c3399c6ca63b2c96cb1 |

## Remaining external blockers

- The Odds API EuroCup sport key is absent from the user's actual active
  catalog. No unsupported EuroCup event endpoint or invented prices are used.
- API-Basketball's native season value `2026` was selected from its catalog,
  but games still return plan/subscription and season error classes. This
  remains a provider access error; no paid subscription or staged secret was
  activated.
- Official injury news pages return HTTP 429 in the phone observation. Existing
  cooldowns are honored. Missing player observations do not imply a healthy
  roster and are not numerical player adjustments.
- Settlement scope and OOS probability calibration remain unverified.
  `NOT_CALIBRATED`, no confidence index and no comparable edge remain correct.
- Real Telegram E2E for this particular alias fix is **BLOCKED in Cloud**;
  UserLAnd must exercise the authenticated isolated bot and inspect its reply.

## Automated validation

- Local Python 3.12: **1,424 tests passed**, zero failures/errors, 119.866 s.
- Targeted identity/provider/replay/Telegram-loopback/challenger suite:
  **137 passed**, zero failures/errors, 17.310 s.
- Twelve new identity tests plus two current-source integration tests retain
  all previous 1,410 tests. Additional assertions check that absent-key and
  post-tipoff paths make no official catalog calls.
- The public native catalog test verifies the original source receipt hashes;
  the application-level legal-name association is explicitly identified.
- Local Python 3.11 Docker image built using the repository's existing
  ephemeral proxy-CA build secret. The initial build without the environment
  CA failed certificate verification during dependency download; that was not
  an application test failure. No credential or CA was added to the image.
- Local rootless Docker did not expose the requested hard memory/CPU cgroups;
  `--require-cgroup-limits` correctly refused the probe. This is **BLOCKED
  locally**, not a successful 256 MiB validation. The committed GitHub workflow
  requires hard 256 MiB/one CPU in both base and optional-PDF images; exact-HEAD
  Actions results are tracked in PR #89.
- The previously registered phone challenger protocol is unchanged. No model
  source pins or prepared models were changed or refreshed by this fix.

## UserLAnd verification

Stop the isolated poller with Ctrl+C, then use the existing launcher:

```bash
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh
```

Before tipoff, send the existing official command and open **Piyasa**:

```text
/analyze EUROLEAGUE 2026-11-18 Besiktas Istanbul vs Real Madrid
```

This must replay the existing forecast. If current provider prices are
available, the panel should report `Resmî kulüp kimlikleri ve tekil başlangıç
saati eşleşti` with a catalog SHA and retain `NOT_CALIBRATED`. A successful
identity fix does not guarantee prices, settlement rules, calibration or API
subscription access. For the existing EuroCup record, use its original
official fixture command and verify that absent market coverage remains
explicit rather than fabricated.

No main merge, Fly deployment, production bot/DB/secret change, model refit or
archive reset is part of this change. Production decision remains **NO-GO**.

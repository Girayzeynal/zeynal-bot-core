# FAZ26 end-to-end verification and resilience

Initial remote SHA fcfa41d4480ac69c2a04cc44560d6edf2e77408e was independently
verified on draft, unmerged PR #12. Both unit-tests and docker-build passed in
push 41916038690 and PR 41916049189. Existing FAZ24/25 ledger architecture was
retained; no production schedule was enabled.

## KeyError investigation and scope of the fix

The old collection expression indexed team['abbreviation'] after checking only
its ID. A controlled directory record containing id but no abbreviation
reproduces KeyError('abbreviation'). The new directory_codes boundary validates
shape, uniqueness and a nonempty abbreviation for both independently resolved
team IDs, otherwise raising BaselineUnavailable before refreshing or forecasting.
A regression reproduces the previous exception and checks safe rejection.

The original FAZ25 incident retained error_type=KeyError, not the missing field
or a traceback. Subsequent real data did not reproduce it. Therefore this is a
confirmed vulnerable path and a confirmed fix, **not proof that the original
incident had this exact cause**. That historical root cause remains unresolved.
An attempted missing competition-status reproduction instead returned None
through existing pace guards; no claim is made that it reproduced the incident.
The earlier team-schedule omission of historical finals was already addressed
in FAZ25 by date-scoped history and remains independently documented.

## HTTP retry policy

ESPN 403 now stops the request loop and cools the adapter for at least five
minutes. HTTP 429 stops rapid retries, respects numeric or HTTP-date Retry-After
and applies at least sixty seconds. Malformed/nonfinite/negative values cannot
shorten the minimum. No long blocking sleep is inserted. Within the instance,
all endpoint calls honor the same cooldown. FAZ25 persists schedule retry delays
through ProviderCooldown, so restarting a local poller does not erase the due time.
Transport/5xx retries remain bounded to three attempts and existing timeouts.
No proxy rotation, paid fallback or access-control bypass is introduced.

## Dry run and synthetic end-to-end test

```
python -m faz25 poll RESEARCH_LEDGER BASELINE_DIRECTORY --cycles 1 --dry-run
```

Dry run fetches/validates schedule and reports future IDs, but does not invoke
baseline refresh, prediction collection or result reconciliation and does not
write attempts. Constructing a brand-new Poller still initializes its local
schema; existing initialized DB bytes are unchanged by a dry-run tick. The CLI
requires a clean source checkout as before. This does not enable any timer.

The synthetic integration test runs the real scheduler and FAZ24 pipeline from
an explicit pregame ESPN-shaped schedule, then advances a mocked clock and supplies
a synthetic consistent final through the existing source-evidence collector.
The resulting strict report contains one evaluated game and score metrics; no
Brier score or calibration is inferred without original probability outputs.
Original stage payloads/hashes remain unchanged. It is an algorithm/integration
test, not actual predictive performance or a backdated real match.

## Real records and restoration

At actual observation epoch 1793829090, ESPN summary routes for 401909922 and
401909923 both reported explicit pregame status and the original start
1793836800 (2026-11-05 00:00 UTC). IDs, source home/away IDs and starts replayed
through the scheduled-fixture parser. Existing bound-result collectors returned
awaiting_tipoff; no final outcome was substituted. Original predictions, input
copies and stage rows were byte-for-byte equal as selected SQL records before
and after checking. SQLite integrity_check returned ok.

The research ledger retains **two original prospective predictions, two FAZ24
bundles, zero real completed results and zero verified scored prediction/result
pairs**. This count concerns these two prospective fixtures, not the prior
separate audit of fifteen historical ESPN finals. Their accuracy metrics remain
null. Injuries/rosters/probabilities remain missing/unverified; estimated pace
is not reclassified as a measured possession count.

A new owner-only online backup was restored to /workspace/scratch/faz26-restore.sqlite
and its FAZ24 evidence-bound report replayed successfully. External transfer is
still untested. Hashes detect corruption but do not provide remote attestation.
Exact live check and restoration evidence are committed under docs/evidence.

## Remaining release gates

Continuous unattended operation, actual post-final ingestion of these fixtures,
sufficient prospective observations, calibrated original probabilities with
matching scoring scope, independent provider availability, externally stored
backup/restore and operational monitoring remain unverified. The historical
KeyError incident is not fully explained. Local Docker daemon access was denied
previously; successful docker-build must be checked on this commit's GitHub CI.
No merge, Fly.io/Telegram deployment, production timer, paid API or secret change
is part of FAZ26.

Local validation: all 576 regression tests passed in 23.358 seconds, including
eight new FAZ26 cases for the controlled schema exception, HTTP cooldowns,
Retry-After formats, network retry bounds, persistent delay, dry-run byte
preservation and the full synthetic schedule-to-score chain. Compilation and
diff checks passed. Synthetic scored cases are excluded from real sample counts.

An actual CLI dry run using clean implementation b339536 returned
schedule_unavailable / ProviderCooldown with no collection/result actions. This
is retained as an unsuccessful provider-access observation, not successful live
schedule validation. The output does not identify which HTTP cooldown status
was returned, so neither 403 nor 429 is asserted for this specific observation.
The restored database's SHA256 still equals its original backup hash after the
attempt. No predictions, outcomes or retry state were written by this dry run.

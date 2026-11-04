# FAZ25 opt-in NBA polling and safe retries

Initial FAZ24 head 7c6e572aeaae8754aa22f85a31d57cc942d11d30 was independently
verified on PR #12. Both unit-tests and docker-build passed in push 41913739452
and PR 41913741071. FAZ24 original input/stage/result infrastructure is reused.

## Run boundaries

```
python -m faz25 poll NEW_RESEARCH_LEDGER NEW_BASELINES_DIRECTORY --cycles 1
python -m faz25 poll RESEARCH_LEDGER BASELINES_DIRECTORY --cycles 12 --interval 300
python -m faz25 backup RESEARCH_LEDGER NEW_BACKUP_FILE.sqlite
```

The local loop is explicitly opt-in. No production service, cron, Fly.io job or
Telegram handler is enabled. The CLI uses the clean checkout's full commit SHA;
cycles are bounded, interval must be at least 60 seconds. It checks yesterday,
today and tomorrow's UTC scoreboard buckets, then uses the existing Istanbul-date
resolver again to establish exact fixture identity before generation and writing.
A provider failure is not an empty valid game day. Invalid scheduled events and
conflicting fixture IDs/team starts fail the schedule poll closed.

Only future games within six hours are eligible. At most two fixtures and two
pending results are attempted per tick. Polling fetches ESPN directory team IDs,
refreshes each baseline using the existing explicit estimated-pace adapter, and
requires source observations no older than six hours. Missing/stale data prevents
collection; the cutoff is an operational configuration, not proof of injury,
roster, or market freshness. Pace remains a labeled box-score estimate. Missing
injuries, rosters and calibrated probabilities retain FAZ24's unverified markers.
Same-second observation availability may fail the strict earlier-than-generation
contract; a later retry is safe, never backdated.

The schedule row must match both fixture resolutions. A schedule change is
rejected before writing, rather than labeling a changed schedule a successful
poll. FAZ24 still enforces the actual wall clock inside its atomic write.
Late ticks cannot backfill forecasts. Source/model IDs and generation/observation
freshness remain in immutable FAZ24 bundles; mutable faz25_attempts records only
operational attempt status, next retry and error category.

## Retry and concurrency contract

A nonblocking flock on the local ledger's adjacent lock file prevents overlapping
FAZ25 processes from starting work. Existing canonical predictions are checked
before baseline refresh or generation. Interrupted-after-commit attempts cannot
replace or duplicate the forecast on retry. FAZ24's transaction/uniqueness guards
remain authoritative for other writers. Local locks do not coordinate different
hosts or separate ledger copies.

Timeouts bound each schedule/collection/result action. Connection failures,
unavailable responses, invalid evidence and SQLite failures are retained as
retry_pending, with exponential cooldown from 60 seconds capped at one hour.
Successful/pending actions have a five-minute cooldown. No blocking retry loop
is added. A failed schedule does not prevent results from being reconciled.
Pending results are ordered by retry time to avoid starvation; already completed
results are skipped. Result matching uses the existing strict ESPN bound-result
collector; operational success never fabricates a score or prediction.

## Local scheduling versus GitHub Actions

| Option | Benefit | Reliability limit |
| --- | --- | --- |
| Opt-in local loop/systemd timer | Durable local SQLite, controllable frequency, flock | Host downtime/sleep misses windows; monitoring and backups needed |
| GitHub scheduled Actions | Hosted runner; no always-on local host | Cron can delay/skip; runner disk is ephemeral; repo concurrency is not a distributed ledger |
| Manual reliability workflow | Reproducible isolated fault tests without real data writes | Exercises software only; not continuous collection or live accuracy |

The committed faz25-reliability workflow is workflow_dispatch only, has read-only
repository permissions and no secrets, schedule trigger or production connections.
Normal PR CI also runs the full tests and Docker build. A GitHub cron collector
must not be enabled until durable ledger retrieval, conditional publication,
concurrency, outage recovery and access policy are independently tested.
No scheduled hosted collector has been provisioned or started here.

## Safe external-backup design

The implemented backup uses SQLite's online backup API rather than copying a
live DB file. It checks integrity, sets mode 0600, atomically publishes without
overwrite and returns a SHA256. The source DB is opened read-only. Lock files,
environment variables and credentials are not archived. Caller-supplied new
backup paths control where local snapshots are written; no cloud upload occurs.

For an external destination already authorized by the operator: use a restricted
private location, authenticated encrypted transport, immutable/versioned names,
retention limits and a manifest containing hash/schema/source SHA. Verify the
hash after transfer and rehearse restoring to an isolated DB, replaying inputs,
stages and result evidence before enabling collection. Encrypt sensitive payloads
with existing managed credentials if required; no keys are generated or changed
by this work. Do not commit ledgers/credentials or publish private artifacts from
a public repository. GitHub artifacts alone are not a reliable mutable ledger.

## Evidence limits

Tests inject timeout, transport failure, blocked/null response, late polling,
malformed/conflicting fixtures, missing/stale baseline failure, duplicate replay,
concurrent runs, process interruption after atomic commit, result starvation,
result work during schedule outage, backup integrity/permissions and no-clobber.
FAZ24's existing input binding, chronology, corruption and atomic rollback tests
continue to apply. Source outage mocks test policy; they do not prove an endpoint
is accessible. Real final ingestion and sufficient prospective samples are still
needed. No live historical backfill or measured predictive accuracy is claimed.

Validation: full local suite 566 tests passed (20.225 seconds). Targeted polling
and FAZ24 suites also passed after adding a nonzero CLI exit for provider/retry
failures, so monitoring cannot mistake a failed run for healthy collection.
Compilation and diff checks passed. No local Docker success is claimed; the
managed environment previously denied Docker socket access. Dedicated GitHub
Docker/unit jobs are the authoritative build checks for the new commit.

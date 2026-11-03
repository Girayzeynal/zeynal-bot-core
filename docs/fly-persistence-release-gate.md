# Fly.io persistence and writer-safety release gate

Status: **NOT APPROVED FOR PRODUCTION**. This checklist is a verification procedure, not evidence that production is configured correctly.

## Findings from repository configuration

- `fly.toml` sets `min_machines_running = 1`. This is a minimum, **not** a maximum machine count.
- `fly.toml` declares no `[[mounts]]` entry.
- `BASELINE_DIR = "data/baselines"` and `FAZ23_STORAGE = "faz23_storage.sqlite"` are relative paths.
- `Dockerfile` creates `/app/data/baselines/series` inside the image; image filesystem creation does **not** make that directory persistent.
- `main.py` now passes `BASELINE_DIR` to `TeamBaselineStore`.
- `fcntl.flock` serializes writers only when they access the same lock file on a filesystem with compatible locking semantics. It is **not** distributed coordination across independent machines.

## Required pre-deployment verification (operator, read-only)

Run from an authenticated Fly.io CLI session and retain redacted outputs:

```sh
fly status -a zeynal-bot-core
fly machine list -a zeynal-bot-core
fly volumes list -a zeynal-bot-core
```

Confirm the actual machine count, attached volumes, region, and intended writer ownership. Do not paste tokens, secrets, or complete environment dumps into issues.

## Release-blocking decisions

1. Choose either **one designated writer with an attached persistent volume** or a **transactional shared datastore** supporting concurrent writers. Do not treat `min_machines_running = 1` as a single-writer guarantee.
2. Verify that the chosen storage persists across restarts and replacement of the writer machine. A volume is scoped to a machine/region; do not assume automatic replication.
3. Ensure both baseline series and `FAZ23_STORAGE` have an explicit persistence policy. Verify all code paths use the configured locations.
4. Define backups, restore drill, corruption handling, and rollback before migrating any existing records.
5. Re-run regression tests, Docker build, and a non-production persistence/restart smoke test against the exact release commit.
6. Verify NBA.com source timestamps and measured pace provenance; do not synthesize pace or mark date-only timestamps as exact.

## Evidence and sign-off

- Latest verified CI before this document: GitHub Actions #389, commit `e536f59e`, unit-tests and docker-build successful (user screenshots).
- Subsequent commits require fresh CI evidence.
- Earlier operator CLI output showed two started machines: an older bot-serving machine without a `/data` mount, and a newer volume-attached machine running `sleep 86400` rather than the bot. Re-check this inventory immediately before any release; it is historical evidence, not a current live verification.
- The operator's local UserLAnd `fly.toml` included a `/data` mount and absolute storage paths, but this GitHub branch's `fly.toml` does not. Deployment from this branch must not assume that local configuration is present in GitHub or in the deployed machine.
- Before release, reconcile the configuration files, establish a single bot polling/writer owner, and confirm all SQLite paths and baseline storage reside on its mounted persistent volume.
- **Do not merge or deploy** until the above release gates are explicitly satisfied.

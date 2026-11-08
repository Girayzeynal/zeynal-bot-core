# Fly.io production prediction ledger verification

This procedure does **not** assert that a persistent Fly volume already exists.
It must be executed against the actual production Fly app before calling
prediction archiving or calibration operational.

## 1. Inspect the current app and its storage

From a terminal authenticated with Fly.io:

```sh
fly status -a zeynal-bot-core
fly volumes list -a zeynal-bot-core
fly machine list -a zeynal-bot-core
```

Check the actual machine/volume attachment and region. Fly volumes belong to
individual machines, not to the entire app. A volume on one machine does not
make SQLite on another machine durable or shared. Do not assume two machines
can safely share one SQLite file.

## 2. Verify the running machine

```sh
fly ssh console -a zeynal-bot-core -C 'python /app/ledger_readiness.py'
```

If the result says `persistent_volume_not_mounted`, do **not** claim that
predictions are archived. If `database_not_found`, check the configured
`PREDICTION_LEDGER_DB` and the attached volume. Do not create a blank database
to make the health check green.

`status=ready` means that the tables can be read; inspect
`prediction_count`, `outcome_count`, and `espn_provenance_count` to establish
whether real observations exist. `ready` with zero predictions is **not** a
successful end-to-end prediction archive test.

## 3. Provision persistent storage only after inspecting existing volumes

If no appropriate volume exists, plan a **single-writer** storage topology,
provision a Fly volume in the correct region, and configure a mount to
`/data` in `fly.toml`:

```toml
[mounts]
source = "prediction_data"
destination = "/data"
```

The mount declaration alone does **not** create a volume. Before any
production deploy, check that the named volume exists and is attached to the
intended machine. Do not create or resize production volumes blindly.
For multi-machine deployment, SQLite on per-machine Fly volumes is not a
shared ledger: use a designated writer or external transactional storage.

## 4. Verify a real prematch prediction

1. Confirm the actual machine has a mounted `/data` volume and the readiness
   command returns readable ledger tables.
2. In Telegram, request `/analyze NBA YYYY-MM-DD Home vs Away` for a
   **verified future fixture**. Use actual team names only in the Telegram
   command, not hardcoded application code.
3. Run readiness again on the **same machine**. Verify the prediction count
   changed or an immutable version was appended. Do not assume a repeated
   request inserts a new first prediction.
4. Inspect ledger provenance and tipoff only through authorized, read-only
   queries; no sensitive environment variables should be printed.

## 5. Import completed ESPN results

Only for an existing ledger with ESPN-provenance prematch records:

```sh
fly ssh console -a zeynal-bot-core -C 'python /app/espn_outcome_sync.py /data/prediction_ledger.sqlite'
```

This is a **dry run**. Inspect each event's `VERIFIED_DRY_RUN` status and
scores before explicitly applying:

```sh
fly ssh console -a zeynal-bot-core -C 'python /app/espn_outcome_sync.py /data/prediction_ledger.sqlite --apply'
```

Do not use `--apply` if the volume/machine identity is uncertain.
The importer is not scheduled automatically. ESPN and API-Sports fixture
identities are intentionally not interchangeable.

## 6. Produce a verified calibration report

```sh
fly ssh console -a zeynal-bot-core -C 'python -c "import json; from verified_version_calibration import version_calibration_report; print(json.dumps(version_calibration_report(\"/data/prediction_ledger.sqlite\"), ensure_ascii=False))"'
```

If no verified pairs exist, report that fact. Do not present synthetic or
unverified historical predictions as real backtest performance.

## Release gate

- GitHub CI green **and** actual deployed commit verified
- Fly volume and machine attachment verified
- Real Telegram prediction present in persistent ledger
- ESPN outcome matched to the exact original provider fixture ID
- Calibration includes only pre-tipoff, same-scope observations

Until all gates pass, label production calibration **not verified**.

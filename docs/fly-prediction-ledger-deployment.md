# Fly.io prediction ledger: existing volume migration (NOT YET SAFE TO DEPLOY)

## Verified production state — 2026-11-08

- Active Telegram bot machine: `2876926b073608`, started, health check 1/1, **no mounts**.
- Stopped helper machine: `805121f66139d8`, command `sleep 86400`, restart policy `no`.
- Existing encrypted 1 GB volume: `zeynal_data` (`vol_vjy269kxopkd8opv`), region `ams`, currently attached to stopped helper machine at `/data`.
- This PR changes `fly.toml` to mount `zeynal_data` at `/data` and sets `PREDICTION_LEDGER_DB=/data/prediction_ledger.sqlite`.
- **Do not merge or deploy yet.** The volume is not currently available to the active bot; a deployment could fail or interrupt service.

## Mandatory safety gates

1. Inspect and independently back up the contents of `zeynal_data` before changing machine attachment. Do not assume it is empty.
2. Verify the backup can be read, including any existing SQLite databases.
3. Plan a controlled maintenance window to detach/reassign the volume from the stopped helper machine. Fly volumes are machine-local and cannot be simultaneously mounted on two machines.
4. Confirm the deployment target machine is in `ams`, and avoid creating a second Telegram polling process.
5. Only then merge this PR and deploy. Verify the active bot reports a mounted `/data`, the SQLite ledger file is created, and a **new pre-tipoff** NBA prediction is inserted.
6. Confirm records persist across a normal restart and retain independent backups.

## Read-only checks

```sh
fly machines list -a zeynal-bot-core
fly volumes list -a zeynal-bot-core
fly machine status 805121f66139d8 -a zeynal-bot-core -d
fly machine status 2876926b073608 -a zeynal-bot-core -d
```

Do not start, destroy, clone, or update either machine solely to inspect the data. A stopped helper machine may be used for data access only after a separately reviewed safe procedure.

## Calibration caveats

- The existing ledger writes only when `PREDICTION_LEDGER_DB` is configured, fixture tipoff is known, and the forecast precedes tipoff.
- No historical predictions are retroactively added.
- Stored win probability is **regulation-only**; settlement must compare against regulation-only results, not overtime-inclusive NBA final scores.
- A Telegram response does not prove the archive write succeeded. Verify database contents and logs.
- The archive does not yet provide calibrated confidence or proven prediction accuracy.

## Rollback

If the migration fails, restore the previous deployment configuration while preserving the existing volume and its backup. Never delete the volume to fix a deployment error.

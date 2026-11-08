# NBA prediction ledger — Fly.io persistent storage

**Deployment gate:** Do not merge the volume-mount PR until a Fly volume
named `zeynal_predictions` exists in the application's `ams` region.
The GitHub Actions Docker build does **not** create a Fly volume.

The proposed `fly.toml` uses:
- `[[mounts]] source = "zeynal_predictions"`
- `destination = "/data/predictions"`
- `PREDICTION_LEDGER_DB = "/data/predictions/prediction_ledger.sqlite"`

## Operator steps (authenticated Fly CLI)

1. Inspect current deployment and volumes, **before creating anything**:

   ```sh
   fly status -a zeynal-bot-core
   fly volumes list -a zeynal-bot-core
   ```

2. If no appropriate volume exists, provision one in the existing app region:

   ```sh
   fly volumes create zeynal_predictions --region ams --size 1 -a zeynal-bot-core
   ```

   Check the Fly dashboard for region, available storage, cost and
   machine/volume placement. A Fly volume is tied to one machine; do not
   assume a single SQLite file is shared across multiple instances.

3. Verify `fly volumes list -a zeynal-bot-core` shows the correct volume.
   Only then merge this PR and deploy the resulting main commit.

4. Verify runtime logs and actual persisted records after a **new pre-tipoff**
   `/analyze` command. Existing predictions are not retroactively imported.
   Confirm the volume survives a restart and that the ledger contains the
   expected fixture, UTC prediction timestamp and scope.

5. Back up the SQLite database off-machine. A volume is persistent across
   normal restarts but is **not** a substitute for independent backups.

## Safety and calibration limits

- If the DB env variable is unset, the handler intentionally skips archiving.
- The current handler logs persistence failures and still sends the forecast;
  a Telegram reply alone does not prove archiving succeeded.
- The ledger records regulation-only win probabilities. Compare them only to
  **regulation-only** outcomes; final NBA scores including overtime are
  incompatible with that probability scope.
- Current archive identity is a canonicalized team-name/time key, not a
  provider fixture ID. Provider provenance and settlement are still pending.
- No historical accuracy or numerical confidence index is justified until
  actual pregame predictions, verified outcomes and provenance are matched.

## Rollback

If deploy fails because the volume is absent or mismatched, revert the
mount/config commit and redeploy the previous known-good image. Do not delete
a volume as part of rollback; deletion risks permanent data loss.

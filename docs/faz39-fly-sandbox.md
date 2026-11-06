# FAZ39 Fly.io sandbox preparation

This is an **offline synthetic storage exercise**, not a Fly deployment, a real
prediction pilot, or proof of cross-Cloud persistence. The existing `fly.toml`,
production Dockerfile, model coefficients, original ledgers and prior evidence
are unchanged. PR #14 stays draft. No app, volume, secret, paid resource,
external transfer target or production scheduler is created/enabled.

## Isolation contract

- `fly.faz39-sandbox.toml` deliberately has **no app name, mounts, services,
  HTTP listener, release command or automatic restart**. Its only process runs
  `python -I /sandbox/faz39_sandbox.py` once and exits. Never pass the production
  app to this config. A future separately authorized test app must use the
  `zeynal-faz39-sandbox-` namespace; no such app is allocated by this change.
- `Dockerfile.faz39-sandbox` and its Dockerfile-specific `.dockerignore` use an
  explicit allowlist. No `COPY . .`, `main.py`, `dynamic_scheduler.py`, production
  `fly.toml`, `.env`, `.git`, SQLite files or prior prediction packages enter
  the image/context. Selected recovery dependency code may include adapter class
  definitions; the exercise never instantiates a provider or calls an API.
- Runtime dependencies exclude the Telegram SDK. UID/GID 10001 has no production
  filesystem paths; selected code is read-only. The build requires an explicit
  40-character `FAZ39_SOURCE_SHA`. This is build/caller provenance, **not a live
  GitHub SHA/CI attestation** and cannot authorize real prospective capture.
- The runner refuses wrong modes, production app names, `/data`, production
  database/volume/API configuration, tokens, secrets, Telegram and scheduler
  environment variables. It does not read credential values or secret files.
  Start with a clean environment; do not inject production/CI credentials.
- An irreversible Python audit hook is installed before recovery imports. It
  refuses socket operations, child processes, shell execution and imports of
  bot/scheduler entry modules. No polling, webhook or scheduling loop exists.
  This application guard is **not** a kernel/network security boundary. CI also
  uses `--network=none --read-only --cap-drop=ALL`, no-new-privileges and only a
  disposable `/tmp` tmpfs. An authorized future Fly test needs independent
  platform egress isolation review; no real provider connections are needed.

## One-shot flow

1. Validate the strict TOML contract and runtime environment; fail with exit 1
   and sanitized `SANDBOX_REFUSED` JSON on invalid state.
2. Create a fresh owner-only `/tmp/faz39-sandbox-*` directory; accept **no input
   database, storage target or destination arguments**. Initialize the existing
   FAZ39 schema in `SYNTHETIC_TEST` mode. No match or forecast is fabricated.
3. Keep a real SQLite WAL writer open, disable autocheckpoint, commit one
   synthetic probe row and hold a second row in an uncommitted transaction.
4. Use the existing FAZ39 snapshot/backup, immutable DirectoryStore and transfer
   protocol. Verify bundle and manifest SHA-256. Restore by the exact trusted
   manifest pin into a new directory and replay the FAZ39/integrity audit.
5. Verify the committed row is present and the uncommitted row is absent. Retry
   export must be `ALREADY_EXPORTED`; existing restore targets must be refused.
   Confirm source/restored file hashes stay unchanged. Store/print `report.json`.

The pin is in a **separate local namespace**, on the same ephemeral disk. It is
not a durable external pin or a freshness attestation (`NOT_ATTESTED`). The
report always retains `durable_storage_verified=false`,
`separate_cloud_runtime_verified=false`, `external_upload_performed=false`,
and `new_real_prospective_records=0`. Records are storage probes; forecast count
is zero. Losing `/tmp` loses this test evidence unless an authorized operator
later exports it. No backup is uploaded by this preparation.

## Validation performed without Fly resources

Local regression: `python -m unittest tests.test_faz39_sandbox -v`, then the full
`python -m unittest discover -s tests -v`. The allowlisted source set is copied
to a fresh local directory and exercised in a fresh isolated Python process.
This is not a container or an independent second Cloud runtime.

The existing GitHub `docker-build` job now additionally builds this sandbox
image with the checked-out SHA and executes its synthetic flow without network
or persistent mounts. It does not use Fly credentials or the Fly CLI, publish
an image or deploy anything. Production image build validation remains present.

`tomllib` parsing plus the strict regression contract validates the config
locally. Fly platform acceptance is **not** claimed without an actual Fly
validator. The local Docker socket is inaccessible to this non-root Cloud
user; container build/runtime verification must be reported from exact-SHA CI.

## Remaining release gates

- Separately authorized sandbox app/volume and platform permission review;
  no resource creation or deploy is authorized by this preparation.
- Real second-runtime restore with trusted pin obtained outside the source
  runtime, stale/corrupt backup refusal and an independently retained hash trail.
- Authorized durable storage, latest-pin freshness and provider-specific atomic
  create/read-after-write/durability proof. Local staging does not establish any
  of these, even when all synthetic tests pass.
- No production scheduler activation, main merge or Telegram/Fly production
  changes. This sandbox has no live prediction capability.

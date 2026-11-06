# FAZ39: external checkpoint and independent recovery readiness

Task: [PR #14 comment 6677628143](https://github.com/Girayzeynal/zeynal-bot-core/pull/14#issuecomment-6677628143).
This is contract/readiness code, **not an enabled external storage integration**.
`LOCAL_ONLY`, existing local transfer semantics, the sandbox image, original
ledgers, model coefficients, production Fly config and Telegram remain unchanged.
No credentials, SDK, remote provider, independent verifier, pin service or second
Cloud runtime is provisioned. No real external upload or cross-runtime test ran.

## Provider and authority contracts

`faz39_checkpoint_contract.py` adds optional, disabled-by-default interfaces:

| Interface | Required semantics |
|---|---|
| `ExternalCheckpointStore` | Immutable atomic `put_if_absent` and streaming-bounded `read`; no list/latest/upsert/delete |
| `IndependentPinAuthority` | Independently retained current pin; linearizable conditional update by expected payload SHA across machines |
| `Attestor` | Explicitly installed trust dependency; verify purpose-bound canonical payload and detached attestation against registered public trust roots |
| `CheckedExternalStore` | Require policy, issuer and attested capability evidence before provider I/O; check response types, returned size and exact read-after-write bytes |

The capability attestation must bind the target ID and evidence digest for
atomic create, bounded read, read-after-write, immutable objects, durable ACK and
linearizable pin CAS. A declaration or successful fake test is not evidence of
these properties. Real provider certification must bind the provider/driver
revision and independently retained test artifacts to that evidence digest.
The wrapper cannot retroactively limit a dishonest adapter's memory allocation:
the actual transport must enforce streaming limits itself.

No automatic adapter registry, environment lookup, credential discovery or CLI
activation exists. `ExternalPolicy()` is disabled. This gate only accepts
`usage=SYNTHETIC_TEST`; an attested PROSPECTIVE ledger is still refused. A future
authorized experiment with real independent attestation can retain synthetic
data and select a separately installed `INDEPENDENT` attestor. Its UTC clock
must be a callable that is re-read around provider waits. Existing live ledgers
are outside this contract's authorization.

The only attestor/authority implementations in the tests are **FAKES**. The fake
attestation is a deterministic purpose-prefixed digest, not a signature, secret
or proof of independence. Its scope is SYNTHETIC_TEST; it cannot satisfy an
INDEPENDENT policy. A real public-key/attestation verifier and trusted key/issuer
registration remain unimplemented blockers. Never load verifier code, trust roots
or issuer selection from the checkpoint or its JSON payload.

## Trusted pin protocol (schema 1)

A detached envelope has exactly `payload` and `attestation`. Attestation has
`scheme`, `issuer_id`, `key_id`, `proof`. Only DETACHED_SIGNATURE or
INDEPENDENT_ATTESTATION schemes are accepted; the installed verifier decides
which proof/algorithm/key is valid. Algorithm/key selection must be pinned by
that verifier, not negotiated by untrusted JSON. Verification must return the
boolean True. Missing provenance, duplicate keys, invalid JSON, nonfinite values,
documents over 64 KiB and unrecognized fields fail closed.

Canonical signed bytes are UTF-8 JSON using sorted keys, compact separators,
ASCII escaping and no nonfinite numbers. The verifier also receives a mandatory
purpose: FAZ39_TRUSTED_PIN, FAZ39_UTC, FAZ39_ADAPTER_CONTRACT or
FAZ39_RUNTIME_EVIDENCE. A signature/proof for one purpose cannot authorize another.

The pin payload has exactly:

| Field | Meaning |
|---|---|
| schema_version, generation | Integer 1 schema; strictly positive integer generation (booleans refused) |
| previous_pin_sha256 | Null for generation 1; preceding canonical pin payload digest thereafter |
| manifest_sha256, source_commit | Exact transfer manifest SHA-256 and full source commit SHA |
| target_id, ledger_id | Authorized non-secret target alias and exact ledger identity |
| issued_utc, expires_utc | UTC epoch seconds; positive lifetime at most 300 seconds |
| source_runtime_id, storage_identity | Globally scoped source runtime and independent checkpoint-store identities |

The caller obtains a **TrustAnchor** `(target_id, ledger_id, generation,
pin_sha256)` outside the restore payload from an independent control plane.
Never reconstruct the high-water mark from the supplied pin, object listing,
filename, local restored DB or a co-rolled-back file. An old genuine signature
does not override a higher independently retained generation. Same-generation
forks, target/ledger/source/manifest substitutions and skipped generations fail.

`advance_pin` requires exactly old generation + 1 and the old digest as parent.
It reads the head, performs conditional CAS, and verifies an exact read-back.
An identical already-published candidate is idempotent. A competing candidate,
stale read, partition, invalid response or lost ACK is not success. It never
force-replaces a head or chooses a listing fallback. Update the independently
retained high-water mark only after confirmed publication. If a write may have
succeeded, retain the old/candidate receipts and audit; do not infer zero writes.

A separately attested UTC ticket binds observed/lower/upper UTC, a validity end,
the evidence digest and `challenge_sha256` for a fresh caller-generated request
nonce. Its expected digest must be retained outside the envelope; rotate it per
attempt, never recover it from the supplied ticket. INDEPENDENT scope also
requires a caller-retained monotonic request deadline (at most 10 seconds),
checked before and after attestation verification. Wall-clock rollback cannot
rearm that lease. Monotonic deadlines are local-process state and must never be
copied between machines. Uncertainty is at most 2 seconds; host skew tolerance
is 2 seconds. The current wall clock must lie within the ticket's narrow validity;
both that clock and the trusted interval must lie within pin validity. Checks
repeat before CAS, after read-back and after evidence-provider ACKs. Expiration
after a write is an uncertain operation requiring audit, never fabricated success.

`verify_restore_plan` binds the pin to the external high-water mark and the raw
manifest digest, source SHA, ledger identity and SYNTHETIC_TEST mode. It returns
RESTORE_PLAN_VALIDATED_NOT_EXECUTED. It does **not** replace full commit-marker,
bundle, expanded-size, SQLite integrity or FAZ39 audit checks in `import_bundle`.
Local legacy pins deliberately remain exact-pin/NOT_ATTESTED and are not upgraded.

## Independent-runtime outcome schema (schema 1)

Each detached evidence payload binds:

- `source` and `destination`: runtime ID, run ID, filesystem identity and storage
  identity. Every pair must differ. Use globally scoped provider/resource IDs;
  Linux st_dev numbers or two directory names are not independent identities.
- Authorized persistent `storage` target/identity/durability. Ephemeral-only,
  same-runtime, same-run, same-filesystem or same-volume reports are refused.
- Manifest digest, pin payload digest/generation, source SHA and ledger ID.
- `restore`: observed SQLite checksum, canonical audit checksum, `integrity=ok`
  and ledger identity. These must match a **separate actual destination restore
  observation**, not an observation copied out of the evidence payload itself.
- Source/production isolation booleans (both false) and isolation evidence digest.
- UTC evidence digest and chronological start/completion UTC epoch seconds.
- Exact `outcome=RESTORE_COMPLETE`. Incomplete/error outcomes cannot be submitted
  as a successful restore; retain their raw diagnostics separately.

`validate_runtime_evidence` checks schema, attestation, bindings and observations
but returns **EVIDENCE_SCHEMA_VALID_NOT_INDEPENDENTLY_VERIFIED**. In particular,
JSON containing `separate_cloud_runtime_verified=true` is refused. Plausible
different IDs and self-reported persistent storage do not prove actual separation.

`publish_runtime_evidence` conditionally publishes an immutable outcome outside
the restore bundle under an attempt key derived from destination runtime/run IDs
and pin/generation. Filesystem/storage identity claims are immutable outcome
metadata; changing them cannot invent a second outcome for that same run.
Exact retry is idempotent; different bytes for the same attempt
conflict without replacing the first outcome. ACK loss/expiry may leave a visible
object; retry/audit the exact attempt instead of manufacturing another success.
Retries still require valid pin/UTC gates. After expiry, use a read-only audit
with independently obtained fresh evidence; do not edit the old envelope or
publish a replacement outcome to hide an uncertain operation. That live audit
orchestration is not implemented/activated by this readiness change.
An independently retained expected envelope digest is also needed to detect
deletion/rollback of this evidence namespace. Publication alone is not proof.

All contract/plan/evidence results retain `durable_storage_verified=false` and
`separate_cloud_runtime_verified=false`. The schema validator never issues
CROSS_RUNTIME_VERIFIED. Independent operational review of real artifacts and
provider/platform evidence must remain a separate release gate.

## Clean destination inventory and future procedure (NOT executed)

1. Obtain separate authorization for the exact synthetic-only storage namespace,
   source/destination runtimes, costs, network policy and public attestation trust
   configuration. No Fly app/volume/deploy or paid allocation is authorized here.
2. Destination needs pinned recovery code/dependencies, immutable bundle object,
   transfer manifest and final commit marker. Do not copy `.git`, `.env`, bot
   configuration, production secrets, /data or actual prediction ledgers.
3. Obtain the detached pin, latest high-water mark, public issuer/verifier roots,
   capability attestation and fresh trusted UTC ticket through independent channels
   outside the payload. Persist them independently of the source runtime.
4. Verify all trust/plan gates. Invoke the existing full pinned importer in a new
   quarantined owner-only destination. Missing marker/visibility or corrupt bytes
   must fail, with no fallback to older objects. Revalidate authority/UTC after
   provider waits, before publishing a completion outcome; expired/uncertain
   imports stay quarantined and never become independent success evidence.
5. Independently hash the actual restored database, run read-only integrity and
   FAZ39 audits, verify ledger identity and source/production access denial.
   Retain signed platform evidence of distinct runtime/storage identities and
   persistent target survival after the source workspace is unavailable.
6. Validate/publish the detached immutable outcome. Independently retain its
   expected digest, pin/high-water mark, source/destination run IDs, source SHA,
   exit codes, UTC proofs and provider logs. A second process or CI job on the
   same source disk does not satisfy this procedure.

The preexisting collector/CLI/sandbox are deliberately **not wired** to a live
external orchestrator. The readiness functions and mock integration demonstrate
the required gates; installing a transport/verifier, final quarantine publication
or granting cross-runtime status require a separately authorized live experiment.

## Threats and deterministic coverage

| Threat | Required behavior / evidence limit |
|---|---|
| Two distributed writers / lost updates | Authority linearizable CAS, exact parent/generation and read-back; test thread lock only simulates the contract |
| Stale listing / rollback / fork | No listing API; require independently retained anchor; stale signed pin cannot override it |
| Partial upload / eventual visibility | Existing commit-last protocol; missing commit or read-back fails; exact-byte retry only |
| Malicious substitution / corrupt bundle | Bound manifest, source, ledger and hash; full existing SQLite/FAZ39 importer still mandatory |
| Network partition / lost ACK | Exception/uncertain state; possible publication is not claimed absent; exact retry is idempotent |
| Simulated power loss | Fake provider loses acknowledged data and is refused; prior WAL/fsync tests remain, no physical power-cut claim |
| Clock delay / skew / expiry | Signed UTC ticket and repeated pin validity checks; no completion after deadline |
| Forged independence / copied observation | Signed schema and external observation bindings; even valid mock evidence stays NOT_VERIFIED |
| Conflicting outcome writers | One immutable attempt key; conflicting bytes refused, no extra success record |
| Production access | Synthetic-only trust gate, unchanged sandbox guards and allowlist; no Telegram/production configuration import |

Tests use in-memory fake provider/authority/attestor and real local synthetic
SQLite backup/import. They are not remote transport, real cryptographic
attestation, physical durability or independent-Cloud evidence.

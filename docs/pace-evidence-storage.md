# Durable pace evidence and availability

The ESPN estimated-pace path now stores a versioned source observation inside
each retained `TeamGameRecord.pace_evidence`, in the same atomic JSON replacement
as scores, pace and provider identity. There is no separately written sidecar
whose failure could leave a numeric baseline without its evidence.

The observation contains:

- `snapshot.schema_version = 1`, actual local UTC fetch time, the parsed
  scoreboard identity and the relevant original ESPN summary fields;
- replay inputs for final status, period scores/duration, made/attempted shots,
  rebounds and total turnovers;
- method, estimated pace and source URL;
- SHA-256 over the canonical serialized snapshot, including its observation
  time. This is an integrity check, **not a signature or source authentication**.

Every estimated ESPN record must replay successfully on append and read. Its
fixture ID, timestamp, home/away score orientation, pace and source method must
agree with the retained observation. Missing, malformed, future-dated or
contradictory observations fail closed. Recomputing a hash alone cannot bypass
the independent numeric and source-field reconciliation.

A repeated fetch with identical source fields and a later observation time is
idempotent: it preserves the original file and first observation time. An
attempt to replace that time with an earlier assertion is rejected. Changed
source facts require a separate correction workflow; they cannot silently
overwrite the recorded observation.

Point-in-time selection, canonical prematch-series audits and numerical
reconciliation require `observed_at_utc < prediction_utc`. A game starting
before a prediction does not prove its box score was available then. Equal
second timestamps are conservatively excluded. The adapter captures the actual
fetch time, even when a caller requests a historical cutoff; it never backdates
the observation to that cutoff.

Legacy providers retain their previous schema contract. Existing records are
not rewritten or assigned invented evidence. Old estimated-method-tagged rows
without a complete observation are rejected. Estimated pace remains opt-in;
production adapter construction still leaves it disabled.

## Validation

- Prior commit `33d90f5`: GitHub run 41864736340 completed successfully, including
  unit tests and the Docker image build.
- Eleven new offline regression methods cover restart/replay, record binding,
  tampering, recalculated hashes, late evidence, repeated fetch/backdating,
  legacy compatibility, atomic replacement failure, numerical reconciliation
  and the adapter-to-bootstrapper persistence path.
- Full local suite: **384 passing tests**; module compilation and
  `git diff --check` passed.
- Live ESPN fixture `401909903` was fetched, stored in a temporary directory,
  reopened and replayed successfully. Estimated pace: 94.4. An audit cutoff
  before its actual observation time correctly rejected it. The retained live
  report is `evidence/espn-pace-storage-20261104.json`. No production files were
  touched and no predictions were manufactured for this check.

## Remaining boundaries

The observation proves internal consistency and records when this process
received the data; a writable local timestamp/hash is not independent provider
attestation. Team-key resolution remains the adapter/caller's responsibility.
The series keeps its existing rolling retention limit, so evidence is pruned
with its game. Retained input copies have subsequently been bound to each new
canonical FAZ13 projection independently of rolling history; see
`prediction-input-binding.md` for replay and transaction validation.
Independent possession validation,
prospective calibration and non-NBA provider integration also remain open.

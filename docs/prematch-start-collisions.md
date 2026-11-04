# Reject ambiguous same-team historical starts

Prior commit `c641121` passed push CI 41890868529 and PR CI 41890879868.

Exact-time historical series now reject two eligible records for the same team
with an identical game start, even when their provider fixture IDs or sources
differ. Provider IDs do not make simultaneous matches for one team independent
observations. This prevents a malformed or conflicting record from inflating
the input sample and altering aggregates.

The check lives in the common prematch-series audit rather than an optional
store helper. It therefore also applies to frozen original-input copies during
ledger replay. Rehashing a modified copy cannot bypass its semantic validation.
Existing duplicate provider-ID checks and stricter source-specific evidence
replay remain in place. Ineligible future records remain excluded before this
check and do not increase the eligible sample.

Tests cover different IDs at one start, different providers without a custom
store checker, future-record exclusion and a rehashed input-copy collision
rejected before any prediction/input ledger rows are written. Synthetic
fixtures are used for malformed cases; no real match is invented or merged.
No attempt is made to automatically choose which conflicting provider is true.
Independent reconciliation remains necessary to resolve a rejected conflict.

This change does not add observation-time evidence to legacy providers. It
retains existing source-specific availability validation and does not claim
that game start alone proves when legacy data became available. Real prospective
outcomes and empirical calibration remain outstanding. No merge, deployment,
paid service, secret change or external message is part of this work.

Recovery validation: all 535 tests passed again in 22.527 seconds; compilation
and diff checks passed. Changes were recovered intact from the working tree.
The previous full-suite log also showed 535 passing tests. Its old execution
session was no longer queryable (unknown process ID); the available logs do not
establish a code/test failure or the root cause of the reported cloud failure.
Old git processes were zombies, not active blocked operations. No active work
needed forced termination. A recovery patch and document copy were retained
under /tmp before committing.

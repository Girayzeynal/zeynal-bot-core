# Remove the remaining FAZ13 manual pace default

Prior commit `2e4da56` passed push CI 41889886647 and PR CI 41889897966.

The optional manual loader used to substitute 99.5 when a JSON baseline lacked
pace. FAZ13 now preserves missing pace as missing. If either aggregated team
has no valid supplied pace, it raises an explicit missing-tempo error and
produces no projection. The score aggregator may still describe score-only
rows for other callers, but FAZ13 requires tempo before constructing its output.
The obsolete 99.5 fallback expressions were removed from FAZ13's output path.

Manual and persisted numeric magnitudes now reach aggregation without an early
float cast, preventing booleans from becoming 1.0/0.0 before validation. Boolean
scores/confidences and non-string sources are excluded by aggregation; boolean
pace is absent rather than numeric. Missing/invalid manual JSON objects do not
cause scalar/list indexing crashes. Persisted sample counts must be positive
non-boolean integers instead of being silently truncated.

Manual baselines remain exploratory and cannot gain the verified label merely
by providing a pace value. Exact original input capture and source-specific
replay gates remain unchanged. No real possession count or empirical calibration
is inferred from an estimate or manually supplied statistic.

Five new synthetic regression tests exercise missing/invalid summary tempo,
manual files without tempo, malformed JSON shape, boolean summary scores and
invalid aggregation sources. They perform no network calls. Actual ESPN source
validation and prospective completed-result evaluation were not repeated by
this local change. No merge or production deployment is included.

Validation: all 531 local regression tests passed, including existing captured
input, source evidence and decision integration tests. Compilation and diff
checks passed. The FAZ13 source contains no remaining 99.5 fallback.

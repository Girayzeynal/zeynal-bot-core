# Strict descriptive-metric input types

Prior commit `d9ff66e` passed push CI 41886229926 and PR CI 41886244233.

The historical evaluator rejects boolean scores, probabilities and timestamps.
Python booleans are integer subclasses; accepting them could turn malformed
observations into apparently legitimate numeric errors or Brier scores. Numeric
strings are no longer coerced into predictions/probabilities. Expected scores
and optional probabilities require finite numeric magnitudes, actual scores
require nonnegative non-boolean integers, and timestamps require positive
non-boolean integer epoch seconds. An absent probability remains valid and
does not create probability metrics.

Fixture and league identities must be nonempty strings with no surrounding
whitespace. Invalid identities are rejected rather than silently normalized,
which avoids conflating different provider identifiers or allowing whitespace
to hide duplicates. Scope must explicitly be `REGULATION_ONLY` or
`FINAL_WITH_OT`, and prediction/result scopes must match. Matching unknown or
missing scopes cannot establish comparability.

These gates validate the local evaluation contract. They do not independently
verify a provider response, establish observation authenticity, or replace the
strict bound report's original-input/result-evidence replay. Legacy evaluations
without a fixture-start timestamp retain their existing exploratory behavior;
the walk-forward and strict bound paths require a verified start.

Seven additional synthetic tests cover malformed numeric fields, timestamps,
actual scores, identities, unknown scopes, supported scopes and non-record
inputs. Existing known-score error/Brier/log-loss tests remain unchanged.
No observed result or empirical calibration parameter is invented.

Validation: all 508 regression tests passed; compilation and diff checks passed.
Re-ran the result collectors against existing prospective NBA fixture 401909924
and EuroLeague fixture E2026_100. Both returned `awaiting_tipoff`, so neither made
a final-result request or invented an outcome. This does not constitute new ESPN
network verification or real completed-result validation. No pending collector
process remained after these checks.

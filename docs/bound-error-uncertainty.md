# Descriptive uncertainty for source-bound errors

Previous commit `2520a17` passed push CI 41887644168 and PR CI 41887652279.

The explicit `--require-bound-evidence` report now includes error uncertainty
only after original prediction inputs and provider final observations replay.
EuroLeague additionally requires its original pre-tipoff fixture observation.
This supplements descriptive error metrics; it never fits production parameters
or changes a forecast or outcome.

Total bias, total MAE and team-score MAE are bootstrapped by **whole game**.
Home and away score errors stay paired: two scores from a match must not be
counted as two independent games. Original unadjusted predictions are used;
walk-forward counterfactual corrections remain a separate experiment.

The report contains reproducible 95% percentile intervals from the existing
IID bootstrap and fixed five-game circular moving-block bootstrap. Games are
ordered by verified fixture start then fixture ID, rather than late result
observation order. The IID interval requires two games; the block interval
requires at least ten. Absent intervals are null, not zero. These minimums are
algorithmic requirements, not evidence of adequate empirical sample size.

IID resampling assumes independent games. Circular blocks retain some local
ordering, including the wraparound assumption; they do not model every dependency
from recurring teams, shared schedules or season changes. Neither guarantees
nominal coverage, particularly in small samples. Constant observed errors can
produce a degenerate interval without establishing certainty about future errors.
`calibration_status` always remains `NOT_ESTABLISHED`.

Five synthetic tests cover empty/singleton samples, whole-game score pairing,
known constant errors, block eligibility, chronology, determinism and rejection
of mixed league/scope, duplicate fixtures and missing tipoff. These algorithm
tests do not measure basketball forecast accuracy.

The existing real NBA/ESPN and EuroLeague research ledgers were replayed offline.
Both still contain one original prediction and zero verified completed outcomes.
All error intervals are null. This is not a fresh provider HTTP validation.
Authentic completed results and a sufficient prospective sample remain required.
No merge, deployment, paid service or secret change is part of this module.

Validation: all 521 local regression tests passed; compilation and diff checks
passed. The exact offline reports are retained in
`evidence/bound-error-uncertainty-20261104.json`.

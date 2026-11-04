# FAZ16 live clock boundaries

Previous commit `1f57870` passed push CI 41885500498 and PR CI 41885513301.

FAZ16 is a deterministic scoring-rate heuristic. It does not measure possessions,
fit a calibrated live distribution, or simulate overtime. Its result now explicitly
states `REGULATION_ONLY` and `NOT_ESTABLISHED`. Those labels apply even when a
market comparison produces a heuristic edge flag or confidence boost; such flags
are not verified betting performance or a calibrated probability.

Live period, elapsed seconds, points and early-guard seconds must be actual
integers. Booleans, numeric strings, fractional values, NaN and missing values
are rejected instead of truncated. The early guard must lie within the first
period. Drift thresholds must be finite and satisfy `0 <= soft < trigger`.
These checks happen before early returns.

Clock selection uses the canonical registered league: NBA is four 720-second
periods and EuroLeague is four 600-second periods. Unsupported leagues remain
blocked; there is no generic 40-minute fallback at the public entry point.
Overtime and a fully completed regulation clock are rejected because they need
separate outcome/state handling. Nonzero points at zero elapsed time are also
rejected. Provider clock conversion, live status verification, and source-bound
live snapshots remain unimplemented; callers cannot treat a manual snapshot
as verified provider evidence.

Regression cases cover malformed clocks/guards/thresholds, canonical league
selection, regulation completion, overtime refusal, zero-time inconsistencies,
repeatability, scope and calibration labels. These tests use synthetic snapshots;
no real live-game validation or measured accuracy is claimed. The prematch
pipeline remains separate from FAZ16 and its contract test remains in the suite.

Validation: all 495 local regression tests passed, including six additional live
contract tests. Compilation and `git diff --check` passed. No live provider request,
ledger modification, production integration or deployment was performed.

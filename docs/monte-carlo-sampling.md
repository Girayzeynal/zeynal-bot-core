# Monte Carlo sampling error

Prior commit `46b3904` passed both push CI 41885883425 and PR CI 41885896500.

The deterministic prematch Monte Carlo result includes `sampling_diagnostics`.
For each regulation win/tie category it retains the count, number of trials,
estimated probability, binomial standard error and marginal 95% Wilson interval.
Over/under/push diagnostics exist only when a market total was supplied.
Category counts reconcile to the simulation size. Existing point estimates,
seed, draw sequence and regulation-only model scope are preserved.

Wilson intervals remain non-degenerate when an event appears zero times or
in every draw. Individual category intervals are marginal, not a simultaneous
confidence region. Standard errors are plug-in estimates; at zero events the
Wilson upper bound remains informative even though the plug-in error is zero.
Expected-total standard error is sample standard deviation divided by sqrt(n).
Score quantiles remain simulated score-distribution quantiles, not confidence
intervals for the model mean or real-world outcomes.

These diagnostics measure **simulation sampling error conditional on the supplied
model and parameters**. They do not measure errors in data, score-distribution
assumptions, correlations, future season shifts, or model calibration. Increasing
the simulation count reduces sampling error but does not establish predictive
accuracy. The result explicitly retains `calibration_status: NOT_ESTABLISHED`.
No empirical basketball parameters were fitted or invented by this change.
Boolean numeric magnitudes/correlations are rejected rather than interpreted
as 0 or 1.

Six synthetic regression tests verify known Wilson bounds, zero/all-event
uncertainty, sample-size effects, count/probability reconciliation, total-mean
standard error, absent-market behavior and boolean rejection. The original
Monte Carlo seed-repeatability, score covariance, scope and partition tests
remain in the full suite. Real-game probabilistic calibration still requires
source-bound original probabilities with matching regulation outcomes; the
current final-with-overtime research ledger must not be substituted.

Validation: all 501 local regression tests passed. Compilation and diff checks
passed. This change made no provider requests, altered no prediction ledgers,
and performed no production deployment or merge.

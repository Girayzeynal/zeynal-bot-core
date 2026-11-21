# Negative-error diagnostic — positive original forecasts protected (2026-11-21)

**Scope:** isolated research only, no production Fly deployment, model replacement, Telegram writes, SQLite mutation, source/provider calls or retrospective reissue of forecasts.

Run **after** producing a native verified quality report via the existing isolated `--error-review` mode:

```bash
cd ~/zeynal-hybrid-844
.venv/bin/python -B -m hybrid_engine.negative_error_audit \
  --report ~/zeynal-test-isolated/data/quality-phase924/reports/quality-4b2be633584586dd439fcfc3f6414001217ac4d9f8c60a9d8fc68c6e17a7a2f1.json
```

The command is available **only after this change lands in the isolated test checkout**; a PR alone does not install code on the Android phone. The report path is the exact pinned path from the user's 21 November device output; don't silently switch to an unrelated report.

## Semantics and safeguards

- Signed error = **forecast regulation total minus verified actual regulation total**.
- Negative signed cases: forecast **under** actual. Only this set is shown in detailed priority order, including exact frozen fixture, quarter signed errors, current-history-since-fit, fitted-model age, and baseline reference when available.
- Positive signed cases: forecast **over** actual. They are **not adjusted**, not replayed, not sent for calibration, and not exported as correction targets. Count and content fingerprint are recorded only as a no-mutation guard.
- Zero-error cases remain separate. Every source case is assigned to exactly one sign group; inconsistent signed errors, duplicate rows, missing report pins and unsupported report formats fail closed.
- No writing: input report hash is checked before and after; no output files are created. This does not magically attest other concurrent processes or earlier file histories.
- Any group is the original `league + season + fitted model version + fitted model digest`. No combining multiple fit versions or repeated snapshots into apparent new independent results.
- `negative_matched_reference` is **outcome-selected exploratory diagnostics** using a retrospective unpublished baseline. It must not be interpreted as a predictive bet signal, calibrated confidence or valid pregame classifier.
- **Do not apply sign-based corrections to future matches.** Whether a future game will have positive or negative signed residual is unknown pre-tipoff. If a new test-only challenger is evaluated, compare on identical frozen pretipoff inputs and separately protect previously positive original cases from degradation; no automatic promotion or production merge.

## 2026-11-21 source observation

54 local committed NBA first-publication fixtures; 46 matched native outcomes spanning 7 TSİ match-day clusters; frozen model regulation total MAE 14.86/RMSE 18.68, signed mean -0.35. Offline cross-mean reference on the same 46: MAE 14.82/RMSE 18.59. The old 18-case subset does not represent the complete device archive. This module does not claim its own fresh device E2E run. See issue #139 for complete user-supplied evidence.

## Verification

Synthetic tests:

```bash
.venv/bin/python -B -m unittest tests.test_negative_error_audit -v
```

The synthetic fixture scores are tests of classification/integrity, never counted as live performance. Only the user's private device can confirm the command's operation on its original pinned quality report.

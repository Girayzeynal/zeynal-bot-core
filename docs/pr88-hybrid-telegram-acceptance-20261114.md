# PR #88 — Hybrid Telegram acceptance gate (2026-11-14)

**Decision: NO-GO for production promotion.** The PR is a default-off research route, not a calibrated betting or production model. Keep PR draft until the gates below are evidenced. No changes to the existing Fly machine, volume, snapshots, or secrets.

## Verified CI
At commit `ae71f8619ef2fd1acbeb1363a774448ac99c2fed`, GitHub Actions `unit-tests` and `docker-build` completed successfully. This proves CI contracts, not a live Telegram exchange or model calibration.

## Prepared artifact
The model loader requires `ZEYNAL_HYBRID_PREPARED_PATH`, `ZEYNAL_HYBRID_PREPARED_SHA256`, and a separate `ZEYNAL_HYBRID_RESEARCH_DIR`. The trusted hash must come from a verified offline preparation, never from a user-supplied untrusted file alone. The offline command is:

```sh
python -m hybrid_engine.live_nba --prepare-manifest /isolated/manifest.json --output-directory /isolated/models
```

Use a time-stamped, permission-checked manifest of native past NBA labels, verify source/ingestion times and distinct fixture IDs, and independently record output path, hash, sample count, and source pins. The repository documentation describes 170 past games, but does not itself establish that the prepared artifact is present on the Fly machine. Do not enable the opt-in until the file is present and verified. Never put tokens or secrets in GitHub comments.

## Research-only Telegram gate
In a disposable, isolated test environment, with a separately authorized test bot, enable `ZEYNAL_HYBRID_NBA_RESEARCH=1` only after verifying the prepared artifact and a research directory **outside** `/data`. Check that `/analyze NBA YYYY-MM-DD Home vs Away` sends a clear uncalibrated research warning, respects the Telegram length budget, and returns ABSTAIN on missing/started/unverified fixtures. Capture Bot API delivery receipts and verify no production ledger mutation. A local HTTP mock does not satisfy this gate.

## Calibration gate
Use prospective snapshots created **before tipoff**, join them to verified final regulation scores by canonical fixture ID, and exclude duplicates, late snapshots, or data that arrived after prediction. Report paired MAE/RMSE, proper probability scores where applicable, empirical interval coverage and width, abstention rate, and comparison to FAZ13 on identical games. Do not infer superiority from four games or from Monte Carlo scenario count. Preserve original forecasts and source timestamps.

## Deployment decision
CI success is necessary but insufficient. Before merge/deploy, review the complete test-bot receipts, pinned artifact, isolated storage, calibration evidence, and explicit authorization. If any gate is missing, leave production FAZ13 routing unchanged.

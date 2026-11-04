"""Fail-closed calibration of pre-tipoff predictions against verified final scores.

No network requests, odds, inferred results, or backfilled predictions.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List


def evaluate_verified_totals(
    snapshots: List[Dict[str, Any]],
    verified_results: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Compute MAE, RMSE and signed bias from matched, verified final scores.

    snapshots: output of Faz23Engine.prematch_snapshots_for_calibration.
    verified_results: fixture_key -> {home_score, away_score, start_utc,
                                     status: "FINAL", verified: True}.
    Caller must independently verify score, start time and fixture identity.
    """
    if not isinstance(snapshots, list) or not isinstance(verified_results, dict):
        raise TypeError("Invalid calibration inputs")
    errors = []
    seen = set()
    excluded = {"duplicate": 0, "unverified_result": 0, "invalid_prediction": 0,
                "invalid_score": 0, "not_prematch": 0, "unverified_baseline": 0, "identity_mismatch": 0}
    for item in snapshots:
        if not isinstance(item, dict):
            raise TypeError("Invalid snapshot record")
        key = item.get("fixture_key")
        if not isinstance(key, str) or not key:
            raise ValueError("Missing fixture identity")
        if key in seen:
            excluded["duplicate"] += 1
            continue
        seen.add(key)
        result = verified_results.get(key)
        if not isinstance(result, dict) or result.get("verified") is not True or result.get("status") != "FINAL":
            excluded["unverified_result"] += 1
            continue
        # Match stored snapshot context against the keyed result identity.
        # Legacy records lacking context cannot establish a verified match.
        payload = item.get("payload")
        ctx = payload.get("ctx") if isinstance(payload, dict) else None
        if not isinstance(ctx, dict) or any(
            not isinstance(ctx.get(field), str) or not ctx[field]
            for field in ("date", "home", "away", "league")
        ) or f'{ctx["date"]}:{ctx["home"]}:{ctx["away"]}:{ctx["league"]}' != key:
            excluded["identity_mismatch"] += 1
            continue
        start = result.get("start_utc")
        ts = item.get("ts")
        if type(start) is not int or start <= 0 or type(ts) is not int or ts <= 0 or ts >= start:
            excluded["not_prematch"] += 1
            continue
        meta = item.get("payload", {}).get("meta") if isinstance(item.get("payload"), dict) else None
        # Manual baselines are permitted for exploratory analysis, not verified calibration.
        if not isinstance(meta, dict) or meta.get("data_quality") != "VERIFIED_BASELINE":
            excluded["unverified_baseline"] += 1
            continue
        pred = meta.get("expected_total")
        if isinstance(pred, bool) or not isinstance(pred, (int, float)) or not math.isfinite(pred) or pred < 0:
            excluded["invalid_prediction"] += 1
            continue
        home, away = result.get("home_score"), result.get("away_score")
        if any(type(v) is not int or v < 0 for v in (home, away)):
            excluded["invalid_score"] += 1
            continue
        errors.append(float(pred - (home + away)))
    n = len(errors)
    return {
        "sample_size": n,
        "mae": sum(abs(e) for e in errors) / n if n else None,
        "rmse": math.sqrt(sum(e * e for e in errors) / n) if n else None,
        "bias": sum(errors) / n if n else None,
        "excluded": excluded,
        "status": "EVALUATED" if n else "INSUFFICIENT_VERIFIED_DATA",
    }

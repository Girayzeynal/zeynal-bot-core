"""Strict offline NBA accuracy summary using verified fixture comparisons only.

No backfill, network requests, prediction generation, or model updates.
"""
from __future__ import annotations

import math
import sqlite3
from pathlib import Path

from telegram_result_audit import compare_fixture


def _validated_evaluated_result(result: dict) -> dict:
    """Reject malformed metric payloads instead of polluting published accuracy."""
    errors = result.get("signed_errors")
    if not isinstance(errors, dict):
        raise ValueError("Verified comparison missing signed errors")
    for key in ("total", "margin"):
        value = errors.get(key)
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("Verified comparison contains invalid signed error")
    direction = result.get("winner_direction_correct")
    if direction is not None and type(direction) is not bool:
        raise ValueError("Verified comparison contains invalid winner direction")
    return result


def verified_nba_accuracy(db_path: str, *, minimum_sample: int = 30) -> dict:
    if type(minimum_sample) is not int or minimum_sample < 1:
        raise ValueError("minimum_sample must be a positive integer")
    path = Path(db_path).resolve(strict=True)
    if not path.is_file():
        raise ValueError("Ledger path is not a file")
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        ids = [row[0] for row in db.execute(
            "SELECT fixture_id FROM predictions WHERE league='NBA' ORDER BY fixture_id"
        )]
    # Corrupt/legacy schemas can contain duplicate fixture rows. Never count
    # one game more than once or inflate the verified sample denominator.
    if len(ids) != len(set(ids)) or any(
        not isinstance(fixture_id, str) or not fixture_id.strip()
        for fixture_id in ids
    ):
        raise ValueError("Invalid or duplicate NBA fixture IDs in ledger")
    evaluated = []
    excluded = {}
    for fixture_id in ids:
        result = compare_fixture(str(path), fixture_id)
        if result["status"] != "EVALUATED":
            status = result["status"]
            excluded[status] = excluded.get(status, 0) + 1
            continue
        evaluated.append(_validated_evaluated_result(result))
    count = len(evaluated)
    if not count:
        return {"status": "INSUFFICIENT_VERIFIED_PAIRS", "verified": 0,
                "total_predictions": len(ids), "excluded": excluded,
                "total_mae": None, "margin_mae": None,
                "total_bias": None, "margin_bias": None,
                "total_rmse": None, "margin_rmse": None,
                "max_total_abs_error": None, "max_margin_abs_error": None,
                "total_error_over_10": 0, "total_error_over_20": 0,
                "winner_accuracy": None,
                "winner_sample": 0, "calibration": "NOT_VERIFIED"}
    total_mae = math.fsum(abs(r["signed_errors"]["total"]) for r in evaluated) / count
    margin_mae = math.fsum(abs(r["signed_errors"]["margin"]) for r in evaluated) / count
    total_bias = math.fsum(r["signed_errors"]["total"] for r in evaluated) / count
    margin_bias = math.fsum(r["signed_errors"]["margin"] for r in evaluated) / count
    total_rmse = math.sqrt(math.fsum(
        r["signed_errors"]["total"] ** 2 for r in evaluated) / count)
    margin_rmse = math.sqrt(math.fsum(
        r["signed_errors"]["margin"] ** 2 for r in evaluated) / count)
    max_total_abs_error = max(abs(r["signed_errors"]["total"]) for r in evaluated)
    max_margin_abs_error = max(abs(r["signed_errors"]["margin"]) for r in evaluated)
    total_error_over_10 = sum(abs(r["signed_errors"]["total"]) > 10 for r in evaluated)
    total_error_over_20 = sum(abs(r["signed_errors"]["total"]) > 20 for r in evaluated)
    directional = [r["winner_direction_correct"] for r in evaluated
                   if r["winner_direction_correct"] is not None]
    return {"status": ("EVALUATED" if count >= minimum_sample
                       else "LOW_VERIFIED_SAMPLE"), "verified": count,
            "total_predictions": len(ids), "excluded": excluded,
            "total_mae": total_mae, "margin_mae": margin_mae,
            "total_bias": total_bias, "margin_bias": margin_bias,
            "total_rmse": total_rmse, "margin_rmse": margin_rmse,
            "max_total_abs_error": max_total_abs_error,
            "max_margin_abs_error": max_margin_abs_error,
            "total_error_over_10": total_error_over_10,
            "total_error_over_20": total_error_over_20,
            "winner_accuracy": (sum(directional) / len(directional)
                                if directional else None),
            "winner_sample": len(directional),
            "calibration": "NOT_VERIFIED"}

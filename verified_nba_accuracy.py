"""Strict offline NBA accuracy summary using verified fixture comparisons only.

No backfill, network requests, prediction generation, or model updates.
"""
from __future__ import annotations

import math
import sqlite3
from pathlib import Path

from telegram_result_audit import compare_fixture


def verified_nba_accuracy(db_path: str) -> dict:
    path = Path(db_path).resolve(strict=True)
    if not path.is_file():
        raise ValueError("Ledger path is not a file")
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        ids = [row[0] for row in db.execute(
            "SELECT fixture_id FROM predictions WHERE league='NBA' ORDER BY fixture_id"
        )]
    evaluated = []
    excluded = {}
    for fixture_id in ids:
        result = compare_fixture(str(path), fixture_id)
        if result["status"] != "EVALUATED":
            status = result["status"]
            excluded[status] = excluded.get(status, 0) + 1
            continue
        evaluated.append(result)
    count = len(evaluated)
    if not count:
        return {"status": "INSUFFICIENT_VERIFIED_PAIRS", "verified": 0,
                "total_predictions": len(ids), "excluded": excluded,
                "total_mae": None, "margin_mae": None, "winner_accuracy": None,
                "winner_sample": 0, "calibration": "NOT_VERIFIED"}
    total_mae = math.fsum(abs(r["signed_errors"]["total"]) for r in evaluated) / count
    margin_mae = math.fsum(abs(r["signed_errors"]["margin"]) for r in evaluated) / count
    directional = [r["winner_direction_correct"] for r in evaluated
                   if r["winner_direction_correct"] is not None]
    return {"status": "EVALUATED", "verified": count,
            "total_predictions": len(ids), "excluded": excluded,
            "total_mae": total_mae, "margin_mae": margin_mae,
            "winner_accuracy": (sum(directional) / len(directional)
                                if directional else None),
            "winner_sample": len(directional),
            "calibration": "NOT_VERIFIED"}

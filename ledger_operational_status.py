"""Read-only operational truth about prediction and calibration pipelines.

Counts are not accuracy metrics. Never claim autonomous calibration from table
names or a scheduled task that only writes snapshots.
"""
from __future__ import annotations

from pathlib import Path
import sqlite3


def ledger_operational_status(path: str | None) -> dict:
    if not path:
        return {"status": "DISABLED", "predictions": None, "outcomes": None,
                "paired": None, "calibration": "NOT_VERIFIED"}
    location = Path(path).resolve()
    if not location.is_file():
        return {"status": "MISSING", "predictions": None, "outcomes": None,
                "paired": None, "calibration": "NOT_VERIFIED"}
    try:
        with sqlite3.connect(location.as_uri() + "?mode=ro", uri=True) as db:
            db.execute("PRAGMA query_only=ON")
            tables = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"predictions", "outcomes"}.issubset(tables):
                return {"status": "INCOMPLETE", "predictions": None,
                        "outcomes": None, "paired": None,
                        "calibration": "NOT_VERIFIED"}
            predictions = db.execute(
                "SELECT COUNT(*) FROM predictions WHERE league='NBA'").fetchone()[0]
            outcomes = db.execute(
                "SELECT COUNT(*) FROM outcomes WHERE league='NBA'").fetchone()[0]
            # A result timestamp alone cannot prove a prediction was pregame.
            # Require a stored fixture tipoff and strictly ordered timestamps.
            if "fixture_starts" in tables:
                paired = db.execute("""SELECT COUNT(*) FROM predictions p
                    JOIN outcomes o ON o.league=p.league AND o.fixture_id=p.fixture_id
                    JOIN fixture_starts f ON f.league=p.league
                        AND f.fixture_id=p.fixture_id
                    WHERE p.league='NBA'
                    AND p.prediction_ts_utc < f.start_ts_utc
                    AND f.start_ts_utc < o.result_ts_utc
                    AND p.scope=o.scope""").fetchone()[0]
            else:
                paired = 0
    except (OSError, sqlite3.Error):
        return {"status": "UNREADABLE", "predictions": None,
                "outcomes": None, "paired": None,
                "calibration": "NOT_VERIFIED"}
    return {"status": "READABLE", "predictions": predictions,
            "outcomes": outcomes, "paired": paired,
            "calibration": "NOT_VERIFIED"}

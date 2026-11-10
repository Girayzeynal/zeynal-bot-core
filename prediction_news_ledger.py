"""Immutable, optional news context linked to an existing pregame prediction.

This is a post-recording evidence attachment, NOT a model input or evidence
that news changed a forecast. It cannot be replaced or attached to outcomes.
"""
import json

from news_context_snapshot import validate_news_context


def attach_news_context(ledger, bundle, *, league: str, fixture_id: str) -> bool:
    from prediction_ledger import PredictionLedger
    if not isinstance(ledger, PredictionLedger):
        raise TypeError("PredictionLedger required")
    ledger._identity(league, fixture_id)
    with ledger._connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT prediction_ts_utc FROM predictions WHERE league=? AND fixture_id=?",
            (league, fixture_id)).fetchone()
        if row is None:
            raise ValueError("News cannot be attached without an archived prediction")
        validate_news_context(bundle, league=league, fixture_id=fixture_id,
                              prediction_utc=row[0])
        serialized = json.dumps(bundle, sort_keys=True, ensure_ascii=False,
                                separators=(",", ":"), allow_nan=False)
        db.execute("""CREATE TABLE IF NOT EXISTS prediction_news_context (
            league TEXT NOT NULL, fixture_id TEXT NOT NULL,
            context_json TEXT NOT NULL, context_sha256 TEXT NOT NULL,
            PRIMARY KEY (league, fixture_id)
        )""")
        existing = db.execute(
            "SELECT context_json, context_sha256 FROM prediction_news_context "
            "WHERE league=? AND fixture_id=?", (league, fixture_id)).fetchone()
        if existing is not None:
            if existing != (serialized, bundle["sha256"]):
                raise ValueError("Immutable news context already differs")
            return False
        db.execute("INSERT INTO prediction_news_context VALUES (?,?,?,?)",
                   (league, fixture_id, serialized, bundle["sha256"]))
        return True


def load_news_context(ledger, *, league: str, fixture_id: str):
    from prediction_ledger import PredictionLedger
    if not isinstance(ledger, PredictionLedger):
        raise TypeError("PredictionLedger required")
    ledger._identity(league, fixture_id)
    with ledger._connect() as db:
        row = db.execute(
            "SELECT prediction_ts_utc FROM predictions WHERE league=? AND fixture_id=?",
            (league, fixture_id)).fetchone()
        if row is None:
            raise ValueError("No archived prediction")
        table = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='prediction_news_context'"
        ).fetchone()
        if table is None:
            return None
        saved = db.execute(
            "SELECT context_json, context_sha256 FROM prediction_news_context "
            "WHERE league=? AND fixture_id=?", (league, fixture_id)).fetchone()
    if saved is None:
        return None
    bundle = json.loads(saved[0])
    if not isinstance(bundle, dict) or bundle.get("sha256") != saved[1]:
        raise ValueError("Stored news context digest mismatch")
    validate_news_context(bundle, league=league, fixture_id=fixture_id,
                          prediction_utc=row[0])
    return bundle

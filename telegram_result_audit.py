"""Read-only, fail-closed reporting for archived NBA pregame predictions.

No provider requests, model inference or database writes occur in this module.\n"""
from __future__ import annotations

import math
from pathlib import Path
import sqlite3


def _db(path):
    location = Path(path).resolve(strict=True)
    if not location.is_file():
        raise ValueError("Ledger path is not a file")
    return sqlite3.connect(location.as_uri() + "?mode=ro", uri=True)


def compare_fixture(db_path: str, fixture_id: str, league: str = "NBA") -> dict:
    """Return verified comparison only for an original, bound pregame forecast."""
    if league != "NBA" or not isinstance(fixture_id, str) or not fixture_id.strip():
        raise ValueError("Unsupported league or fixture ID")
    with _db(db_path) as db:
        db.execute("PRAGMA query_only=ON")
        row = db.execute(
            """SELECT p.prediction_ts_utc,p.expected_home,p.expected_away,
                      p.home_win_probability,p.scope,o.result_ts_utc,
                      o.actual_home,o.actual_away,o.scope,f.start_ts_utc,
                      v.start_ts_utc,v.provider,v.provider_fixture_id,
                      i.snapshot_sha256,e.evidence_sha256
               FROM predictions p
               LEFT JOIN outcomes o ON o.league=p.league AND o.fixture_id=p.fixture_id
               LEFT JOIN fixture_starts f ON f.league=p.league AND f.fixture_id=p.fixture_id
               LEFT JOIN fixture_provenance v ON v.league=p.league AND v.fixture_id=p.fixture_id
               LEFT JOIN prediction_inputs i ON i.league=p.league AND i.fixture_id=p.fixture_id
               LEFT JOIN outcome_evidence e ON e.league=p.league AND e.fixture_id=p.fixture_id
               WHERE p.league=? AND p.fixture_id=?""",
            (league, fixture_id),
        ).fetchone()
    if row is None:
        return {"status": "NO_PREMATCH_PREDICTION", "fixture_id": fixture_id}
    (ts, home, away, probability, scope, result_ts, actual_home, actual_away,
     result_scope, start, provider_start, provider, provider_id, input_sha, final_sha) = row
    if start is None or provider_start != start or provider != "ESPN" or provider_id != fixture_id or not input_sha:
        return {"status": "UNVERIFIED_PROVENANCE", "fixture_id": fixture_id}
    if not isinstance(ts, int) or ts >= start:
        return {"status": "INVALID_PREGAME_TIME", "fixture_id": fixture_id}
    if result_ts is None:
        return {"status": "AWAITING_VERIFIED_FINAL", "fixture_id": fixture_id}
    if result_scope != scope or scope != "FINAL_WITH_OT":
        return {"status": "INCOMPATIBLE_SCOPE", "fixture_id": fixture_id}
    if not final_sha or not start < result_ts:
        return {"status": "UNVERIFIED_FINAL", "fixture_id": fixture_id}

    # Cryptographic input/result binding must be validated by the canonical ledger.
    from prediction_ledger import PredictionLedger
    ledger = object.__new__(PredictionLedger)
    ledger.db_path = str(Path(db_path).resolve())
    ledger._connect = lambda: _db(db_path)
    inputs = ledger.load_prediction_inputs(league, fixture_id)
    evidence = ledger.load_outcome_evidence(league, fixture_id)
    if inputs is None or evidence is None or inputs["sha256"] != input_sha or evidence["sha256"] != final_sha:
        return {"status": "UNVERIFIED_FINAL", "fixture_id": fixture_id}

    values = (home, away)
    if any(not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in values):
        raise ValueError("Invalid stored prediction")
    predicted_total, actual_total = home + away, actual_home + actual_away
    predicted_margin, actual_margin = home - away, actual_home - actual_away
    return {
        "status": "EVALUATED", "fixture_id": fixture_id,
        "predicted": {"home": home, "away": away, "total": predicted_total},
        "actual": {"home": actual_home, "away": actual_away, "total": actual_total},
        "signed_errors": {
            "home": home - actual_home, "away": away - actual_away,
            "total": predicted_total - actual_total,
            "margin": predicted_margin - actual_margin,
        },
        "winner_direction_correct": None if predicted_margin == 0 or actual_margin == 0
            else (predicted_margin > 0) == (actual_margin > 0),
        "home_win_probability": probability,
        "scope": scope,
        "verified_final_sha256": final_sha,
    }


def format_comparison(report: dict) -> str:
    """Compact Telegram-safe plain-text output; no Markdown interpolation."""
    status = report["status"]
    fixture = report["fixture_id"]
    if status != "EVALUATED":
        return f"NBA {fixture}: {status}"
    pred, actual, errors = report["predicted"], report["actual"], report["signed_errors"]
    return (
        f"NBA {fixture} | DOGRULANMIS KARSILASTIRMA\n"
        f"Tahmin: {pred['home']:.1f}-{pred['away']:.1f} (toplam {pred['total']:.1f})\n"
        f"Sonuc: {actual['home']}-{actual['away']} (toplam {actual['total']})\n"
        f"Mutlak toplam hata: {abs(errors['total']):.1f}\n"
        f"Mutlak fark hatasi: {abs(errors['margin']):.1f}\n"
        f"Kazanan yonu: {report['winner_direction_correct']}"
    )

"""Regression tests for read-only Telegram result audit."""
import sqlite3
import tempfile
from pathlib import Path

import unittest

from prediction_ledger import PredictionLedger, PredictionRecord, OutcomeRecord
from telegram_result_audit import compare_fixture, format_comparison


def _ledger(tmp_path):
    path = tmp_path / "ledger.sqlite"
    ledger = PredictionLedger(str(path))
    ledger.record_fixture_start("NBA", "_schema_init", 1)
    ledger.record_fixture_provenance("NBA", "_schema_init", "ESPN", "_schema_init", 1)
    return path


def test_missing_forecast_does_not_create_any_record(tmp_path):
    path = _ledger(tmp_path)
    before = path.stat().st_size
    result = compare_fixture(str(path), "401909922")
    assert result["status"] == "NO_PREMATCH_PREDICTION"
    assert path.stat().st_size == before


def test_missing_fixture_identity_fails_closed(tmp_path):
    path = _ledger(tmp_path)
    ledger = PredictionLedger(str(path))
    ledger.record_prediction(PredictionRecord(
        "401909922", "NBA", 100, 110.5, 109.5, None))
    result = compare_fixture(str(path), "401909922")
    assert result["status"] == "UNVERIFIED_PROVENANCE"


def test_post_tipoff_prediction_is_not_accepted(tmp_path):
    path = _ledger(tmp_path)
    ledger = PredictionLedger(str(path))
    ledger.record_prediction(PredictionRecord(
        "401909922", "NBA", 200, 110.5, 109.5, None))
    ledger.record_fixture_start("NBA", "401909922", 100)
    ledger.record_fixture_provenance("NBA", "401909922", "ESPN", "401909922", 100)
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO prediction_inputs VALUES (?,?,?,?)",
                   ("NBA", "401909922", "{}", "placeholder"))
    assert compare_fixture(str(path), "401909922")["status"] == "INVALID_PREGAME_TIME"


def test_invalid_league_rejected(tmp_path):
    path = _ledger(tmp_path)
    try:
        compare_fixture(str(path), "401909922", "EUROLEAGUE")
    except ValueError:
        pass
    else:
        raise AssertionError("Invalid league must be rejected")


def test_plain_text_report(tmp_path):
    path = _ledger(tmp_path)
    result = compare_fixture(str(path), "401909922")
    assert format_comparison(result) == "NBA 401909922: NO_PREMATCH_PREDICTION"

def test_awaiting_final_does_not_claim_a_result(tmp_path):
    path = _ledger(tmp_path)
    ledger = PredictionLedger(str(path))
    ledger.record_prediction(PredictionRecord(
        "401909922", "NBA", 100, 110.5, 109.5, None))
    ledger.record_fixture_start("NBA", "401909922", 200)
    ledger.record_fixture_provenance("NBA", "401909922", "ESPN", "401909922", 200)
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO prediction_inputs VALUES (?,?,?,?)",
                   ("NBA", "401909922", "{}", "placeholder"))
    assert compare_fixture(str(path), "401909922")["status"] == "AWAITING_VERIFIED_FINAL"


def test_mismatched_scope_is_rejected(tmp_path):
    path = _ledger(tmp_path)
    ledger = PredictionLedger(str(path))
    ledger.record_prediction(PredictionRecord(
        "401909922", "NBA", 100, 110.5, 109.5, None))
    ledger.record_fixture_start("NBA", "401909922", 200)
    ledger.record_fixture_provenance("NBA", "401909922", "ESPN", "401909922", 200)
    ledger.record_outcome(OutcomeRecord(
        "401909922", "NBA", 300, 120, 100, "REGULATION_ONLY"))
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO prediction_inputs VALUES (?,?,?,?)",
                   ("NBA", "401909922", "{}", "placeholder"))
    assert compare_fixture(str(path), "401909922")["status"] == "INCOMPATIBLE_SCOPE"

def test_legacy_ledger_without_provenance_tables_fails_closed(tmp_path):
    path = tmp_path / "legacy.sqlite"
    PredictionLedger(str(path))
    assert compare_fixture(str(path), "401909922")["status"] == "LEDGER_SCHEMA_INCOMPLETE"


class TelegramResultAuditUnittestTests(unittest.TestCase):
    """Run the same regression cases in the repository's unittest discovery."""

    def test_missing_forecast_does_not_create_any_record(self):
        with tempfile.TemporaryDirectory() as root:
            test_missing_forecast_does_not_create_any_record(Path(root))

    def test_missing_fixture_identity_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            test_missing_fixture_identity_fails_closed(Path(root))

    def test_post_tipoff_prediction_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as root:
            test_post_tipoff_prediction_is_not_accepted(Path(root))

    def test_invalid_league_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            test_invalid_league_rejected(Path(root))

    def test_plain_text_report(self):
        with tempfile.TemporaryDirectory() as root:
            test_plain_text_report(Path(root))

    def test_awaiting_final_does_not_claim_a_result(self):
        with tempfile.TemporaryDirectory() as root:
            test_awaiting_final_does_not_claim_a_result(Path(root))

    def test_mismatched_scope_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            test_mismatched_scope_is_rejected(Path(root))

    def test_legacy_ledger_without_provenance_tables_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            test_legacy_ledger_without_provenance_tables_fails_closed(Path(root))

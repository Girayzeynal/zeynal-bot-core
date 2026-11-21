"""Synthetic, not basketball accuracy: pregame market-direction evidence gates."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sqlite3
import tempfile
from unittest import TestCase
from unittest.mock import patch

from core.team_identity import digest
from hybrid_engine.pregame_direction_evidence import quote_row,inspect,inspect_file


def receipt():
    return dict(bookmaker="Recorded Bookmaker",market="TOTAL",line=230.5,
                quote_sha256="f"*64,observed_at_utc=100,
                age_at_prediction_seconds=100,
                freshness_status="FRESH_AT_PREDICTION",
                settlement_scope="UNKNOWN")


def example():
    snapshot=dict(league="NBA",season="2026/2027",fixture_id="fixture",
                  model_digest="model",prediction_generated_at_utc=200,
                  fixture_start_utc=300,provider_fixture_ids=["1234"],
                  prediction=dict(total=220.0),
                  home=dict(official_name="Home"),away=dict(official_name="Away"),
                  source_assets=[dict(file="source-any.json",sha256="a"*64)])
    forecast=dict(league="NBA",season="2026/2027",fixture_id="fixture",
                  model_digest="model",snapshot_sha256=digest(snapshot),
                  prediction_generated_at_utc=200,prediction=[110.0,110.0],
                  actual=[120.0,120.0])
    payload=dict(format="PHASE92_READ_ONLY_QUALITY_REPORT_V1",
                 archive_audit=dict(performance_status="READ_ONLY_NATIVE_VERIFIED",
                     performance=dict(status="VERIFIED_LIVE_REPORT",forecasts=[forecast])))
    return snapshot,dict(payload=payload,sha256=digest(payload))


class DirectionEvidenceTests(TestCase):
    def test_original_barem_yields_research_side_not_a_historical_pick(self):
        record=quote_row(receipt(),220.0,240.0)
        self.assertEqual(record["original_model_mean_relative_to_line"],"ALT")
        self.assertEqual(record["research_regulation_only_side"],"UST")
        self.assertFalse(record["original_direction_publication_proven"])
        self.assertIsNone(record["official_bookmaker_direction_result"])

    def test_no_observed_barem_is_not_treated_as_a_direction_success(self):
        snapshot,report=example()
        with tempfile.TemporaryDirectory() as folder:
            ledger=Path(folder)/"ledger.sqlite"
            assets=Path(folder)/"assets";assets.mkdir()
            with sqlite3.connect(ledger) as db:
                db.execute("CREATE TABLE live_analysis_snapshots (league TEXT,fixture_id TEXT,model_digest TEXT,payload TEXT,sha256 TEXT)")
                db.execute("INSERT INTO live_analysis_snapshots VALUES(?,?,?,?,?)",
                           ("NBA","fixture","model","{}", "hash"))
            with patch("hybrid_engine.pregame_direction_evidence.LiveAnalysisLedger._decode",return_value=snapshot),patch(
                    "hybrid_engine.pregame_direction_evidence.observed_market_evidence",return_value=[]) as quotes:
                result=inspect(report,ledger,assets)
            self.assertEqual(result["counts"]["fixtures"],1)
            self.assertEqual(result["no_quote_fixture_count"],1)
            self.assertIsNone(result["actual_original_direction_decision_hit_rate"])
            self.assertEqual(result["market_lines_manufactured"],0)
            self.assertFalse(result["positive_signed_original_cases_modified"])
            self.assertTrue(quotes.called)

    def test_pregame_saved_quote_is_counted_without_claiming_win_rate(self):
        snapshot,report=example()
        with tempfile.TemporaryDirectory() as folder:
            ledger=Path(folder)/"ledger.sqlite"
            assets=Path(folder)/"assets";assets.mkdir()
            with sqlite3.connect(ledger) as db:
                db.execute("CREATE TABLE live_analysis_snapshots (league TEXT,fixture_id TEXT,model_digest TEXT,payload TEXT,sha256 TEXT)")
                db.execute("INSERT INTO live_analysis_snapshots VALUES(?,?,?,?,?)",
                           ("NBA","fixture","model","{}","hash"))
            with patch("hybrid_engine.pregame_direction_evidence.LiveAnalysisLedger._decode",return_value=snapshot),patch(
                    "hybrid_engine.pregame_direction_evidence.observed_market_evidence",return_value=[receipt()]):
                result=inspect(report,ledger,assets)
            self.assertEqual(result["counts"]["fixtures_with_total_quote"],1)
            self.assertEqual(result["counts"]["fixtures_with_fresh_total_quote"],1)
            self.assertEqual(result["counts"]["fixtures_with_quote_and_result"],1)
            self.assertIsNone(result["actual_bookmaker_direction_settlement_rate"])
            self.assertEqual(result["fixture_quotes"][0]["observed_total_quote_rows"][0]["original_model_mean_relative_to_line"],"ALT")

    def test_quality_pin_and_bad_quote_rejected(self):
        _, report=example()
        report["payload"]["archive_audit"]["performance"]["status"]="BAD"
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with self.assertRaisesRegex(ValueError,"REPORT_PIN"):
                inspect(report,root,root)
        wrong=receipt();wrong["line"]=float("nan")
        with self.assertRaisesRegex(ValueError,"FINITE"):
            quote_row(wrong,220,240)


if __name__=="__main__":
    import unittest
    unittest.main()

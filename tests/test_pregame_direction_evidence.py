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
from hybrid_engine.pregame_direction_evidence import quote_row,inspect,inspect_file,research_direction_summary


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

    def test_research_direction_summary_confusion_is_not_published_accuracy(self):
        quotes=[
            quote_row(receipt(),220,240),    # frozen mean ALT, actual UST
            quote_row(receipt(),240,250),    # frozen mean UST, actual UST
            quote_row(receipt(),240,225),    # frozen mean UST, actual ALT
            quote_row(receipt(),220,210),    # frozen mean ALT, actual ALT
        ]
        fixtures=[
            dict(fixture_id=str(i),provider_fixture_ids=[str(i)],
                 home="Home",away="Away",actual_native_regulation_result_available=True,
                 observed_total_quote_rows=[q])
            for i,q in enumerate(quotes)
        ]
        original=json.dumps(fixtures,sort_keys=True)
        result=research_direction_summary(fixtures)
        self.assertEqual(json.dumps(fixtures,sort_keys=True),original)
        self.assertEqual((result["matched"],result["mismatched"]),(2,2))
        self.assertEqual(result["confusion_matrix"],
                         {"ALT_UST":1,"UST_UST":1,"UST_ALT":1,"ALT_ALT":1})
        self.assertEqual(result["by_score_error_sign"]["PRED_MINUS_ACTUAL_POSITIVE"]["n"],2)
        self.assertEqual(result["by_score_error_sign"]["PRED_MINUS_ACTUAL_NEGATIVE"]["n"],2)
        self.assertIsNone(result["published_pregame_direction_accuracy"])
        self.assertIsNone(result["official_bookmaker_settlement_accuracy"])
        self.assertTrue(result["no_selection_or_correction_performed"])

    def test_direction_push_and_duplicate_barem_not_counted_as_wins(self):
        first=quote_row(receipt(),220,240)
        push=quote_row(receipt(),220,230.5)
        equal=quote_row(receipt(),230.5,240)
        records=[
            dict(fixture_id="multi",provider_fixture_ids=["1"],
                 actual_native_regulation_result_available=True,
                 observed_total_quote_rows=[first,first]),
            dict(fixture_id="push",provider_fixture_ids=["2"],
                 actual_native_regulation_result_available=True,
                 observed_total_quote_rows=[push]),
            dict(fixture_id="equal",provider_fixture_ids=["3"],
                 actual_native_regulation_result_available=True,
                 observed_total_quote_rows=[equal]),
            dict(fixture_id="missing",provider_fixture_ids=["4"],
                 actual_native_regulation_result_available=True,
                 observed_total_quote_rows=[]),
        ]
        # Exact line equals actual => no decided result, not a failure.
        records[1]["observed_total_quote_rows"][0]["research_regulation_only_side"]="ESIT"
        result=research_direction_summary(records)
        self.assertEqual(result["eligible_unique_fixtures"],0)
        self.assertIsNone(result["descriptive_regulation_direction_agreement"])
        self.assertEqual(result["status_counts"]["multiple_fresh_quotes_ambiguous_fixture"],1)
        self.assertEqual(result["status_counts"]["regulation_push_not_decided"],1)
        self.assertEqual(result["status_counts"]["model_on_barem_no_direction"],1)
        self.assertEqual(result["status_counts"]["with_final_but_no_quote"],1)

    def test_research_gap_buckets_are_descriptive_not_tuned(self):
        quotes=[quote_row(receipt(),231,220),quote_row(receipt(),235,220),
                quote_row(receipt(),250,220)]
        records=[dict(fixture_id=str(i),provider_fixture_ids=[str(i)],
                      actual_native_regulation_result_available=True,
                      observed_total_quote_rows=[q]) for i,q in enumerate(quotes)]
        out=research_direction_summary(records)
        self.assertEqual(out["by_original_mean_line_gap"]["0-3"]["n"],1)
        self.assertEqual(out["by_original_mean_line_gap"]["3-7"]["n"],1)
        self.assertEqual(out["by_original_mean_line_gap"]["7+"]["n"],1)

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

"""News audit never confuses archived context with a model input."""
from dataclasses import replace
import tempfile
from pathlib import Path
import unittest

from basketball_news_intelligence import NewsItem
from news_context_snapshot import seal_news_context
from prediction_ledger import PredictionLedger, PredictionRecord
from prediction_news_ledger import attach_news_context
from prediction_news_audit import audit_prediction_news


class PredictionNewsAuditTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.ledger = PredictionLedger(str(Path(tmp.name) / "ledger.sqlite"))
        self.kw = dict(league="NBA", fixture_id="401999001")
        self.ledger.record_prediction(PredictionRecord(
            fixture_id="401999001", league="NBA", prediction_ts_utc=10000,
            expected_home=110, expected_away=109, home_win_probability=None))
        self.item = NewsItem(
            source_id="editor", source_group="publisher-a",
            url="https://example.org/a", league="NBA", fixture_id="401999001",
            subject_type="COACH", subject_id="coach-a", category="TACTICS",
            claim="slower pace expected", published_at_utc=9000,
            retrieved_at_utc=9100, evidence_type="EDITORIAL",
            authenticated=True)

    def attach(self, items):
        bundle = seal_news_context(items, prediction_utc=10000, **self.kw)
        attach_news_context(self.ledger, bundle, **self.kw)

    def test_missing_snapshot_is_explicit(self):
        report = audit_prediction_news(self.ledger, **self.kw)
        self.assertEqual(report.status, "NO_NEWS_SNAPSHOT")
        self.assertFalse(report.model_consumed_news)

    def test_editorial_does_not_become_verified_prediction_effect(self):
        self.attach([self.item])
        report = audit_prediction_news(self.ledger, **self.kw)
        self.assertEqual((report.editorial_items, report.official_items), (1, 0))
        self.assertIn("EDITORIAL_IS_NOT_VERIFIED_FACT", report.warnings)
        self.assertIn("NEWS_NOT_CONSUMED_BY_PREDICTION_MODEL", report.warnings)

    def test_uncorroborated_reporting_flagged(self):
        self.attach([replace(self.item, evidence_type="REPORTING")])
        report = audit_prediction_news(self.ledger, **self.kw)
        self.assertIn("REPORTING_NOT_INDEPENDENTLY_CORROBORATED", report.warnings)

    def test_empty_evidence_not_marked_as_complete(self):
        self.attach([])
        report = audit_prediction_news(self.ledger, **self.kw)
        self.assertIn("NO_ELIGIBLE_PREGAME_NEWS", report.warnings)

    def test_official_evidence_does_not_imply_model_use(self):
        self.attach([replace(self.item, evidence_type="OFFICIAL")])
        report = audit_prediction_news(self.ledger, **self.kw)
        self.assertEqual(report.official_items, 1)
        self.assertFalse(report.model_consumed_news)


if __name__ == "__main__":
    unittest.main()

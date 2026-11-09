"""Real SQLite news-to-prediction binding and immutable replay tests."""
from dataclasses import replace
import sqlite3
import tempfile
from pathlib import Path
import unittest

from basketball_news_intelligence import NewsItem
from news_context_snapshot import seal_news_context
from prediction_ledger import PredictionLedger, PredictionRecord
from prediction_news_ledger import attach_news_context, load_news_context


class PredictionNewsLedgerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = str(Path(temp.name) / "ledger.sqlite")
        self.ledger = PredictionLedger(self.path)
        self.kw = dict(league="NBA", fixture_id="401999001")
        self.item = NewsItem(
            source_id="official", source_group="official", url="https://example.org/a",
            league="NBA", fixture_id="401999001", subject_type="COACH",
            subject_id="coach-1", category="ROTATION", claim="rotation changed",
            published_at_utc=9000, retrieved_at_utc=9100,
            evidence_type="OFFICIAL", authenticated=True)
        self.bundle = seal_news_context([self.item], prediction_utc=10000, **self.kw)

    def predict(self):
        self.ledger.record_prediction(PredictionRecord(
            fixture_id="401999001", league="NBA", prediction_ts_utc=10000,
            expected_home=110.0, expected_away=108.0,
            home_win_probability=None))

    def test_cannot_attach_without_prediction(self):
        with self.assertRaises(ValueError):
            attach_news_context(self.ledger, self.bundle, **self.kw)

    def test_roundtrip_reopen_database(self):
        self.predict()
        self.assertTrue(attach_news_context(self.ledger, self.bundle, **self.kw))
        self.assertEqual(load_news_context(PredictionLedger(self.path), **self.kw), self.bundle)

    def test_identical_retry_is_idempotent(self):
        self.predict()
        self.assertTrue(attach_news_context(self.ledger, self.bundle, **self.kw))
        self.assertFalse(attach_news_context(self.ledger, self.bundle, **self.kw))

    def test_conflicting_news_cannot_replace_original(self):
        self.predict()
        attach_news_context(self.ledger, self.bundle, **self.kw)
        other = seal_news_context([replace(self.item, claim="different")],
                                  prediction_utc=10000, **self.kw)
        with self.assertRaises(ValueError):
            attach_news_context(self.ledger, other, **self.kw)
        self.assertEqual(load_news_context(self.ledger, **self.kw), self.bundle)

    def test_tampering_detected(self):
        self.predict()
        attach_news_context(self.ledger, self.bundle, **self.kw)
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE prediction_news_context SET context_sha256='bad'")
        with self.assertRaises(ValueError):
            load_news_context(self.ledger, **self.kw)

    def test_future_news_does_not_enter_snapshot(self):
        self.predict()
        future = replace(self.item, published_at_utc=10001, retrieved_at_utc=10002)
        bundle = seal_news_context([future], prediction_utc=10000, **self.kw)
        self.assertEqual(bundle["payload"]["items"], [])
        self.assertTrue(attach_news_context(self.ledger, bundle, **self.kw))


if __name__ == "__main__":
    unittest.main()

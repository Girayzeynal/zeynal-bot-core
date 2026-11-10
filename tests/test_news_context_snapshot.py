"""Archival replay checks for pregame news context."""
from copy import deepcopy
from dataclasses import replace
import unittest

from basketball_news_intelligence import NewsItem
from news_context_snapshot import seal_news_context, validate_news_context


class NewsContextSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.kw = dict(league="NBA", fixture_id="401999001", prediction_utc=10000)
        self.a = NewsItem(
            source_id="report-a", source_group="group-a", url="https://example.org/a",
            league="NBA", fixture_id="401999001", subject_type="PLAYER",
            subject_id="p1", category="MINUTES", claim="limited minutes",
            published_at_utc=9000, retrieved_at_utc=9100,
            evidence_type="REPORTING", authenticated=True)
        self.b = replace(self.a, source_id="report-b", source_group="group-b",
                         url="https://example.org/b")

    def test_round_trip(self):
        bundle = seal_news_context([self.a, self.b], **self.kw)
        self.assertTrue(validate_news_context(bundle, **self.kw))
        self.assertEqual(len(bundle["payload"]["corroborated_claims"]), 1)
        self.assertIs(bundle["payload"]["model_consumed_news"], False)

    def test_arrival_order_does_not_change_digest(self):
        self.assertEqual(seal_news_context([self.a, self.b], **self.kw)["sha256"],
                         seal_news_context([self.b, self.a], **self.kw)["sha256"])

    def test_tampered_claim_rejected(self):
        bundle = seal_news_context([self.a], **self.kw)
        changed = deepcopy(bundle)
        changed["payload"]["items"][0]["claim"] = "unlimited minutes"
        with self.assertRaises(ValueError):
            validate_news_context(changed, **self.kw)

    def test_wrong_fixture_rejected(self):
        bundle = seal_news_context([self.a], **self.kw)
        with self.assertRaises(ValueError):
            validate_news_context(bundle, **(self.kw | {"fixture_id": "other"}))

    def test_future_news_excluded(self):
        future = replace(self.a, published_at_utc=10001, retrieved_at_utc=10002)
        bundle = seal_news_context([future], **self.kw)
        self.assertEqual(bundle["payload"]["items"], [])
        self.assertEqual(bundle["payload"]["status"], "NO_VERIFIED_NEWS")

    def test_replay_rejects_laundered_future_news(self):
        future = replace(self.a, published_at_utc=10001, retrieved_at_utc=10002)
        bundle = seal_news_context([future], **(self.kw | {"prediction_utc": 11000}))
        # Even a valid newer snapshot cannot be replayed against earlier prediction.
        with self.assertRaises(ValueError):
            validate_news_context(bundle, **self.kw)


if __name__ == "__main__":
    unittest.main()

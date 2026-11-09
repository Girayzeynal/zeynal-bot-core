"""News provenance, temporal leakage and editorial separation regressions."""
from dataclasses import replace
import unittest

from basketball_news_intelligence import NewsItem, assess_news


class NewsIntelligenceTests(unittest.TestCase):
    def setUp(self):
        self.item = NewsItem(
            source_id="team-press", source_group="team-official",
            url="https://example.org/team/press", league="NBA",
            fixture_id="401999001", subject_type="PLAYER", subject_id="p1",
            category="MINUTES", claim="limited minutes",
            published_at_utc=9000, retrieved_at_utc=9100,
            evidence_type="OFFICIAL", authenticated=True)
        self.kw = dict(league="NBA", fixture_id="401999001",
                       prediction_utc=10000, max_age_seconds=2000)

    def assess(self, items):
        return assess_news(items, **self.kw)

    def test_official_item_is_accepted_but_not_fake_consensus(self):
        result = self.assess([self.item])
        self.assertEqual(result.status, "EVIDENCE_AVAILABLE")
        self.assertFalse(result.corroborated_claims)

    def test_editorial_cannot_be_promoted_to_corroborated_fact(self):
        a = replace(self.item, evidence_type="EDITORIAL", source_group="editor-a")
        b = replace(a, source_group="editor-b", source_id="editor-b")
        self.assertFalse(self.assess([a, b]).corroborated_claims)

    def test_two_independent_reports_can_corroborate(self):
        a = replace(self.item, evidence_type="REPORTING", source_group="reporter-a")
        b = replace(a, source_group="reporter-b", source_id="reporter-b")
        self.assertEqual(len(self.assess([a, b]).corroborated_claims), 1)

    def test_mirrored_reporting_is_not_independent(self):
        a = replace(self.item, evidence_type="REPORTING")
        b = replace(a, source_id="mirror")
        self.assertFalse(self.assess([a, b]).corroborated_claims)

    def test_future_publication_is_excluded(self):
        self.assertEqual(self.assess([replace(self.item, published_at_utc=10001,
                                             retrieved_at_utc=10002)]).status,
                         "NO_VERIFIED_NEWS")

    def test_future_retrieval_is_excluded(self):
        self.assertEqual(self.assess([replace(self.item, retrieved_at_utc=10001)]).status,
                         "NO_VERIFIED_NEWS")

    def test_wrong_fixture_is_excluded(self):
        self.assertEqual(self.assess([replace(self.item, fixture_id="other")]).status,
                         "NO_VERIFIED_NEWS")

    def test_unauthenticated_source_is_excluded(self):
        self.assertEqual(self.assess([replace(self.item, authenticated=False)]).status,
                         "NO_VERIFIED_NEWS")

    def test_stale_item_is_excluded(self):
        self.assertEqual(self.assess([replace(self.item, published_at_utc=7000)]).status,
                         "NO_VERIFIED_NEWS")

    def test_http_url_is_excluded(self):
        self.assertEqual(self.assess([replace(self.item, url="http://example.org")]).status,
                         "NO_VERIFIED_NEWS")


if __name__ == "__main__":
    unittest.main()

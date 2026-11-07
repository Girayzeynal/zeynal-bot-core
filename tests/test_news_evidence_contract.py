"""Regression tests for pretipoff official news and editorial evidence."""
import unittest
from dataclasses import replace
from news_evidence_contract import NewsEvidence, summarize_news

T = 1800000000


def item(**changes):
    fields = dict(fixture_id="fixture-1", team_id="team-1",
                  kind="official_status", source_class="league",
                  source_name="League injury report",
                  url="https://official.nba.com/example", headline="Availability",
                  published_at_utc=T-300, observed_at_utc=T-200,
                  captured_at_utc=T-100, assertion="Listed questionable",
                  player_id="player-1", availability="questionable")
    fields.update(changes)
    return NewsEvidence(**fields)


class NewsEvidenceTests(unittest.TestCase):
    def test_official_status_kept_separate(self):
        summary = summarize_news([item()], fixture_id="fixture-1", prediction_at_utc=T)
        self.assertEqual(summary["official_statuses"][0]["status"], "questionable")
        self.assertFalse(summary["automatic_projection_adjustment"])

    def test_editorial_opinion_is_not_official_status(self):
        opinion = item(kind="editorial_opinion", source_class="analyst",
                       player_id="", availability="unknown")
        summary = summarize_news([opinion], fixture_id="fixture-1", prediction_at_utc=T)
        self.assertEqual(summary["official_statuses"], [])
        self.assertEqual(len(summary["editorial_hypotheses"]), 1)

    def test_editorial_cannot_assign_player_status(self):
        with self.assertRaises(ValueError):
            summarize_news([item(kind="editorial_opinion", source_class="analyst")],
                           fixture_id="fixture-1", prediction_at_utc=T)

    def test_late_published_news_rejected(self):
        with self.assertRaises(ValueError):
            summarize_news([item(published_at_utc=T+1, observed_at_utc=T+2,
                                 captured_at_utc=T+3)],
                           fixture_id="fixture-1", prediction_at_utc=T)

    def test_cross_fixture_rejected(self):
        with self.assertRaises(ValueError):
            summarize_news([item()], fixture_id="fixture-2", prediction_at_utc=T)

    def test_duplicate_evidence_does_not_multiply(self):
        summary = summarize_news([item(), item()], fixture_id="fixture-1", prediction_at_utc=T)
        self.assertEqual(summary["news_observations"], 1)
        self.assertFalse(summary["independently_confirmed"])

    def test_non_https_rejected(self):
        with self.assertRaises(ValueError):
            summarize_news([item(url="http://example.com")],
                           fixture_id="fixture-1", prediction_at_utc=T)


if __name__ == "__main__":
    unittest.main()

"""Read-only observed market evidence tests for the isolated NBA hybrid service."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hybrid_engine.market_evidence_report import observed_market_evidence


class ObservedMarketEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.assets = Path(self.tmp.name)

    def test_missing_quotes_remain_empty(self):
        self.assertEqual(observed_market_evidence(self.assets, {}, 'fixture', 100, 200), [])

    def test_latest_quote_per_bookmaker_market_wins_without_lookahead(self):
        receipt = {'source_url': 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=20261114'}
        (self.assets / 'source.json').write_text(json.dumps(receipt))
        def quote(book, market, line, observed, ingested):
            return {'sha256': f'{book}-{market}-{observed}', 'payload': {
                'fixture_id': 'fixture', 'fixture_start_utc': 200,
                'ingested_at_utc': ingested, 'observed_at_utc': observed,
                'bookmaker_id': book, 'bookmaker': book,
                'market': market, 'line': line, 'settlement_scope': 'UNKNOWN'}}
        quotes = [
            quote('DraftKings', 'TOTAL', 230.5, 70, 75),
            quote('DraftKings', 'TOTAL', 234.5, 85, 90),
            quote('DraftKings', 'TOTAL', 240.5, 95, 110),
            quote('DraftKings', 'HOME_HANDICAP', 12.5, 85, 90),
            quote('Other', 'TOTAL', 231.5, 80, 85)]
        with patch('hybrid_engine.market_evidence_report.observe_espn',
                   return_value={'quotes': quotes, 'rejected': []}):
            rows = observed_market_evidence(self.assets, {'r': {'file': 'source.json'}},
                                            'fixture', 100, 200)
        self.assertEqual(len(rows), 3)
        self.assertEqual({(q['bookmaker'], q['market'], q['line']) for q in rows}, {
            ('DraftKings', 'TOTAL', 234.5),
            ('DraftKings', 'HOME_HANDICAP', 12.5),
            ('Other', 'TOTAL', 231.5)})

    def test_only_matching_pretipoff_quotes_are_reported(self):
        receipt = {'source_url': 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=20261114'}
        (self.assets / 'source.json').write_text(json.dumps(receipt))
        sources = {'source': {'file': 'source.json'}}
        def quote(fixture, ingested):
            return {'sha256': 'pin', 'payload': {
                'fixture_id': fixture, 'fixture_start_utc': 200,
                'ingested_at_utc': ingested, 'observed_at_utc': 80,
                'bookmaker_id': 'book', 'bookmaker': 'Example',
                'market': 'TOTAL', 'line': 230.5, 'settlement_scope': 'UNKNOWN'}}
        with patch('hybrid_engine.market_evidence_report.observe_espn', return_value={
            'quotes': [quote('fixture', 90), quote('other', 90), quote('fixture', 110)],
            'rejected': []}):
            rows = observed_market_evidence(self.assets, sources, 'fixture', 100, 200)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['status'], 'OBSERVED_NOT_COMPARABLE')
        self.assertNotIn('confidence_index', rows[0])
        self.assertNotIn('recommended_direction', rows[0])


if __name__ == '__main__':
    unittest.main()

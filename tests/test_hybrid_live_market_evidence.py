"""Read-only observed market evidence tests for the isolated NBA hybrid service."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from hybrid_engine.live_nba import LiveNBAHybridService


class ObservedMarketEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.assets = Path(self.tmp.name)
        self.service = object.__new__(LiveNBAHybridService)
        self.service.assets = self.assets

    def test_missing_quotes_remain_empty(self):
        self.service.sources = {}
        self.assertEqual(self.service._observed_market_evidence('fixture', 100, 200), [])

    def test_only_matching_pretipoff_quotes_are_reported(self):
        receipt = {'source_url': 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=20261114'}
        (self.assets / 'source.json').write_text(json.dumps(receipt))
        self.service.sources = {'source': {'file': 'source.json'}}
        def quote(fixture, ingested):
            return {'sha256': 'pin', 'payload': {
                'fixture_id': fixture, 'fixture_start_utc': 200,
                'ingested_at_utc': ingested, 'observed_at_utc': 80,
                'bookmaker_id': 'book', 'bookmaker': 'Example',
                'market': 'TOTAL', 'line': 230.5, 'settlement_scope': 'UNKNOWN'}}
        with patch('hybrid_engine.observed_markets.observe_espn', return_value={
            'quotes': [quote('fixture', 90), quote('other', 90), quote('fixture', 110)],
            'rejected': []}):
            rows = self.service._observed_market_evidence('fixture', 100, 200)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['status'], 'OBSERVED_NOT_COMPARABLE')
        self.assertNotIn('confidence_index', rows[0])
        self.assertNotIn('recommended_direction', rows[0])


if __name__ == '__main__':
    unittest.main()

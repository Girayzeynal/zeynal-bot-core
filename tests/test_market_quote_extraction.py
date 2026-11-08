import unittest
from faz17_engine.faz17_engine import _verified_total_quotes


class MarketQuoteExtractionTests(unittest.TestCase):
    def test_complete_same_line_decimal_prices(self):
        event = {'bookmakers': [{'key': 'book1', 'last_update': '2026-11-09T00:00:00Z',
            'markets': [{'key': 'totals', 'outcomes': [
                {'name': 'Over', 'point': 225.5, 'price': 1.91},
                {'name': 'Under', 'point': 225.5, 'price': 1.91}]}]}]}
        quotes = _verified_total_quotes(event, 1794183000)
        self.assertEqual(len(quotes), 1)
        self.assertEqual(quotes[0]['line'], 225.5)
        self.assertEqual(quotes[0]['source'], 'the-odds-api')

    def test_reject_mismatched_lines_and_missing_timestamp(self):
        event = {'bookmakers': [{'key': 'book1', 'last_update': '2026-11-09T00:00:00Z',
            'markets': [{'key': 'totals', 'outcomes': [
                {'name': 'Over', 'point': 225.5, 'price': 1.91},
                {'name': 'Under', 'point': 224.5, 'price': 1.91}]}]}]}
        self.assertEqual(_verified_total_quotes(event, 1794183000), [])
        event['bookmakers'][0].pop('last_update')
        self.assertEqual(_verified_total_quotes(event, 1794183000), [])


if __name__ == '__main__':
    unittest.main()

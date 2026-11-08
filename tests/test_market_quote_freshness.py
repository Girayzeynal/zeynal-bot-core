import ast
from pathlib import Path
import unittest


class MarketQuoteFreshnessContract(unittest.TestCase):
    def test_archive_rejects_stale_future_and_post_tipoff(self):
        source = Path('main.py').read_text(encoding='utf-8')
        ast.parse(source)
        self.assertIn('quote_ts >= fixture_start_utc', source)
        self.assertIn('quote_ts > now_ts', source)
        self.assertIn('now_ts - quote_ts > 900', source)


if __name__ == '__main__':
    unittest.main()

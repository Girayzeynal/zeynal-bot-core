import ast
import pathlib
import unittest


class MarketPrematchCutoffContract(unittest.TestCase):
    def test_prematch_archive_rejects_post_tipoff_quotes(self):
        source = pathlib.Path('main.py').read_text(encoding='utf-8')
        ast.parse(source)
        self.assertIn('quote_ts >= fixture_start_utc', source)
        self.assertIn('Market quote rejected: post-tipoff', source)
        self.assertIn('MarketSnapshot(**quote)', source)


if __name__ == '__main__':
    unittest.main()

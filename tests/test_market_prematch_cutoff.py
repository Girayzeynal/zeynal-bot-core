import ast
import pathlib
import unittest


class MarketPrematchCutoffContract(unittest.TestCase):
    def test_prematch_archive_rejects_post_tipoff_quotes(self):
        source = pathlib.Path('main.py').read_text(encoding='utf-8')
        ast.parse(source)
        self.assertIn('quote.get("observed_utc", 0) >= fixture_start_utc', source)
        self.assertIn('Post-tipoff market quote rejected', source)
        self.assertIn('MarketSnapshot(**quote)', source)


if __name__ == '__main__':
    unittest.main()

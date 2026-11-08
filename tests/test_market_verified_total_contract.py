import ast
import pathlib
import unittest


class MarketVerifiedLineContract(unittest.TestCase):
    def test_displayed_total_uses_verified_bookmaker_quote(self):
        source = pathlib.Path('faz17_engine/faz17_engine.py').read_text(encoding='utf-8')
        ast.parse(source)
        self.assertIn('verified_quotes = _verified_total_quotes(best_event, int(time.time()))', source)
        self.assertIn('total_line = verified_quotes[0]["line"] if verified_quotes else None', source)
        self.assertIn('"quotes": verified_quotes', source)


if __name__ == '__main__':
    unittest.main()

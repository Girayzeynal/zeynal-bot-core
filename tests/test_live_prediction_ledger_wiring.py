import ast
from pathlib import Path
import unittest


class LivePredictionLedgerWiringTests(unittest.TestCase):
    def test_analyze_handler_records_only_pre_tipoff_and_regulation_scope(self):
        source = Path("main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        funcs = [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)
                 and any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                         and c.func.attr == "run_prematch" for c in ast.walk(n))]
        self.assertTrue(funcs, "Prematch handler not found")
        body = ast.get_source_segment(source, funcs[0])
        self.assertIn('PREDICTION_LEDGER_DB', body)
        self.assertIn('prediction_ts >= fixture_start_utc', body)
        self.assertIn('scope="REGULATION_ONLY"', body)
        self.assertIn('record_prediction(', body)
        self.assertIn('record_fixture_start(', body)


if __name__ == "__main__":
    unittest.main()

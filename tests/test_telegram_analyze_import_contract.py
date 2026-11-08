"""Regression guard: Telegram analyze output type must be imported at runtime."""
import ast
from pathlib import Path
import unittest


class AnalyzeImportContractTests(unittest.TestCase):
    def test_faz13_output_type_is_imported(self):
        source = Path(__file__).resolve().parents[1] / "main.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        imports = {
            alias.asname or alias.name
            for node in tree.body
            if isinstance(node, ast.ImportFrom) and node.module == "faz13_engine"
            for alias in node.names
        }
        self.assertIn("Faz13CoreOutput", imports)


if __name__ == "__main__":
    unittest.main()

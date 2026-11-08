"""Telegram report regression contract."""
import ast
from pathlib import Path
import unittest


class TestTelegramReport(unittest.TestCase):
    def test_team_totals_and_market_disclosure(self):
        source = (Path(__file__).resolve().parents[1] / "faz13_engine" / "faz13_engine.py").read_text(encoding="utf-8")
        ast.parse(source)
        for phrase in ("Takım toplamları (ilk yarı)", "Takım toplamları (48 dk)", "Doğrulanmış piyasa baremi/oranı", "BELİRLENEMEDİ / NO EDGE", "kalibre edilmedi"):
            self.assertIn(phrase, source)


if __name__ == "__main__":
    unittest.main()

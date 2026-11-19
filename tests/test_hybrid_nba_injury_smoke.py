"""Offline smoke report must never imply verified roster or Telegram delivery."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from hybrid_engine.nba_injury_smoke import inspect_pdf

class InjurySmokeTests(unittest.TestCase):
    def test_pdf_smoke_reports_only_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'report.pdf'
            file.write_bytes(b'%PDF-1.7\nmock')
            with patch('hybrid_engine.nba_injury_smoke.extract_nba_injury_rows',
                       return_value=dict(status='PARSED_TABLE_ROWS_REQUIRE_ID_VERIFICATION',
                                         rows=[{'player_name':'Example'}],rejected_count=0)):
                result=inspect_pdf(file)
            self.assertEqual(result['parsed_rows'],1)
            self.assertFalse(result['extraction_verified'])
            self.assertFalse(result['roster_verified'])
            self.assertFalse(result['telegram_delivery_verified'])
    def test_reason_counts_separate_medical_and_assignments(self):
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'report.pdf'
            file.write_bytes(b'%PDF-1.7\nmock')
            rows=[
                {'matchup':'DEN@NOP','status':'Out','reason':'GLeague-OnAssignment'},
                {'matchup':'DEN@NOP','status':'Out','reason':'Injury/Illness-LeftKneeSprain'},
                {'matchup':'DEN@NOP','status':'Questionable','reason':'Injury/Illness-Illness'},
            ]
            with patch('hybrid_engine.nba_injury_smoke.extract_nba_injury_rows',
                       return_value=dict(status='PARSED_TABLE_ROWS_REQUIRE_ID_VERIFICATION',
                                         rows=rows,rejected_count=0)):
                result=inspect_pdf(file)
            self.assertEqual(result['by_reason'],{
                'G_LEAGUE_OR_ASSIGNMENT':1,'INJURY_OR_ILLNESS':2})
            self.assertEqual(result['by_status'],{'Out':2,'Questionable':1})
            self.assertFalse(result['roster_verified'])
            self.assertFalse(result['telegram_delivery_verified'])

    def test_missing_pdf_rejected(self):
        with self.assertRaises(ValueError):
            inspect_pdf('/not-a-real-report.pdf')

if __name__=='__main__':
    unittest.main()

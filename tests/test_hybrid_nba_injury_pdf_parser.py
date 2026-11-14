"""Digest and parsing gates for official injury PDF extraction."""
import hashlib
import sys
import types
import unittest
from unittest.mock import patch
from hybrid_engine.nba_injury_pdf_parser import extract_nba_injury_rows,HEADERS

class FakePage:
    def extract_tables(self):
        return [[list(HEADERS),
                 ['11/14/2026','07:00 (ET)','AWY@HOM','Home Team',
                  'Example, Player','Questionable','Injury/Illness - Ankle'],
                 ['11/14/2026','07:00 (ET)','AWY@HOM','Home Team',
                  '—','—','NOT YET SUBMITTED']]]

class FakePDF:
    pages=[FakePage()]
    def __enter__(self):return self
    def __exit__(self,*args):pass

class InjuryPDFParserTests(unittest.TestCase):
    def setUp(self):
        self.data=b'%PDF-1.7\nfixture'
        self.digest=hashlib.sha256(self.data).hexdigest()

    def test_digest_mismatch_refused_before_parsing(self):
        with self.assertRaises(ValueError):
            extract_nba_injury_rows(self.data,expected_sha256='0'*64)

    def test_table_rows_are_not_automatically_verified(self):
        fake=types.SimpleNamespace(open=lambda stream:FakePDF())
        with patch.dict(sys.modules,{'pdfplumber':fake}):
            result=extract_nba_injury_rows(self.data,expected_sha256=self.digest)
        self.assertEqual(len(result['rows']),1)
        self.assertEqual(result['rejected_count'],1)
        self.assertFalse(result['extraction_verified'])
        self.assertEqual(result['rows'][0]['status'],'Questionable')

if __name__=='__main__':
    unittest.main()

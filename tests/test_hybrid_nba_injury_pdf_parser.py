"""Digest and parsing gates for official injury PDF extraction."""
import hashlib
import sys
import types
import unittest
from unittest.mock import patch
from hybrid_engine.nba_injury_pdf_parser import extract_nba_injury_rows,HEADERS,OFFICIAL_HEADERS

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

    def test_unknown_table_schema_is_rejected(self):
        class UnknownPage:
            def extract_tables(self):return [[['unrelated','columns'],['x','y']]]
        class UnknownPDF:
            pages=[UnknownPage()]
            def __enter__(self):return self
            def __exit__(self,*args):pass
        fake=types.SimpleNamespace(open=lambda stream:UnknownPDF())
        with patch.dict(sys.modules,{'pdfplumber':fake}):
            with self.assertRaisesRegex(ValueError,'OFFICIAL_REPORT_TABLE_SCHEMA_UNRECOGNIZED'):
                extract_nba_injury_rows(self.data,expected_sha256=self.digest)

    def test_oversized_pdf_rejected_before_parser(self):
        oversized=b'%PDF-1.7'+b'x'*(8*1024*1024)
        with self.assertRaisesRegex(ValueError,'OVERSIZED_PDF_BYTES'):
            extract_nba_injury_rows(oversized,
                expected_sha256=hashlib.sha256(oversized).hexdigest())

    def test_continued_page_table_inherits_prior_game_context(self):
        class FirstPage:
            def extract_tables(self):
                return [[list(HEADERS),
                         ['11/14/2026','07:00 (ET)','AWY@HOM','Home Team',
                          'Example, First','Out','Injury/Illness - Ankle']]]
        class ContinuedPage:
            def extract_tables(self):
                return [[[None,None,None,None,'Example, Second','Questionable',
                          'Injury/Illness - Knee']]]
        class TwoPagePDF:
            pages=[FirstPage(),ContinuedPage()]
            def __enter__(self):return self
            def __exit__(self,*args):pass
        fake=types.SimpleNamespace(open=lambda stream:TwoPagePDF())
        with patch.dict(sys.modules,{'pdfplumber':fake}):
            result=extract_nba_injury_rows(self.data,expected_sha256=self.digest)
        self.assertEqual(len(result['rows']),2)
        self.assertEqual(result['rows'][1]['matchup'],'AWY@HOM')
        self.assertFalse(result['extraction_verified'])

    def test_official_nba_headers_and_sparse_rows(self):
        class OfficialPage:
            def extract_tables(self):
                return [[list(OFFICIAL_HEADERS),
                         ['11/14/2026','08:00 (ET)','DEN@NOP','Denver Nuggets',
                          'Example, First','Out','Injury/Illness - Knee'],
                         [None,None,None,None,'Example, Second','Questionable',
                          'Injury/Illness - Ankle'],
                         [None,None,None,'New Orleans Pelicans','—','—',
                          'NOT YET SUBMITTED']]]
        class OfficialPDF:
            pages=[OfficialPage()]
            def __enter__(self):return self
            def __exit__(self,*args):pass
        fake=types.SimpleNamespace(open=lambda stream:OfficialPDF())
        with patch.dict(sys.modules,{'pdfplumber':fake}):
            result=extract_nba_injury_rows(self.data,expected_sha256=self.digest)
        self.assertEqual(len(result['rows']),2)
        self.assertEqual(result['rows'][1]['team'],'Denver Nuggets')
        self.assertEqual(result['rows'][1]['matchup'],'DEN@NOP')
        self.assertEqual(result['rejected_count'],1)
        self.assertFalse(result['extraction_verified'])


    def test_coordinate_fallback_real_nba_sparse_body(self):
        anchors=[23.1,119.6,200.0,264.2,425.0,585.7,666.1]
        def line(y,values):
            return [dict(text=value,x0=x,top=y) for x,value in zip(anchors,values) if value]
        words=[]
        words+=line(107.7,['GameDate','GameTime','Matchup','Team','PlayerName','CurrentStatus','Reason'])
        words+=line(128.9,['11/14/2026','07:00(ET)','DEN@NOP','DenverNuggets','HolmesII,DaRon','Out','GLeague-OnAssignment'])
        words+=line(151.0,['','','','','Nembhard,Ryan','Out','GLeague-Two-Way'])
        words+=line(173.0,['','','','','Strawther,Julian','Out','LeftKneeSprain'])
        words+=line(218.1,['','','','NewOrleansPelicans','','','NOTYETSUBMITTED'])
        class CoordinatePage:
            def extract_tables(self):
                return [[list(HEADERS)]]
            def extract_words(self):
                return words
        class CoordinatePDF:
            pages=[CoordinatePage()]
            def __enter__(self):return self
            def __exit__(self,*args):pass
        fake=types.SimpleNamespace(open=lambda stream:CoordinatePDF())
        with patch.dict(sys.modules,{'pdfplumber':fake}):
            result=extract_nba_injury_rows(self.data,expected_sha256=self.digest)
        self.assertEqual(len(result['rows']),3)
        self.assertTrue(all(r['team']=='DenverNuggets' for r in result['rows']))
        self.assertFalse(result['extraction_verified'])

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

"""Network-free contract tests for bounded NBA PDF capture."""
import io
import unittest
from datetime import datetime,timezone
from hybrid_engine.nba_injury_capture import capture_official_injury_pdf

class Response:
    def __init__(self,url,body,headers=None):
        self.url=url;self.stream=io.BytesIO(body);self.headers=headers or {}
    def __enter__(self):return self
    def __exit__(self,*args):self.stream.close()
    def geturl(self):return self.url
    def read(self,size):return self.stream.read(size)

class NBAInjuryCaptureTests(unittest.TestCase):
    def setUp(self):
        self.url='https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-11-14_02_00PM.pdf'
        self.retrieved=int(datetime(2026,11,14,20,0,tzinfo=timezone.utc).timestamp())
    def capture(self,body=b'%PDF-1.7\nmock',url=None,headers=None):
        return capture_official_injury_pdf(self.url,retrieved_at_utc=self.retrieved,
            prediction_utc=self.retrieved+1,
            opener=lambda request,timeout:Response(url or self.url,body,headers))
    def test_receipt_is_not_verified_player_extraction(self):
        receipt=self.capture()
        self.assertTrue(receipt['download_verified'])
        self.assertFalse(receipt['extraction_verified'])
        self.assertEqual(receipt['player_status_records'],[])
        self.assertEqual(len(receipt['sha256']),64)
    def test_non_pdf_and_redirect_rejected(self):
        with self.assertRaises(ValueError):self.capture(body=b'<html>not pdf</html>')
        with self.assertRaises(ValueError):self.capture(url='https://example.org/other.pdf')
    def test_oversized_declared_length_rejected(self):
        with self.assertRaises(ValueError):
            self.capture(headers={'Content-Length':str(9*1024*1024)})

if __name__=='__main__':
    unittest.main()

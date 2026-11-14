"""Official NBA injury report reference safety tests."""
import unittest
from datetime import datetime,timezone
from hybrid_engine.nba_injury_source import official_nba_injury_report_reference

class NBAInjurySourceTests(unittest.TestCase):
    def setUp(self):
        self.url='https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-11-14_02_00PM.pdf'
        self.retrieved=int(datetime(2026,11,14,20,0,tzinfo=timezone.utc).timestamp())
        self.prediction=self.retrieved+60

    def check(self,url=None,retrieved=None,prediction=None):
        return official_nba_injury_report_reference(
            self.url if url is None else url,
            retrieved_at_utc=self.retrieved if retrieved is None else retrieved,
            prediction_utc=self.prediction if prediction is None else prediction)

    def test_official_reference_is_not_misrepresented_as_parsed(self):
        result=self.check()
        self.assertEqual(result['status'],'OFFICIAL_URL_AND_CLOCK_VERIFIED_CONTENT_NOT_PARSED')
        self.assertEqual(result['player_status_records'],[])
        self.assertFalse(result['roster_verified'])

    def test_wrong_host_or_path_rejected(self):
        for url in ('https://fake.nba.com/referee/injury/Injury-Report_2026-11-14_02_00PM.pdf',
                    'http://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-11-14_02_00PM.pdf',
                    self.url+'?version=latest'):
            with self.subTest(url=url),self.assertRaises(ValueError):
                self.check(url=url)

    def test_future_report_and_late_retrieval_rejected(self):
        with self.assertRaises(ValueError):
            self.check(retrieved=self.retrieved-3600)
        with self.assertRaises(ValueError):
            self.check(prediction=self.retrieved-1)

if __name__=='__main__':
    unittest.main()

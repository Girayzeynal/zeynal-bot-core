"""Fixture and player ID gate for NBA injury report rows."""
import unittest
from hybrid_engine.nba_injury_rows import map_official_injury_rows

class InjuryRowTests(unittest.TestCase):
    def setUp(self):
        self.prediction=1794700000
        self.tipoff=self.prediction+3600
        self.reference=dict(status='OFFICIAL_REPORT_CONTENT_VERIFIED',
            extraction_verified=True,report_timestamp_utc=self.prediction-100,
            source_url='https://ak-static.cms.nba.com/referee/injury/report.pdf')
        self.teams={'home':'home-id','away':'away-id','Home Team':'home-id','Away Team':'away-id'}
        self.players={('Home Team','Player A'):'player-a'}
        self.rows=[dict(matchup='AWY@HOM',team='Home Team',player_name='Player A',status='Questionable')]

    def run_rows(self,reference=None,rows=None):
        return map_official_injury_rows(self.rows if rows is None else rows,
            fixture_matchup='AWY@HOM',team_ids=self.teams,player_ids=self.players,
            report_reference=self.reference if reference is None else reference,
            prediction_utc=self.prediction,fixture_start_utc=self.tipoff)

    def test_verified_row_is_partial_status_not_lineup(self):
        result=self.run_rows()
        self.assertEqual(result['records'][0]['status'],'QUESTIONABLE')
        self.assertFalse(result['rotation_verified'])

    def test_unverified_pdf_extraction_never_enters_evidence(self):
        result=self.run_rows(dict(self.reference,extraction_verified=False))
        self.assertEqual(result['records'],[])

    def test_other_fixture_and_unmapped_player_excluded(self):
        rows=self.rows+[dict(matchup='OTHER',team='Home Team',player_name='Player A',status='Out'),
                        dict(matchup='AWY@HOM',team='Home Team',player_name='Unknown',status='Out')]
        self.assertEqual(len(self.run_rows(rows=rows)['records']),1)

if __name__=='__main__':
    unittest.main()

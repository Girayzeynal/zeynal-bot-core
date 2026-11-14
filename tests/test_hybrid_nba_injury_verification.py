"""Fail-closed PDF extraction-to-roster verification tests."""
import unittest
from hybrid_engine.nba_injury_verification import verified_pdf_roster_evidence

class NBAInjuryVerificationTests(unittest.TestCase):
    def setUp(self):
        self.prediction=1794700000
        self.capture=dict(download_verified=True,sha256='a'*64,
                          report_timestamp_utc=self.prediction-100,
                          source_url='https://ak-static.cms.nba.com/referee/injury/report.pdf')
        self.extraction=dict(status='PARSED_TABLE_ROWS_REQUIRE_ID_VERIFICATION',
                             rows=[dict(matchup='AWY@HOM',team='Home Team',
                                        player_name='Player A',status='Out')])
        self.verification=dict(verified=True,sha256='a'*64,
                               fixture_matchup='AWY@HOM',
                               player_id_mapping_verified=True,
                               team_id_mapping_verified=True)
        self.teams={'home':'home-id','away':'away-id','Home Team':'home-id'}
        self.players={('Home Team','Player A'):'player-a'}
    def run_gate(self,verification=None):
        return verified_pdf_roster_evidence(self.extraction,
            capture_receipt=self.capture,
            verification=self.verification if verification is None else verification,
            fixture_matchup='AWY@HOM',team_ids=self.teams,player_ids=self.players,
            prediction_utc=self.prediction,fixture_start_utc=self.prediction+3600)
    def test_verified_status_is_not_a_verified_lineup(self):
        result=self.run_gate()
        self.assertEqual(result['records'][0]['status'],'OUT')
        self.assertFalse(result['rotation_verified'])
        self.assertFalse(result['minutes_adjustment_allowed'])
    def test_digest_mismatch_refused(self):
        with self.assertRaises(ValueError):
            self.run_gate(dict(self.verification,sha256='b'*64))
    def test_unverified_player_mapping_refused(self):
        with self.assertRaises(ValueError):
            self.run_gate(dict(self.verification,player_id_mapping_verified=False))
    def test_wrong_fixture_refused(self):
        with self.assertRaises(ValueError):
            self.run_gate(dict(self.verification,fixture_matchup='OTHER'))

if __name__=='__main__':
    unittest.main()

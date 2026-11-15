"""Fail-closed PDF extraction-to-roster verification tests."""
import unittest
from datetime import datetime,timezone
from core.team_identity import digest
from hybrid_engine.nba_injury_verification import verified_pdf_roster_evidence

class NBAInjuryVerificationTests(unittest.TestCase):
    def setUp(self):
        self.prediction=int(datetime(2026,11,14,20,tzinfo=timezone.utc).timestamp())
        self.capture=dict(download_verified=True,sha256='a'*64,
                          report_timestamp_utc=self.prediction-3600,retrieved_at_utc=self.prediction-10,download_completed_at_utc=self.prediction-5,
                          source_url='https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-11-14_02_00PM.pdf')
        self.extraction=dict(status='PARSED_TABLE_ROWS_REQUIRE_ID_VERIFICATION',
                             rows=[dict(matchup='AWY@HOM',team='Home Team',
                                        player_name='Player A',status='Out')])
        self.extraction.update(source_pdf_sha256='a'*64,rows_sha256=digest(self.extraction['rows']))
        self.verification=dict(verified_at_utc=self.prediction,rows_sha256=digest(self.extraction['rows']),verified=True,sha256='a'*64,
                               fixture_matchup='AWY@HOM',
                               player_id_mapping_verified=True,
                               team_id_mapping_verified=True)
        self.teams={'home':'home-id','away':'away-id','Home Team':'home-id'}
        self.players={('Home Team','Player A'):'player-a'}
    def run_gate(self,verification=None):
        self.extraction['rows_sha256']=digest(self.extraction['rows'])
        self.verification['rows_sha256']=self.extraction['rows_sha256']
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
    def test_missing_player_id_refused_even_with_verified_flag(self):
        original=self.players
        try:
            self.players={}
            with self.assertRaisesRegex(ValueError,'INCOMPLETE_OR_DUPLICATE_PLAYER_ID_MAPPING'):
                self.run_gate()
        finally:
            self.players=original
    def test_duplicate_player_ids_refused_even_with_verified_flag(self):
        self.extraction['rows'].append(dict(matchup='AWY@HOM',team='Home Team',
                                            player_name='Player B',status='Out'))
        self.players[('Home Team','Player B')]='player-a'
        with self.assertRaisesRegex(ValueError,'INCOMPLETE_OR_DUPLICATE_PLAYER_ID_MAPPING'):
            self.run_gate()
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

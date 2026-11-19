"""Isolated Telegram roster evidence bridge tests."""
import unittest
from hybrid_engine.telegram_roster_bridge import read_fixture_roster_evidence

class TelegramRosterBridgeTests(unittest.TestCase):
    def setUp(self):
        self.kw=dict(fixture_id='game-1',prediction_utc=1794700000,
                     fixture_start_utc=1794703600,home_team_id='home',away_team_id='away')
        self.packet=dict(verified=True,fixture_id='game-1',
                         prediction_utc=1794700000,fixture_start_utc=1794703600,
                         home_team_id='home',away_team_id='away',
                         records=[dict(team_id='home',player_id='p1',status='OUT',
                             published_at_utc=1794699900,source_url='https://example.org/report')])
    def test_verified_fixture_packet_is_displayable(self):
        result=read_fixture_roster_evidence({'game-1':self.packet},**self.kw)
        self.assertEqual(len(result['records']),1)
        self.assertFalse(result['minutes_adjustment_allowed'])
    def test_wrong_fixture_and_unverified_packet_are_empty(self):
        for packet in (dict(self.packet,verified=False),
                       dict(self.packet,fixture_id='game-2'),
                       dict(self.packet,prediction_utc=1794700001)):
            with self.subTest(packet=packet):
                result=read_fixture_roster_evidence({'game-1':packet},**self.kw)
                self.assertEqual(result['records'],[])
    def test_absent_packet_is_empty(self):
        self.assertEqual(read_fixture_roster_evidence({},**self.kw)['records'],[])

if __name__=='__main__':
    unittest.main()

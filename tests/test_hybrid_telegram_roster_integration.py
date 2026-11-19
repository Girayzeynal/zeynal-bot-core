"""Premium roster button displays fixture-gated evidence, not invented lineup."""
import unittest
from hybrid_engine.telegram_premium_ui import roster_section,detail_sections
from hybrid_engine.telegram_roster_bridge import read_fixture_roster_evidence

class PremiumRosterIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.prediction=1794700000
        self.fixture=1794703600
        self.kw=dict(fixture_id='nba-test-fixture',prediction_utc=self.prediction,
                     fixture_start_utc=self.fixture,home_team_id='home',away_team_id='away')
        self.packet=dict(verified=True,fixture_id='nba-test-fixture',
                         prediction_utc=self.prediction,fixture_start_utc=self.fixture,
                         home_team_id='home',away_team_id='away',
                         records=[dict(team_id='home',player_id='player-1',
                                       status='QUESTIONABLE',
                                       published_at_utc=self.prediction-60,
                                       source_url='https://example.org/official-report')])

    def test_fixture_bound_evidence_reaches_roster_button(self):
        evidence=read_fixture_roster_evidence({'nba-test-fixture':self.packet},**self.kw)
        sections=detail_sections([], '<b>Piyasa yok</b>',roster_evidence=evidence)
        self.assertIn('player-1',sections['roster'])
        self.assertIn('QUESTIONABLE',sections['roster'])
        self.assertIn('example.org/official-report',sections['roster'])
        self.assertIn('ilk beş',sections['roster'])

    def test_unverified_packet_does_not_leak_into_button(self):
        evidence=read_fixture_roster_evidence(
            {'nba-test-fixture':dict(self.packet,verified=False)},**self.kw)
        section=roster_section(evidence)
        self.assertNotIn('player-1',section)
        self.assertIn('doğrulanabilir oyuncu durum kaydı yok',section)

    def test_other_fixture_cannot_leak_player_status(self):
        evidence=read_fixture_roster_evidence(
            {'other-fixture':self.packet},**self.kw)
        self.assertNotIn('player-1',roster_section(evidence))

if __name__=='__main__':
    unittest.main()

"""Exercise fixture evidence through the actual Telegram roster presentation path."""
import unittest
from hybrid_engine.telegram_roster_bridge import read_fixture_roster_evidence
from hybrid_engine.telegram_premium_ui import roster_section, detail_sections

class RosterTelegramPresentationTests(unittest.TestCase):
    def setUp(self):
        self.kw=dict(fixture_id='fixture-42',prediction_utc=1794700000,
                     fixture_start_utc=1794703600,home_team_id='home',away_team_id='away')
        self.packet=dict(verified=True,fixture_id='fixture-42',
                         prediction_utc=1794700000,fixture_start_utc=1794703600,
                         home_team_id='home',away_team_id='away',
                         records=[dict(team_id='home',player_id='p<&>',status='OUT',
                                       published_at_utc=1794699900,
                                       source_url='https://example.org/injury?x=1&y=2')])
    def test_valid_fixture_packet_reaches_roster_button_html(self):
        evidence=read_fixture_roster_evidence({'fixture-42':self.packet},**self.kw)
        section=detail_sections([], '<b>MARKET</b>',roster_evidence=evidence)['roster']
        self.assertIn('p&lt;&amp;&gt;',section)
        self.assertIn('https://example.org/injury?x=1&amp;y=2',section)
        self.assertIn('OUT',section)
        self.assertIn('modele uygulanmadı',section)
        self.assertNotIn('p<&>',section)
        self.assertFalse(evidence['minutes_adjustment_allowed'])
    def test_mismatched_fixture_never_leaks_roster_into_button(self):
        packet=dict(self.packet,fixture_id='another-fixture')
        evidence=read_fixture_roster_evidence({'fixture-42':packet},**self.kw)
        section=roster_section(evidence)
        self.assertIn('doğrulanabilir oyuncu durum kaydı yok',section)
        self.assertNotIn('p&lt;&amp;&gt;',section)
    def test_post_prediction_publication_is_withheld(self):
        packet=dict(self.packet,records=[dict(self.packet['records'][0],
                                             published_at_utc=self.kw['prediction_utc']+1)])
        evidence=read_fixture_roster_evidence({'fixture-42':packet},**self.kw)
        self.assertEqual(evidence['records'],[])
        self.assertEqual(evidence['rejected_count'],1)

if __name__=='__main__':
    unittest.main()

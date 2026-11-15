"""Regression: a refused fixture exposes bounded evidence, not a forecast."""
import unittest
from universal_analysis import render_preflight

class FixtureDiagnosticPresentationTests(unittest.TestCase):
    def test_diagnostic_visible_without_prediction(self):
        report=dict(stage='FIXTURE',reason='FIXTURE_NOT_UNIQUELY_VERIFIED',
                    provider='ESPN',status='ABSTAIN',participant_count=30,
                    fixture_diagnostic=dict(matched_count=0,same_pair_count=1,
                        reversed_pair_count=0,nearby=[dict(local_date='2026-11-16',
                            home_team_id='home',away_team_id='away',
                            fixture_id='game-1',completed=False)]))
        message=render_preflight(report)
        self.assertIn('tam eşleşme 0',message)
        self.assertIn('2026-11-16 TSİ',message)
        self.assertIn('game-1',message)
        self.assertIn('Tahmin üretilmedi',message)
    def test_absent_diagnostic_keeps_existing_message(self):
        report=dict(stage='FIXTURE',reason='FIXTURE_NOT_UNIQUELY_VERIFIED',
                    provider='ESPN',status='ABSTAIN')
        self.assertNotIn('Yakın maç:',render_preflight(report))

if __name__=='__main__':
    unittest.main()

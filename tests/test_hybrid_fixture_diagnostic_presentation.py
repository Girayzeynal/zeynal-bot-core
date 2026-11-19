"""Regression: pinned fixture preflight remains read-only and preserves rejection."""
import unittest
from universal_analysis import render_preflight

class FixtureDiagnosticPresentationTests(unittest.TestCase):
    def test_refusal_never_claims_prediction(self):
        report=dict(stage='FIXTURE',reason='FIXTURE_NOT_UNIQUELY_VERIFIED',
                    provider='ESPN',status='ABSTAIN',participant_count=30)
        message=render_preflight(report)
        self.assertIn('FIXTURE_NOT_UNIQUELY_VERIFIED',message)
        self.assertIn('Tahmin üretilmedi',message)
        self.assertNotIn('Doğrulanmış başlangıç',message)

if __name__=='__main__':
    unittest.main()

from unittest import TestCase
from hybrid_engine.rotation_direction_evidence import direction
from hybrid_engine.rotation_direction_policy import action

class RotationDirectionEvidenceTests(TestCase):
    def test_point_direction_and_spread(self):
        self.assertEqual(direction(240,215.5,'TOTAL'),'over')
        self.assertEqual(direction(220,215.5,'TOTAL'),'over')
        self.assertEqual(direction(-3,4,'HOME_HANDICAP'),'over')
        self.assertEqual(direction(-4,4,'HOME_HANDICAP'),'none')
        self.assertEqual(direction(210,215.5,'TOTAL'),'under')
    def test_success_protected_and_unverified_held(self):
        self.assertEqual(action('WIN',verified=True),'PROTECT_SUCCESS')
        self.assertEqual(action('LOSS',verified=True),'INVESTIGATE_FAILURE')
        self.assertEqual(action('WIN'),'HOLD_UNVERIFIED')

"""Safety tests: no small-sample calibration and no production mutation."""
import unittest
from unittest.mock import patch

import calibration_safety_gate


class CalibrationSafetyGateTests(unittest.TestCase):
    def test_nonempty_versions_never_authorize_training(self):
        with patch.object(calibration_safety_gate, "audit_calibration_readiness",
                          return_value={"status": "ready", "verified_versions": 200}):
            result = calibration_safety_gate.evaluate("/fake/ledger.sqlite")
        self.assertFalse(result["automatic_model_update_permitted"])
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(set(result["leagues"]), {"NBA", "EuroLeague"})

    def test_missing_ledger_fails_closed(self):
        with patch.object(calibration_safety_gate, "audit_calibration_readiness",
                          return_value={"status": "blocked", "reason": "ledger_not_found"}):
            result = calibration_safety_gate.evaluate("/missing.sqlite")
        self.assertEqual(result["leagues"]["NBA"]["reason"], "ledger_not_found")

    def test_invalid_threshold_rejected(self):
        with self.assertRaises(ValueError):
            calibration_safety_gate.evaluate("/fake.sqlite", minimum_fixtures=1)


if __name__ == "__main__":
    unittest.main()

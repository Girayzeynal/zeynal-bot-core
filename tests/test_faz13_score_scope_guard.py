"""FAZ13 v1 must not be reinterpreted as regulation-only data."""
import unittest

from prediction_inputs import digest, validate_prediction_inputs


def snapshot(scope):
    payload = {
        "schema_version": 1, "league": "NBA", "scope": scope,
        "prediction_ts_utc": 100,
        "context": {"date": "2026-11-06", "home": "HOME", "away": "AWAY"},
        "expected_home": 100.0, "expected_away": 100.0,
        "teams": {"home": {"key": "HOME", "captured_at_utc": 90, "records": []},
                  "away": {"key": "AWAY", "captured_at_utc": 90, "records": []}},
    }
    return {"payload": payload, "sha256": digest(payload)}


class Faz13ScoreScopeGuardTests(unittest.TestCase):
    def test_rehashed_regulation_label_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "only supports FINAL_WITH_OT"):
            validate_prediction_inputs(snapshot("REGULATION_ONLY"), league="NBA",
                prediction_utc=100, expected_home=100.0, expected_away=100.0,
                scope="REGULATION_ONLY")

    def test_regulation_request_on_final_snapshot_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "only supports FINAL_WITH_OT"):
            validate_prediction_inputs(snapshot("FINAL_WITH_OT"), league="NBA",
                prediction_utc=100, expected_home=100.0, expected_away=100.0,
                scope="REGULATION_ONLY")

    def test_unsupported_score_scope_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "only supports FINAL_WITH_OT"):
            validate_prediction_inputs(snapshot("UNKNOWN"), league="NBA",
                prediction_utc=100, expected_home=100.0, expected_away=100.0,
                scope="UNKNOWN")

    def test_original_scope_proceeds_to_existing_row_validation(self):
        # Intentionally incomplete rows: verifies the scope guard does not
        # replace the original historical input validation.
        with self.assertRaisesRegex(ValueError, "Invalid input sample size"):
            validate_prediction_inputs(snapshot("FINAL_WITH_OT"), league="NBA",
                prediction_utc=100, expected_home=100.0, expected_away=100.0)


if __name__ == "__main__":
    unittest.main()

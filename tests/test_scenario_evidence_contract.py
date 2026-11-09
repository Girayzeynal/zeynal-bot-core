"""Regression checks for evidence-gated basketball scenario inputs."""
import unittest
from scenario_evidence_contract import Observation, ScenarioInput

START = 1800001000
PRED = 1800000000


def obs(value, unit="points", observed=PRED-60):
    return Observation(value, "provider:fixture:stat", observed, START, unit)


def fixture(**changes):
    base = dict(league="NBA", fixture_id="test-fixture", prediction_at_utc=PRED,
                fixture_start_utc=START, home="H", away="A",
                home_points_for=obs(110), home_points_against=obs(104),
                away_points_for=obs(107), away_points_against=obs(108))
    base.update(changes)
    return ScenarioInput(**base)


class ScenarioEvidenceContractTests(unittest.TestCase):
    def test_valid_base_projection_is_not_called_calibrated(self):
        result = fixture().validate()
        self.assertEqual(result["base_projection"], {"home": 109, "away": 105.5})
        self.assertFalse(result["scenario_probabilities_calibrated"])
        self.assertFalse(result["pace_available"])

    def test_future_observation_rejected(self):
        with self.assertRaises(ValueError):
            fixture(home_points_for=obs(110, observed=PRED+1)).validate()

    def test_observation_at_tipoff_rejected(self):
        with self.assertRaises(ValueError):
            fixture(home_points_for=obs(110, observed=START)).validate()

    def test_missing_provenance_rejected(self):
        with self.assertRaises(ValueError):
            fixture(home_points_for=Observation(110, "", PRED-1, START, "points")).validate()

    def test_boolean_and_nan_rejected(self):
        for bad in (True, float("nan"), float("inf")):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                fixture(home_points_for=obs(bad)).validate()

    def test_pace_must_have_correct_unit(self):
        with self.assertRaises(ValueError):
            fixture(pace=obs(98, unit="points")).validate()

    def test_pace_evidence_is_explicit(self):
        result = fixture(pace=obs(98, unit="possessions")).validate()
        self.assertTrue(result["pace_available"])
        self.assertFalse(result["scenario_probabilities_calibrated"])

    def test_invalid_fixture_identity_rejected(self):
        with self.assertRaises(ValueError):
            fixture(away="H").validate()


if __name__ == "__main__":
    unittest.main()

import unittest

from core.aggregate_engine import aggregate_baseline


class AggregateBaselineValidationTests(unittest.TestCase):
    def row(self, **overrides):
        value = {
            "pts_for": 112.0,
            "pts_against": 108.0,
            "confidence": 0.8,
            "source": "TEST_PROVIDER",
            "pace": 99.0,
            "n_games": 12,
        }
        value.update(overrides)
        return value

    def test_rejects_nan_and_infinite_scoring_inputs(self):
        cases = (
            ("pts_for", float("nan")),
            ("pts_for", float("inf")),
            ("pts_against", float("-inf")),
            ("confidence", float("nan")),
            ("confidence", float("inf")),
        )
        for field, value in cases:
            with self.subTest(field=field, value=value):
                self.assertIsNone(aggregate_baseline([self.row(**{field: value})]))

    def test_non_finite_pace_is_omitted_not_propagated(self):
        result = aggregate_baseline([self.row(pace=float("nan"))])
        self.assertIsNotNone(result)
        self.assertIsNone(result["pace"])

    def test_valid_row_preserves_pace_and_sample_size(self):
        result = aggregate_baseline([self.row()])
        self.assertEqual(result["pace"], 99.0)
        self.assertEqual(result["n_games"], 12)


if __name__ == "__main__":
    unittest.main()

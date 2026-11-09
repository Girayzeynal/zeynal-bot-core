"""Regression checks for explicit provider field mapping and provenance."""
import unittest

from provider_observation_adapter import normalize_numeric_observation


class ProviderObservationAdapterTests(unittest.TestCase):
    def setUp(self):
        self.kw = dict(
            provider="ESPN", independent_group="espn",
            fixture_id="401999001", provider_event_id="401999001",
            field="home_score", value_path=("event", "home", "score"),
            event_id_path=("event", "id"),
            payload={"event": {"id": "401999001", "home": {"score": 110}}},
            fetched_at_utc=10000, source_url="https://site.api.espn.com/example",
        )

    def normalize(self, **changes):
        return normalize_numeric_observation(**(self.kw | changes))

    def test_valid_response_is_bound_to_digest(self):
        result = self.normalize()
        self.assertEqual(result.observation.value, 110.0)
        self.assertEqual(len(result.payload_sha256), 64)

    def test_digest_changes_with_payload(self):
        changed = {"event": {"id": "401999001", "home": {"score": 111}}}
        self.assertNotEqual(self.normalize().payload_sha256,
                            self.normalize(payload=changed).payload_sha256)

    def test_provider_event_id_mismatch_fails(self):
        with self.assertRaises(ValueError):
            self.normalize(provider_event_id="different")

    def test_missing_field_fails(self):
        with self.assertRaises(ValueError):
            self.normalize(value_path=("event", "away", "score"))

    def test_numeric_string_is_not_silently_converted(self):
        with self.assertRaises(ValueError):
            self.normalize(payload={"event": {"id": "401999001", "home": {"score": "110"}}})

    def test_nonfinite_value_fails(self):
        with self.assertRaises(ValueError):
            self.normalize(payload={"event": {"id": "401999001", "home": {"score": float("nan")}}})

    def test_http_url_fails(self):
        with self.assertRaises(ValueError):
            self.normalize(source_url="http://site.api.espn.com/example")

    def test_url_credentials_fail(self):
        with self.assertRaises(ValueError):
            self.normalize(source_url="https://secret:pass@site.api.espn.com/example")

    def test_missing_timestamp_fails(self):
        with self.assertRaises(ValueError):
            self.normalize(fetched_at_utc=0)


if __name__ == "__main__":
    unittest.main()

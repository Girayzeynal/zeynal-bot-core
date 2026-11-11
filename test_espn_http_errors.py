"""Regression tests for ESPN provider access failures (no network or ledger writes)."""
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import espn_outcome_sync


class ProviderAccessTests(unittest.TestCase):
    def test_403_is_reported_without_writes(self):
        error = HTTPError("https://example.invalid", 403, "Forbidden", {}, None)
        with patch.object(espn_outcome_sync, "eligible_espn_ids", return_value=["401909960"]), \
             patch.object(espn_outcome_sync, "fetch_espn_event", side_effect=error), \
             patch.object(espn_outcome_sync, "import_verified_espn_outcome") as importer:
            result = espn_outcome_sync.run("/unused.sqlite", apply=True)
        self.assertEqual(result["results"], [
            {"event_id": "401909960", "status": "PROVIDER_ACCESS_DENIED", "http_status": 403}
        ])
        importer.assert_not_called()

    def test_other_http_errors_are_distinct(self):
        error = HTTPError("https://example.invalid", 503, "Unavailable", {}, None)
        with patch.object(espn_outcome_sync, "eligible_espn_ids", return_value=["401909960"]), \
             patch.object(espn_outcome_sync, "fetch_espn_event", side_effect=error):
            result = espn_outcome_sync.run("/unused.sqlite")
        self.assertEqual(result["results"][0]["status"], "PROVIDER_HTTP_ERROR")
        self.assertEqual(result["results"][0]["http_status"], 503)


if __name__ == "__main__":
    unittest.main()

import unittest
from datetime import datetime, timezone

from providers.espn_identity_audit import audit_scoreboard_identity


def ts(value):
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())


class ESPNIdentityAuditTests(unittest.TestCase):
    def test_utc_midnight_does_not_create_false_eastern_mismatch(self):
        rows = [{
            "provider_fixture_id": "a", "start_ts_utc": ts("2025-10-26T01:00:00Z"),
            "home_team_id": "1", "away_team_id": "2",
        }]
        result = audit_scoreboard_identity(rows, "20251025")
        self.assertEqual(result["eastern_date_mismatch_fixture_ids"], [])
        self.assertEqual(result["teams_in_multiple_accepted_games"], [])

    def test_date_and_team_reuse_anomalies(self):
        rows = [
            {"provider_fixture_id": "a", "start_ts_utc": ts("2025-10-26T01:00:00Z"),
             "home_team_id": "1", "away_team_id": "2"},
            {"provider_fixture_id": "b", "start_ts_utc": ts("2025-10-27T01:00:00Z"),
             "home_team_id": "1", "away_team_id": "3"},
        ]
        result = audit_scoreboard_identity(rows, "20251025")
        self.assertEqual(result["eastern_date_mismatch_fixture_ids"], ["b"])
        self.assertEqual(result["teams_in_multiple_accepted_games"], ["1"])


if __name__ == "__main__":
    unittest.main()

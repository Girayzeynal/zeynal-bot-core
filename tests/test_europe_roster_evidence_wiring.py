"""European player-evidence wiring, fail-closed under HTTP 429.

These are offline integration contracts, NOT evidence that any real player
report has been captured or applied to the live model.
"""
import tempfile
import unittest

from hybrid_engine.europe_data import EuropeanDataReview


TIME = 1_800_000_000
FIXTURE = TIME + 3600
CTX = {
    "league": "EUROLEAGUE",
    "season": "2026/2027",
    "fixture_id": "E2026_111",
    "fixture_start_utc": FIXTURE,
    "prediction_generated_at_utc": TIME,
    "home": {"provider_id": "ZAL", "official_name": "Zalgiris Kaunas"},
    "away": {"provider_id": "PAN", "official_name": "Panathinaikos AKTOR Athens"},
}


class EuropeanRosterAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.calls = []

    def getter(self, url, league, *, deadline):
        self.calls.append((league, url))
        return dict(status="SOURCE_HTTP_ERROR", http_status=429, url=url,
                    retry_after_seconds=300)

    def reviewer(self, store):
        return EuropeanDataReview({}, None, self.tmp.name, getter=self.getter,
                                  clock=lambda: TIME + 60, roster_store=store)

    @staticmethod
    def packet(records):
        return {
            "verified": True,
            "fixture_id": CTX["fixture_id"],
            "prediction_utc": CTX["prediction_generated_at_utc"],
            "fixture_start_utc": CTX["fixture_start_utc"],
            "home_team_id": "ZAL",
            "away_team_id": "PAN",
            "records": records,
        }

    def test_source_429_does_not_erase_pinned_player_evidence(self):
        record = {
            "team_id": "ZAL", "player_id": "native-player-42",
            "status": "OUT", "published_at_utc": TIME - 100,
            "source_url": "https://example.org/official/injury-report",
        }
        store = {CTX["fixture_id"]: self.packet([record])}
        html, details = self.reviewer(store).roster(CTX)
        self.assertEqual(details["verified_player_packet_status"],
                         "FIXTURE_BOUND_PREFORECAST_PLAYER_STATUS_AVAILABLE")
        self.assertEqual(details["verified_player_records"], [record])
        self.assertIn("native-player-42", html)
        self.assertIn("HTTP 429", html)
        self.assertFalse(details["minutes_and_rotation_model_input"])
        self.assertFalse(details["forecast_changed"])
        self.assertEqual(len(self.calls), 1)

    def test_unbound_or_late_packet_must_not_claim_players(self):
        for packet in (
            self.packet([{"team_id": "ZAL", "player_id": "late",
                          "status": "OUT", "published_at_utc": TIME + 1,
                          "source_url": "https://example.org/official"}]),
            dict(self.packet([{"team_id": "ZAL", "player_id": "one",
                              "status": "OUT", "published_at_utc": TIME - 200,
                              "source_url": "https://example.org/official"}]),
                 fixture_id="OTHER"),
        ):
            with self.subTest(packet=packet):
                self.calls.clear()
                html, details = self.reviewer({CTX["fixture_id"]: packet}).roster(CTX)
                self.assertEqual(details["verified_player_records"], [])
                self.assertEqual(details["verified_player_packet_status"],
                                 "NO_VERIFIED_PREFORECAST_PLAYER_PACKET")
                self.assertNotIn("native-player-42", html)

    def test_empty_source_still_explicitly_reports_no_live_adapter(self):
        html, details = self.reviewer({}).roster(CTX)
        self.assertEqual(details["verified_player_records"], [])
        self.assertIn("canlı sakatlık/veri sağlayıcı adaptörü bağlı değil", html)
        self.assertEqual(details["verified_player_packet_status"],
                         "NO_VERIFIED_PREFORECAST_PLAYER_PACKET")
        self.assertIn("300 sn", html)
        self.assertFalse(details["minutes_and_rotation_model_input"])


if __name__ == "__main__":
    unittest.main()

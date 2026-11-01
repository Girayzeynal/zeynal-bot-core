import unittest

from providers.espn_rejection_diagnostics import rejected_event_reason
from providers.espn_quality_audit import audit_espn_events


class ESPNRejectionDiagnosticsTests(unittest.TestCase):
    def test_reasons_are_aggregated_without_raw_payload(self):
        event = {
            "id": "a", "date": "2025-10-25T23:00:00Z",
            "competitions": [{
                "status": {"type": {"state": "post", "completed": False}},
                "competitors": [],
            }],
        }
        report = audit_espn_events(
            [event, {"id": "b"}, None], observed_at_utc=1761500000
        )
        self.assertEqual(report["rejection_reasons"], {
            "invalid_event_structure": 1,
            "invalid_start_time": 1,
            "not_completed": 1,
        })
        self.assertEqual(sum(report["rejection_reasons"].values()), 3)
        self.assertEqual(report["unfinished_events"], 1)
        self.assertEqual(report["malformed_or_unverifiable_events"], 2)
        self.assertNotIn("competitions", report)

    def test_future_event_is_distinguished(self):
        event = {"id": "a", "date": "2026-11-02T00:00:00Z"}
        self.assertEqual(
            rejected_event_reason(event, 1793564768), "future_or_not_started"
        )


if __name__ == "__main__":
    unittest.main()

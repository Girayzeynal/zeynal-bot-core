"""Trimmed real observations plus explicitly corrupted/synthetic rejection cases."""
from copy import deepcopy
import unittest
from test_euroleague_baseline_binding import observation, values
from euro_history_audit import audit_history
from providers.euroleague_live import estimate_pace
from test_euroleague_live import source


class EuroHistoryAuditTests(unittest.TestCase):
    def copies(self, league="EUROCUP"):
        _, ev = observation(league)
        return {ev["game"][f"{side}_team_id"]: dict(
            key=ev["game"][f"{side}_team_id"], captured_at_utc=ev["observed_at_utc"]+1,
            records=[values(deepcopy(ev), home=side=="home")]) for side in ("home", "away")}

    def test_shared_match_counted_once(self):
        result = audit_history(self.copies(), league="EUROCUP", year=2026)
        self.assertEqual(result["team_records"], 2)
        self.assertEqual(result["distinct_fixtures"], 1)
        self.assertEqual(result["duplicate_cross_team_records"], 1)
        self.assertAlmostEqual(result["pace_mean"], 78.08)
        self.assertIsNone(result["pace_sample_std"])
        self.assertEqual(result["calibration_status"], "NOT_ESTABLISHED")
        self.assertFalse(result["independent_provider_verified"])

    def test_competition_and_season_separation(self):
        for league, year in (("EUROLEAGUE", 2026), ("EUROCUP", 2025)):
            with self.subTest(league=league, year=year), self.assertRaises(ValueError):
                audit_history(self.copies(), league=league, year=year)

    def test_duplicate_within_team_rejected(self):
        copies = self.copies()
        copies["KLA"]["records"] *= 2
        with self.assertRaises(ValueError):
            audit_history(copies, league="EUROCUP", year=2026)

    def test_corrupt_score_pace_and_evidence_rejected(self):
        for field, value in (("pace", 100), ("pts_for", 99), ("pace_evidence", None),
                             ("source", "manual"), ("home", False)):
            copies = self.copies()
            copies["KLA"]["records"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                audit_history(copies, league="EUROCUP", year=2026)

    def test_late_observation_cannot_enter_capture(self):
        copies = self.copies()
        copies["KLA"]["captured_at_utc"] -= 1
        with self.assertRaises(ValueError):
            audit_history(copies, league="EUROCUP", year=2026)

    def test_identity_empty_and_malformed_inputs_rejected(self):
        for copies in ({}, [], {"KLA": {}}, {"kla": self.copies()["KLA"]}):
            with self.subTest(copies=copies), self.assertRaises(ValueError):
                audit_history(copies, league="EUROCUP", year=2026)

    def test_audit_preserves_input_and_euroleague_is_supported(self):
        copies = self.copies("EUROLEAGUE")
        before = deepcopy(copies)
        result = audit_history(copies, league="EUROLEAGUE", year=2026)
        self.assertEqual(copies, before)
        self.assertEqual(result["fixture_ids"], ["E2026_1"])

    def test_valid_but_conflicting_source_identity_rejected(self):
        copies = self.copies()
        raw = source("EUROCUP")
        raw["game"]["id"] = "12345678-1234-4234-8234-123456789abc"
        observed = copies["TRN"]["captured_at_utc"]-1
        ev = estimate_pace(raw["game"], raw["stats"], league="EUROCUP", year=2026,
                           observed_at_utc=observed)
        self.assertIsNotNone(ev)
        copies["TRN"]["records"] = [values(ev, home=False)]
        with self.assertRaisesRegex(ValueError, "conflicting fixture"):
            audit_history(copies, league="EUROCUP", year=2026)

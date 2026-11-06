"""Cross-league regression checks for the shared, source-agnostic roster gate.

These fixtures are synthetic; no real roster/provider accuracy is asserted.
"""
import unittest

from faz40_roster_evidence import seal_roster_observation, validate_roster_observation


class CrossLeagueRosterEvidenceTests(unittest.TestCase):
    def test_nba_and_euroleague_are_isolated_by_fixture_id(self):
        for league in ("NBA", "EUROLEAGUE", "EUROCUP", "NBL", "KBL", "CBA"):
            with self.subTest(league=league):
                fixture = f"{league}:2026:fixture-1"
                evidence = seal_roster_observation(
                    fixture_id=fixture, observed_at_utc=100, source="SYNTHETIC_TEST",
                    players=["a", "b", "c", "d", "e", "f"],
                    starting_five=["a", "b", "c", "d", "e"], status="CONFIRMED")
                self.assertEqual(validate_roster_observation(
                    evidence, fixture_id=fixture, prediction_utc=110,
                    tipoff_utc=120, require_confirmed=True)["fixture_id"], fixture)
                with self.assertRaisesRegex(ValueError, "fixture"):
                    validate_roster_observation(
                        evidence, fixture_id=f"{league}:2026:fixture-2",
                        prediction_utc=110, tipoff_utc=120, require_confirmed=True)

    def test_same_fixture_name_without_league_namespace_is_not_safe(self):
        # Integration must supply a league-qualified canonical fixture ID.
        # This is a contract test for the integration layer, not an assertion
        # that the current evidence function itself enforces namespacing.
        nba = "NBA:2026:fixture-1"
        euroleague = "EUROLEAGUE:2026:fixture-1"
        self.assertNotEqual(nba, euroleague)

    def test_future_roster_cannot_leak_into_archived_prediction(self):
        evidence = seal_roster_observation(
            fixture_id="NBA:2026:fixture-1", observed_at_utc=130,
            source="SYNTHETIC_TEST", players=["a", "b", "c", "d", "e"],
            starting_five=["a", "b", "c", "d", "e"], status="CONFIRMED")
        with self.assertRaisesRegex(ValueError, "before prediction"):
            validate_roster_observation(evidence, fixture_id="NBA:2026:fixture-1",
                                        prediction_utc=110, tipoff_utc=140,
                                        require_confirmed=True)


if __name__ == "__main__":
    unittest.main()

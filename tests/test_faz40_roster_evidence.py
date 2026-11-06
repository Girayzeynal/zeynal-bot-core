import copy
import unittest

from faz40_roster_evidence import seal_roster_observation, validate_roster_observation


PLAYERS = ["p1", "p2", "p3", "p4", "p5", "p6"]


class Faz40RosterEvidenceTests(unittest.TestCase):
    def evidence(self, **changes):
        args = dict(fixture_id="EL-2026-1", observed_at_utc=100, source="OFFICIAL_FIXTURE",
                    players=PLAYERS, starting_five=PLAYERS[:5], status="CONFIRMED")
        args.update(changes)
        return seal_roster_observation(**args)

    def validate(self, evidence, **changes):
        args = dict(fixture_id="EL-2026-1", prediction_utc=110, tipoff_utc=120,
                    require_confirmed=True)
        args.update(changes)
        return validate_roster_observation(evidence, **args)

    def test_confirmed_five_before_prediction(self):
        self.assertEqual(self.validate(self.evidence())["status"], "CONFIRMED")

    def test_unconfirmed_cannot_be_promoted(self):
        with self.assertRaisesRegex(ValueError, "Unconfirmed"):
            self.validate(self.evidence(status="UNCONFIRMED"))

    def test_missing_five_cannot_be_confirmed(self):
        with self.assertRaisesRegex(ValueError, "five"):
            self.evidence(starting_five=None)

    def test_duplicate_five_rejected(self):
        with self.assertRaisesRegex(ValueError, "five"):
            self.evidence(starting_five=["p1"] * 5)

    def test_unknown_player_rejected(self):
        with self.assertRaisesRegex(ValueError, "five"):
            self.evidence(starting_five=["p1", "p2", "p3", "p4", "unknown"])

    def test_post_prediction_observation_rejected(self):
        with self.assertRaisesRegex(ValueError, "before prediction"):
            self.validate(self.evidence(observed_at_utc=111))

    def test_wrong_fixture_rejected(self):
        with self.assertRaisesRegex(ValueError, "fixture"):
            self.validate(self.evidence(), fixture_id="EL-2026-2")

    def test_tampering_rejected(self):
        evidence = copy.deepcopy(self.evidence())
        evidence["payload"]["starting_five"][0] = "p6"
        with self.assertRaisesRegex(ValueError, "integrity"):
            self.validate(evidence)

    def test_no_source_rejected(self):
        with self.assertRaisesRegex(ValueError, "source"):
            self.evidence(source="")

    def test_no_synthetic_lineup(self):
        evidence = self.evidence(starting_five=None, status="UNCONFIRMED")
        self.assertIsNone(self.validate(evidence, require_confirmed=False)["starting_five"])


if __name__ == "__main__":
    unittest.main()

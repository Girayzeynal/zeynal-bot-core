import unittest
from espn_final_parser import parse_espn_regulation_final


def event(home, away, completed=True, name="STATUS_FINAL"):
    return {"id": "401999999", "status": {"type": {"completed": completed, "name": name}},
            "competitions": [{"competitors": [
                {"homeAway": "home", "score": str(sum(home)),
                 "linescores": [{"value": n} for n in home]},
                {"homeAway": "away", "score": str(sum(away)),
                 "linescores": [{"value": n} for n in away]},
            ]}]}


class ESPNFinalParserTests(unittest.TestCase):
    def test_regulation(self):
        result = parse_espn_regulation_final(event([25, 30, 28, 22], [22, 29, 24, 27]))
        self.assertEqual((result["home"], result["away"]), (105, 102))
        self.assertFalse(result["has_overtime"])

    def test_overtime_excluded(self):
        result = parse_espn_regulation_final(event([25, 30, 28, 22, 15], [22, 29, 24, 30, 13]))
        self.assertEqual((result["home"], result["away"]), (105, 105))
        self.assertEqual((result["final_with_ot_home"], result["final_with_ot_away"]), (120, 118))
        self.assertTrue(result["has_overtime"])

    def test_live_rejected(self):
        self.assertIsNone(parse_espn_regulation_final(event([25, 30, 28, 22], [22, 29, 24, 27], False)))

    def test_inconsistent_score_rejected(self):
        bad = event([25, 30, 28, 22], [22, 29, 24, 27])
        bad["competitions"][0]["competitors"][0]["score"] = "999"
        self.assertIsNone(parse_espn_regulation_final(bad))

    def test_missing_quarter_rejected(self):
        self.assertIsNone(parse_espn_regulation_final(event([25, 30, 28], [22, 29, 24, 27])))


if __name__ == "__main__":
    unittest.main()

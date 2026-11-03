"""Validate scheduled API-Sports league identifiers in deployment configuration."""
import json
import unittest
from pathlib import Path


class LeagueScheduleConfigTests(unittest.TestCase):
    def test_enabled_schedules_have_positive_integer_api_sports_ids(self):
        path = Path(__file__).resolve().parents[1] / "leagues.json"
        leagues = json.loads(path.read_text(encoding="utf-8"))
        self.assertIsInstance(leagues, list)
        self.assertTrue(leagues, "league configuration must not be empty")
        for league in leagues:
            with self.subTest(league=league.get("name")):
                if league.get("enabled_schedule") is True:
                    league_id = league.get("api_sports_league_id")
                    self.assertIs(type(league_id), int)
                    self.assertGreater(league_id, 0)

    def test_enabled_schedule_ids_are_unique(self):
        path = Path(__file__).resolve().parents[1] / "leagues.json"
        leagues = json.loads(path.read_text(encoding="utf-8"))
        enabled = [item for item in leagues if item.get("enabled_schedule") is True]
        ids = [item.get("api_sports_league_id") for item in enabled]
        self.assertEqual(len(ids), len(set(ids)),
                         "enabled leagues must not share an API-Sports league ID")

    def test_league_names_are_unique(self):
        path = Path(__file__).resolve().parents[1] / "leagues.json"
        leagues = json.loads(path.read_text(encoding="utf-8"))
        names = [item.get("name") for item in leagues]
        self.assertTrue(all(isinstance(name, str) and name.strip() for name in names))
        self.assertEqual(len(names), len(set(names)))

    def test_scheduler_skips_disabled_leagues_before_id_validation(self):
        import ast
        scheduler_path = Path(__file__).resolve().parents[1] / "dynamic_scheduler.py"
        tree = ast.parse(scheduler_path.read_text(encoding="utf-8"))
        loops = [node for node in ast.walk(tree)
                 if isinstance(node, ast.For)
                 and isinstance(node.target, ast.Name)
                 and node.target.id == "lg"
                 and isinstance(node.iter, ast.Name)
                 and node.iter.id == "leagues"]
        self.assertEqual(len(loops), 1)
        first = loops[0].body[0]
        self.assertIsInstance(first, ast.If)
        self.assertEqual(ast.unparse(first.test),
                         "lg.get('enabled_schedule') is not True")
        self.assertEqual(len(first.body), 1)
        self.assertIsInstance(first.body[0], ast.Continue)

    def test_bcl_remains_disabled_until_verified_id_is_configured(self):
        path = Path(__file__).resolve().parents[1] / "leagues.json"
        leagues = json.loads(path.read_text(encoding="utf-8"))
        bcl = [item for item in leagues if item.get("name") == "BCL"]
        self.assertEqual(len(bcl), 1)
        if bcl[0].get("api_sports_league_id") == 0:
            self.assertIs(bcl[0].get("enabled_schedule"), False)


if __name__ == "__main__":
    unittest.main()

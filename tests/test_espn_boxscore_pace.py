"""Real ESPN fixture plus adversarial and synthetic overtime contract cases."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import AsyncMock

from providers.espn_boxscore_pace import METHOD, estimate_pace_from_summary
from providers.espn_completed_event import parse_completed_nba_event
from providers.espn_adapter import ESPNAdapter


def fixture():
    return json.loads((Path(__file__).parent / "fixtures" / "espn-summary-401909903.json").read_text())


def game(payload):
    header = payload["header"]
    return parse_completed_nba_event(dict(header, date=header["competitions"][0]["date"]))


class BoxscorePaceTests(unittest.TestCase):
    def test_real_fixture_reconciles_scores_and_both_possession_estimates(self):
        payload = fixture()
        result = estimate_pace_from_summary(payload, game(payload))
        self.assertAlmostEqual(result["pace"], 94.4)
        self.assertAlmostEqual(result["inputs"]["home"]["estimated_possessions"], 94.36)
        self.assertAlmostEqual(result["inputs"]["away"]["estimated_possessions"], 94.44)
        self.assertEqual(result["duration_minutes"], 48)
        self.assertEqual(result["method"], METHOD)
        self.assertEqual(result["kind"], "BOX_SCORE_ESTIMATE")

    def test_overtime_normalizes_duration_without_assuming_regulation(self):
        payload = fixture()
        c = payload["header"]["competitions"][0]
        for competitor in c["competitors"]:
            last = int(competitor["linescores"][-1]["displayValue"])
            competitor["linescores"][-1]["displayValue"] = str(last - 5)
            competitor["linescores"].append({"displayValue": "5"})
        c["status"]["period"] = 5
        result = estimate_pace_from_summary(payload, game(payload))
        self.assertEqual(result["duration_minutes"], 53)
        self.assertAlmostEqual(result["pace"], 94.4 * 48 / 53)

    def test_identity_score_and_time_must_match_scoreboard(self):
        payload = fixture()
        for field, changed in (("provider_fixture_id", "999"), ("home_team_id", "999"),
                               ("actual_home", 98), ("start_ts_utc", 1),
                               ("scope", "REGULATION_ONLY")):
            with self.subTest(field=field):
                row = dict(game(payload), **{field: changed})
                self.assertIsNone(estimate_pace_from_summary(payload, row))

    def test_missing_duplicate_malformed_stats_are_rejected(self):
        for action in ("missing", "duplicate", "boolean", "negative", "decimal", "made_exceeds_attempts"):
            with self.subTest(action=action):
                payload = fixture()
                row = game(payload)
                stats = payload["boxscore"]["teams"][0]["statistics"]
                if action == "missing":
                    stats[:] = [s for s in stats if s["name"] != "totalTurnovers"]
                elif action == "duplicate":
                    stats.append(copy.deepcopy(stats[0]))
                else:
                    stats[0]["displayValue"] = {"boolean": True, "negative": "-1-84",
                                                "decimal": "37-84.5", "made_exceeds_attempts": "85-84"}[action]
                self.assertIsNone(estimate_pace_from_summary(payload, row))

    def test_missing_duration_wrong_team_and_score_disagreement_are_rejected(self):
        for action in ("duration", "period", "team", "score", "live", "season"):
            with self.subTest(action=action):
                payload = fixture()
                row = game(payload)
                c = payload["header"]["competitions"][0]
                if action == "duration":
                    del c["competitors"][0]["linescores"]
                elif action == "period":
                    c["status"]["period"] = 5
                elif action == "team":
                    payload["boxscore"]["teams"][0]["team"]["id"] = "999"
                elif action == "score":
                    payload["boxscore"]["teams"][0]["statistics"][0]["displayValue"] = "38-84"
                elif action == "season":
                    payload["header"]["season"]["type"] = 1
                else:
                    c["status"]["type"]["completed"] = False
                self.assertIsNone(estimate_pace_from_summary(payload, row))


class PaceFetchTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetches_summary_and_returns_reconciled_evidence(self):
        adapter = ESPNAdapter()
        payload = fixture()
        adapter._get_json = AsyncMock(return_value=payload)
        result = await adapter.fetch_pace_evidence(game(payload))
        self.assertAlmostEqual(result["pace"], 94.4)
        adapter._get_json.assert_awaited_once_with(
            "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event=401909903")

    async def test_missing_summary_never_produces_a_default(self):
        adapter = ESPNAdapter()
        adapter._get_json = AsyncMock(return_value=None)
        self.assertIsNone(await adapter.fetch_pace_evidence(game(fixture())))


if __name__ == "__main__":
    unittest.main()

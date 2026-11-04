"""Real trimmed source fixtures and synthetic rejection/duration cases."""
from copy import deepcopy
from email.utils import formatdate
import json
from pathlib import Path
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from league_profiles import get_league_profile
from providers.euroleague_live import (
    BASE, EuroleagueLiveAdapter, audit_catalog, estimate_pace, parse_game, replay_pace_evidence,
)


def source(league="EUROLEAGUE"):
    name = "euroleague" if league == "EUROLEAGUE" else "eurocup"
    return json.loads((Path(__file__).parent / "fixtures" / f"{name}-2026-source.json").read_text())


class EuroSourceTests(unittest.TestCase):
    def parse(self, raw, league="EUROLEAGUE"):
        return parse_game(raw, league=league, year=2026, observed_at_utc=int(time.time()))

    def pace(self, fixture, league="EUROLEAGUE"):
        return estimate_pace(fixture["game"], fixture["stats"], league=league, year=2026,
                             observed_at_utc=int(time.time()))

    def audit(self, fixture, rows):
        return audit_catalog(fixture["competition"], fixture["season"], dict(total=len(rows), data=rows),
                             league="EUROLEAGUE", year=2026, observed_at_utc=int(time.time()))

    def test_real_competition_scoped_identity_and_pace(self):
        for league, fixture_id, expected in (("EUROLEAGUE", "E2026_1", 79.12), ("EUROCUP", "U2026_12", 78.08)):
            with self.subTest(league=league):
                fixture = source(league)
                game = self.parse(fixture["game"], league)
                self.assertEqual(game["provider_fixture_id"], fixture_id)
                evidence = self.pace(fixture, league)
                self.assertAlmostEqual(evidence["pace"], expected)
                self.assertEqual(evidence["normalization_minutes"], 40)
                self.assertEqual(replay_pace_evidence(evidence), game)

    def test_confirmed_unplayed_game_does_not_supply_scores(self):
        raw = source()["game"]
        raw["played"] = False
        parsed = self.parse(raw)
        self.assertEqual(parsed["status"], "UNPLAYED")
        self.assertNotIn("actual_home", parsed)
        self.assertIsNone(estimate_pace(raw, source()["stats"], league="EUROLEAGUE", year=2026,
                                       observed_at_utc=int(time.time())))

    def test_cross_competition_and_season_mismatch_rejected(self):
        self.assertIsNone(self.parse(source("EUROCUP")["game"]))
        for field, value in (("code", "E2025"), ("alias", "2025-26"), ("year", True), ("competitionCode", "U")):
            raw = source()["game"]
            raw["season"][field] = value
            self.assertIsNone(self.parse(raw))

    def test_no_local_date_fallback_or_unconfirmed_time(self):
        for field, value in (("utcDate", "2026-09-24T18:00:00"), ("utcDate", None),
                             ("confirmedHour", False), ("played", 1)):
            raw = source()["game"]
            raw[field] = value
            self.assertIsNone(self.parse(raw))

    def test_future_played_game_and_invalid_partials_are_rejected(self):
        raw = source()["game"]
        raw["utcDate"] = "2027-01-01T00:00:00Z"
        self.assertIsNone(self.parse(raw))
        raw = source()["game"]
        raw["local"]["partials"]["partials1"] += 1
        self.assertIsNone(self.parse(raw))

    def test_score_bool_fraction_and_duplicate_team_are_rejected(self):
        for value in (True, 77.5, -1, None):
            raw = source()["game"]
            raw["local"]["score"] = value
            self.assertIsNone(self.parse(raw))
        raw = source()["game"]
        raw["road"]["club"]["code"] = raw["local"]["club"]["code"]
        self.assertIsNone(self.parse(raw))

    def test_overtime_uses_40_minute_normalization_and_explicit_tie(self):
        fixture = source("EUROCUP")
        raw, stats = fixture["game"], fixture["stats"]
        raw["local"]["partials"]["partials4"] += 3  # 76-76 after regulation.
        for side, ot, extra_points in (("local", 7, 10), ("road", 5, 5)):
            raw[side]["partials"]["extraPeriods"] = {"1": ot}
            raw[side]["score"] += extra_points
            stats[side]["total"]["timePlayed"] = 2700.0
            for field in ("points", "freeThrowsMade", "freeThrowsAttempted"):
                stats[side]["total"][field] += extra_points
                stats[side]["players"][0]["stats"][field] += extra_points
        evidence = self.pace(fixture, "EUROCUP")
        self.assertEqual(evidence["duration_minutes"], 45)
        self.assertAlmostEqual(evidence["pace"], 81.38*40/45)
        raw["local"]["partials"]["partials4"] -= 1
        raw["local"]["score"] -= 1
        self.assertIsNone(self.parse(raw, "EUROCUP"))

    def test_team_turnovers_cannot_be_silently_dropped(self):
        fixture = source()
        self.assertEqual(fixture["stats"]["road"]["team"]["turnovers"], 1)
        fixture["stats"]["road"]["total"]["turnovers"] -= 1
        self.assertIsNone(self.pace(fixture))

    def test_roster_club_season_and_player_identity_must_match(self):
        for action in ("club", "season", "duplicate"):
            fixture = source()
            member = fixture["stats"]["local"]["players"][0]["player"]
            if action == "club":
                member["club"]["code"] = "WRONG"
            elif action == "season":
                member["season"]["code"] = "E2025"
            else:
                member["person"]["code"] = fixture["stats"]["road"]["players"][0]["player"]["person"]["code"]
            self.assertIsNone(self.pace(fixture))

    def test_missing_statistics_and_duration_do_not_receive_defaults(self):
        for action in ("missing", "duration", "nonfinite"):
            fixture = source()
            total = fixture["stats"]["local"]["total"]
            if action == "missing":
                total.pop("freeThrowsAttempted")
            elif action == "duration":
                total["timePlayed"] = 2880
            else:
                total["turnovers"] = float("nan")
            self.assertIsNone(self.pace(fixture))

    def test_replay_rejects_altered_raw_statistics(self):
        evidence = self.pace(source())
        evidence["snapshot"]["stats"]["local"]["total"]["turnovers"] += 1
        with self.assertRaises(ValueError):
            replay_pace_evidence(evidence)

    def test_incomplete_catalog_and_wrong_official_mapping_are_rejected(self):
        fixture = source()
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            audit_catalog(fixture["competition"], fixture["season"], dict(total=2, data=[fixture["game"]]),
                          league="EUROLEAGUE", year=2026, observed_at_utc=int(time.time()))
        fixture["competition"]["code"] = "U"
        with self.assertRaisesRegex(ValueError, "mapping"):
            self.audit(fixture, [fixture["game"]])

    def test_conflicting_duplicates_are_all_excluded_with_conserved_counts(self):
        fixture = source()
        changed = deepcopy(fixture["game"])
        changed["local"]["score"] += 1
        changed["local"]["partials"]["partials4"] += 1
        audit = self.audit(fixture, [fixture["game"], fixture["game"], changed])
        self.assertEqual(audit["accepted_unique"], 0)
        self.assertEqual(audit["conflicting_records"], 3)
        self.assertEqual(audit["duplicate_identical"], 0)

    def test_uuid_collision_between_different_game_codes_is_rejected(self):
        fixture = source()
        changed = deepcopy(fixture["game"])
        changed.update(gameCode=2, identifier="E2026_2")
        audit = self.audit(fixture, [fixture["game"], changed])
        self.assertEqual(audit["accepted_unique"], 0)
        self.assertEqual(audit["conflicting_records"], 2)

    def test_eurocup_does_not_inherit_a_profile(self):
        with self.assertRaises(ValueError):
            get_league_profile("EUROCUP")


class EuroAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_route_responses_reconcile_and_replay(self):
        fixture = source()
        responses = {f"{BASE}/E": fixture["competition"], f"{BASE}/E/seasons/E2026": fixture["season"],
                     f"{BASE}/E/seasons/E2026/games": dict(total=1, data=[fixture["game"]]),
                     f"{BASE}/E/seasons/E2026/games/1": fixture["game"],
                     f"{BASE}/E/seasons/E2026/games/1/stats": fixture["stats"]}
        adapter = EuroleagueLiveAdapter()
        adapter._get_json = AsyncMock(side_effect=lambda url: responses[url])
        catalog = await adapter.fetch_catalog("EUROLEAGUE", 2026)
        self.assertEqual(catalog["accepted_unique"], 1)
        evidence = await adapter.fetch_pace_evidence(fixture["game"], league="EUROLEAGUE", year=2026)
        self.assertAlmostEqual(evidence["pace"], 79.12)

    async def test_missing_catalog_never_becomes_empty_success(self):
        adapter = EuroleagueLiveAdapter()
        adapter._get_json = AsyncMock(return_value=None)
        with self.assertRaises(RuntimeError):
            await adapter.fetch_catalog("EUROCUP", 2026)

    async def test_injected_session_is_not_closed(self):
        session = type("Session", (), {"closed": False, "close": AsyncMock()})()
        await EuroleagueLiveAdapter(session).aclose()
        session.close.assert_not_awaited()

    async def test_owned_session_uses_proxy_timeout_and_is_closed(self):
        with patch("providers.euroleague_live.aiohttp.ClientSession") as factory:
            session = factory.return_value
            session.closed = False
            session.close = AsyncMock()
            response = MagicMock(status=200)
            response.json = AsyncMock(return_value=source()["competition"])
            session.get.return_value.__aenter__ = AsyncMock(return_value=response)
            adapter = EuroleagueLiveAdapter()
            await adapter._get_json(f"{BASE}/E")
            await adapter._get_json(f"{BASE}/E")
            factory.assert_called_once()
            self.assertIs(factory.call_args.kwargs["trust_env"], True)
            self.assertEqual(factory.call_args.kwargs["timeout"].total, 15)
            response.json.side_effect = ValueError("HTTP 200 HTML response")
            self.assertIsNone(await adapter._get_json(f"{BASE}/E"))
            self.assertEqual(adapter.request_diagnostics[-1]["outcome"], "invalid_json")
            await adapter.aclose()
            session.close.assert_awaited_once()

    async def test_unknown_competition_never_makes_network_calls(self):
        adapter = EuroleagueLiveAdapter()
        adapter._get_json = AsyncMock()
        with self.assertRaises(ValueError):
            await adapter.fetch_catalog("FIBA EuroCup", 2026)
        adapter._get_json.assert_not_awaited()

    async def test_http_429_cooldown_prevents_immediate_repeated_requests(self):
        with patch("providers.euroleague_live.aiohttp.ClientSession") as factory:
            session = factory.return_value
            session.closed = False
            session.close = AsyncMock()
            response = MagicMock(status=429, headers={"Retry-After": "120"})
            session.get.return_value.__aenter__ = AsyncMock(return_value=response)
            adapter = EuroleagueLiveAdapter()
            self.assertIsNone(await adapter._get_json(f"{BASE}/E"))
            self.assertIsNone(await adapter._get_json(f"{BASE}/E"))
            session.get.assert_called_once()
            self.assertEqual(adapter.request_diagnostics[0]["http_status"], 429)
            self.assertEqual(adapter.request_diagnostics[-1]["outcome"], "rate_limit_cooldown")
            await adapter.aclose()

    async def test_cached_baseline_observation_is_not_restamped_or_mutable_by_caller(self):
        fixture = source()
        adapter = EuroleagueLiveAdapter(baseline_season_year=2026, allow_estimated_pace=True)
        adapter._get_json = AsyncMock(side_effect=lambda url: fixture["stats"] if url.endswith("/stats") else fixture["game"])
        first = await adapter.fetch_pace_evidence(fixture["game"], league="EUROLEAGUE", year=2026)
        observed = first["observed_at_utc"]
        first["inputs"]["home"]["fga"] = -1
        second = await adapter.fetch_pace_evidence(fixture["game"], league="EUROLEAGUE", year=2026)
        self.assertEqual(second["observed_at_utc"], observed)
        self.assertEqual(second["inputs"]["home"]["fga"], 73)
        self.assertEqual(adapter._get_json.await_count, 2)

    async def test_retry_after_http_date_is_respected(self):
        with patch("providers.euroleague_live.aiohttp.ClientSession") as factory:
            session = factory.return_value
            session.closed = False
            session.close = AsyncMock()
            response = MagicMock(status=429, headers={"Retry-After": formatdate(time.time()+180, usegmt=True)})
            session.get.return_value.__aenter__ = AsyncMock(return_value=response)
            adapter = EuroleagueLiveAdapter()
            before = time.monotonic()
            await adapter._get_json(f"{BASE}/E")
            self.assertGreaterEqual(adapter._request_not_before, before+170)
            await adapter.aclose()


if __name__ == "__main__":
    unittest.main()

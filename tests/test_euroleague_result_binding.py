"""Synthetic finals with actual FAZ13, fixture binding, source replay and SQLite rollback."""
from copy import deepcopy
from datetime import datetime, timezone
import contextlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import time
from uuid import uuid5, NAMESPACE_URL
import unittest
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from baseline.team_baseline_store import TeamBaselineStore, TeamBaseline
from bound_backtest_report import report_bound
from euroleague_prematch_orchestrator import persist_resolved_euroleague_prematch
from faz13_engine import Faz13Engine, PrematchRequest
from prediction_inputs import digest
from prediction_ledger import PredictionLedger, OutcomeRecord
from providers.euroleague_live import BASE, EuroleagueLiveAdapter
from providers.euroleague_result_evidence import capture_result_evidence
from providers.euroleague_results import ingest_bound_result, reconcile_euroleague_result
from verified_backtest_cli import main as report_cli
from test_euroleague_live import source
from test_euroleague_baseline_binding import observation, values

NOW = int(datetime(2026, 11, 4, 18, tzinfo=timezone.utc).timestamp())


class EuroleagueResultBindingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        clock_patch = patch("time.time", return_value=NOW)
        self.clock = clock_patch.start()
        self.addCleanup(clock_patch.stop)
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.store = TeamBaselineStore(str(Path(self.folder.name) / "baselines"))
        for code in range(1, 7):
            _, evidence = observation(code=code)
            for team, home in (("RED", True), ("ZAL", False)):
                self.store.append_game("EUROLEAGUE", team, **values(evidence, home=home))
        for team in ("RED", "ZAL"):
            self.store.put(TeamBaseline(league="EUROLEAGUE", team=team, updated_ts=NOW,
                **self.store.compute_dynamic_baseline("EUROLEAGUE", team, 6)))
        self.tipoff = NOW+3600
        day = datetime.fromtimestamp(self.tipoff, ZoneInfo("Europe/Istanbul")).date().isoformat()
        engine = Faz13Engine("", "https://example.invalid", baseline_store=self.store)
        engine.espn = None
        core = await engine.run_prematch(PrematchRequest(0, "EUROLEAGUE", day, "RED", "ZAL"))
        fixture = source()
        future = deepcopy(fixture["game"])
        future.update(identifier="E2026_9001", gameCode=9001, played=False,
            id=str(uuid5(NAMESPACE_URL, "synthetic-EuroLeague-result-target")),
            utcDate=datetime.fromtimestamp(self.tipoff, timezone.utc).isoformat())
        for side in ("local", "road"):
            future[side]["score"] = 0
            future[side]["partials"] = dict(partials1=0, partials2=0, partials3=0, partials4=0, extraPeriods={})
        self.url = f"{BASE}/E/seasons/E2026/games/9001"
        responses = {f"{BASE}/E": fixture["competition"], f"{BASE}/E/seasons/E2026": fixture["season"],
            f"{BASE}/E/seasons/E2026/games": dict(total=1, data=[future]), self.url: future}
        self.adapter = EuroleagueLiveAdapter()
        self.adapter._get_json = AsyncMock(side_effect=lambda url: deepcopy(responses.get(url)))
        self.ledger = PredictionLedger(str(Path(self.folder.name) / "research.sqlite"))
        await persist_resolved_euroleague_prematch(adapter=self.adapter, ledger=self.ledger, core=core, year=2026)
        self.fixture = self.ledger.load_fixture_observation("EUROLEAGUE", "E2026_9001")
        self.inputs = self.ledger.load_prediction_inputs("EUROLEAGUE", "E2026_9001")
        self.future = deepcopy(future)
        self.final = deepcopy(fixture["game"])
        for key in ("id", "identifier", "gameCode", "utcDate"):
            self.final[key] = future[key]
        self.stats = deepcopy(fixture["stats"])
        # Synthetic final 79-83, two points different from the source-based projection.
        self.final["local"]["score"] += 2
        self.final["local"]["partials"]["partials4"] += 2
        for block in (self.stats["local"]["total"], self.stats["local"]["players"][0]["stats"]):
            block["fieldGoalsMade2"] += 1
            block["fieldGoalsMadeTotal"] += 1
            block["points"] += 2
        self.clock.return_value = NOW+7200
        self.adapter._get_json = AsyncMock(side_effect=lambda url: deepcopy(
            self.final if url == self.url else self.stats if url == self.url+"/stats" else None))

    async def collect(self):
        return await reconcile_euroleague_result(adapter=self.adapter, ledger=self.ledger, fixture_id="E2026_9001")

    def assert_empty_results(self):
        with self.ledger._connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM outcome_evidence").fetchone()[0], 0)

    async def test_final_reopens_and_explicit_euroleague_report_evaluates_small_sample(self):
        self.assertEqual((await self.collect())["status"], "accepted")
        reopened = PredictionLedger(self.ledger.db_path).load_outcome_evidence("EUROLEAGUE", "E2026_9001")
        self.assertEqual(reopened["snapshot"]["event"]["actual_home"], 79)
        report = report_bound(self.ledger.db_path, "EUROLEAGUE")
        self.assertEqual(report["sample_size"], 1)
        self.assertEqual(report["provider"], "EUROLEAGUE_LIVE")
        self.assertEqual(report["metrics"]["total_mae"], 2)
        self.assertEqual(report["sample_size_assessment"], "small_sample")
        self.assertEqual(report["calibration_status"], "NOT_ESTABLISHED")
        self.assertEqual(report_bound(self.ledger.db_path)["sample_size"], 0)

    async def test_pending_before_tipoff_does_not_request_or_invent_result(self):
        self.clock.return_value = NOW
        self.assertEqual((await self.collect())["status"], "awaiting_tipoff")
        self.adapter._get_json.assert_not_awaited()
        self.assert_empty_results()
        report = report_bound(self.ledger.db_path, "EUROLEAGUE")
        self.assertEqual(report["excluded"]["awaiting_result"], 1)
        self.assertIsNone(report["metrics"])

    async def test_unplayed_after_tipoff_is_pending_without_fetching_stats(self):
        self.final = deepcopy(self.future)
        self.assertEqual((await self.collect())["status"], "awaiting_final")
        self.assertEqual(self.adapter._get_json.await_count, 1)
        self.assert_empty_results()

    async def test_unavailable_or_malformed_final_cannot_be_recorded(self):
        self.adapter._get_json.side_effect = None
        self.adapter._get_json.return_value = None
        self.assertEqual((await self.collect())["status"], "provider_unavailable")
        self.adapter._get_json.return_value = {"played": True}
        self.assertEqual((await self.collect())["status"], "invalid_result")
        self.assert_empty_results()

    async def test_wrong_id_uuid_start_or_direction_is_rejected(self):
        original = deepcopy(self.final)
        for key, changed in (("identifier", "E2026_9002"), ("id", str(uuid5(NAMESPACE_URL, "wrong-uuid"))),
                             ("utcDate", datetime.fromtimestamp(self.tipoff+1, timezone.utc).isoformat()),
                             ("direction", None)):
            self.final = deepcopy(original)
            if key == "direction":
                self.final["local"]["club"]["code"], self.final["road"]["club"]["code"] = "ZAL", "RED"
            else:
                self.final[key] = changed
            self.assertIn((await self.collect())["status"], ("invalid_result", "fixture_identity_conflict"))
            self.assert_empty_results()

    async def test_missing_stats_clock_or_score_agreement_prevents_final_acceptance(self):
        original = deepcopy(self.stats)
        for change in ("clock", "points", "missing"):
            self.stats = deepcopy(original)
            if change == "clock":
                self.stats["local"]["total"]["timePlayed"] = 1800
            elif change == "points":
                self.stats["local"]["total"]["points"] += 1
            else:
                self.stats["road"]["total"].pop("turnovers")
            self.assertEqual((await self.collect())["status"], "invalid_result_evidence")
            self.assert_empty_results()

    async def test_overtime_scope_uses_all_periods_and_45_minute_clock(self):
        fixture = source()
        self.final = deepcopy(fixture["game"])
        for key in ("id", "identifier", "gameCode", "utcDate"):
            self.final[key] = self.future[key]
        self.stats = deepcopy(fixture["stats"])
        self.final["local"]["partials"]["partials4"] += 6  # 83-83 regulation tie.
        for side, overtime, extra_points in (("local", 7, 13), ("road", 5, 5)):
            self.final[side]["partials"]["extraPeriods"] = {"1": overtime}
            self.final[side]["score"] += extra_points
            self.stats[side]["total"]["timePlayed"] = 2700
            for field in ("points", "freeThrowsMade", "freeThrowsAttempted"):
                self.stats[side]["total"][field] += extra_points
                self.stats[side]["players"][0]["stats"][field] += extra_points
        self.assertEqual((await self.collect())["status"], "accepted")
        evidence = self.ledger.load_outcome_evidence("EUROLEAGUE", "E2026_9001")
        self.assertEqual(evidence["snapshot"]["event"]["duration_minutes"], 45)
        self.assertEqual(evidence["snapshot"]["event"]["scope"], "FINAL_WITH_OT")

    async def test_result_evidence_storage_failure_rolls_back_outcome(self):
        with self.ledger._connect() as db:
            db.execute("""CREATE TRIGGER fail_euro_result BEFORE INSERT ON outcome_evidence
                          BEGIN SELECT RAISE(ABORT, 'synthetic storage failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            await self.collect()
        self.assert_empty_results()

    async def test_repeat_fetch_keeps_first_observation_and_rejects_new_source_facts(self):
        await self.collect()
        original = self.ledger.load_outcome_evidence("EUROLEAGUE", "E2026_9001")
        self.clock.return_value += 30
        repeated = await self.collect()
        self.assertEqual(repeated["status"], "accepted")
        self.assertEqual(repeated["result_evidence_sha256"], original["sha256"])
        self.assertEqual(self.ledger.load_outcome_evidence("EUROLEAGUE", "E2026_9001"), original)
        self.final["local"]["score"] += 1
        self.final["local"]["partials"]["partials4"] += 1
        for stats in (self.stats["local"]["total"], self.stats["local"]["players"][0]["stats"]):
            stats["points"] += 1
            stats["freeThrowsMade"] += 1
            stats["freeThrowsAttempted"] += 1
        self.assertEqual((await self.collect())["status"], "unmatched_or_conflicting_result")
        self.assertEqual(self.ledger.load_outcome_evidence("EUROLEAGUE", "E2026_9001"), original)

    async def test_backdating_and_wrong_input_digest_are_rejected(self):
        await self.collect()
        original = self.ledger.load_outcome_evidence("EUROLEAGUE", "E2026_9001")
        old = capture_result_evidence(self.final, self.stats, original_fixture=self.fixture,
            original_inputs=self.inputs, observed_at_utc=original["snapshot"]["observed_at_utc"]-1)
        self.assertFalse(ingest_bound_result(self.ledger, "E2026_9001", old))
        altered = deepcopy(original)
        altered["snapshot"]["prediction_input_sha256"] = "0"*64
        altered["sha256"] = digest(altered["snapshot"])
        self.assertFalse(ingest_bound_result(self.ledger, "E2026_9001", altered))

    async def test_existing_legacy_result_cannot_receive_observation_posthoc(self):
        self.ledger.record_outcome(OutcomeRecord("E2026_9001", "EUROLEAGUE", int(time.time()), 79, 83))
        self.assertEqual((await self.collect())["status"], "unmatched_or_conflicting_result")
        report = report_bound(self.ledger.db_path, "EUROLEAGUE")
        self.assertEqual(report["excluded"]["missing_result_evidence"], 1)
        self.assertIsNone(report["metrics"])

    async def test_missing_original_fixture_cannot_collect_or_evaluate(self):
        with self.ledger._connect() as db:
            db.execute("DELETE FROM fixture_observations")
        self.assertEqual((await self.collect())["status"], "missing_original_binding")
        self.adapter._get_json.assert_not_awaited()
        self.assert_empty_results()
        self.assertEqual(report_bound(self.ledger.db_path, "EUROLEAGUE")["excluded"]["missing_fixture_observation"], 1)

    async def test_corrupt_outcome_or_evidence_is_excluded_from_error_metrics(self):
        await self.collect()
        with self.ledger._connect() as db:
            db.execute("UPDATE outcomes SET actual_home=80")
        report = report_bound(self.ledger.db_path, "EUROLEAGUE")
        self.assertEqual(report["excluded"]["invalid_result_evidence"], 1)
        self.assertIsNone(report["metrics"])
        with self.ledger._connect() as db:
            db.execute("UPDATE outcome_evidence SET evidence_json='[]'")
        with self.assertRaises(ValueError):
            self.ledger.load_outcome_evidence("EUROLEAGUE", "E2026_9001")
        with self.ledger._connect() as db:
            db.execute("UPDATE fixture_observations SET observation_json='[]'")
        report = report_bound(self.ledger.db_path, "EUROLEAGUE")
        self.assertEqual(report["excluded"]["invalid_fixture_observation"], 1)
        self.assertIsNone(report["metrics"])
        self.adapter._get_json.reset_mock()
        self.assertEqual((await self.collect())["status"], "invalid_original_binding")
        self.adapter._get_json.assert_not_awaited()

    async def test_scope_mismatch_and_unsupported_leagues_do_not_create_metrics(self):
        self.ledger.record_outcome(OutcomeRecord("E2026_9001", "EUROLEAGUE", int(time.time()), 79, 83, "REGULATION_ONLY"))
        self.assertEqual(report_bound(self.ledger.db_path, "EUROLEAGUE")["excluded"]["scope_mismatch"], 1)
        with self.assertRaises(ValueError):
            report_bound(self.ledger.db_path, "EUROCUP")

    async def test_readonly_cli_uses_explicit_league_and_preserves_source_bytes(self):
        await self.collect()
        before = Path(self.ledger.db_path).read_bytes()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = report_cli([self.ledger.db_path, "--league", "EUROLEAGUE", "--require-bound-evidence"])
        self.assertEqual(code, 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report["provider"], "EUROLEAGUE_LIVE")
        self.assertEqual(report["sample_size"], 1)
        self.assertEqual(Path(self.ledger.db_path).read_bytes(), before)


if __name__ == "__main__":
    unittest.main()

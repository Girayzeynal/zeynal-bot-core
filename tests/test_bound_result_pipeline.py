"""Synthetic offline result observations; no live scores or predictions are invented."""
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import contextlib
import io
import json
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import AsyncMock

from bound_backtest_report import report_bound
from prediction_inputs import seal_prediction_inputs
from prediction_ledger import PredictionLedger, OutcomeRecord
from prematch_ledger_bridge import record_verified_prematch_projection
from providers.espn_adapter import ESPNAdapter
from providers.espn_bound_results import reconcile_bound_result
from providers.espn_ledger_ingest import ingest_completed_espn_nba_event
from providers.espn_result_evidence import capture_result_evidence
from verified_backtest_cli import main as report_cli


def summary(start, source_id="99001", final=True, home_score="115"):
    return {"header": {"id": source_id, "competitions": [{
        "id": source_id, "date": datetime.fromtimestamp(start, timezone.utc).isoformat(),
        "status": {"type": {"state": "post" if final else "in", "completed": final}},
        "competitors": [
            {"homeAway": "home", "team": {"id": "1"}, "score": home_score},
            {"homeAway": "away", "team": {"id": "2"}, "score": "108"},
        ],
    }]}}


class BoundResultPipelineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = str(Path(self.folder.name) / "ledger.sqlite")
        self.ledger = PredictionLedger(self.path)
        self.start = int(time.time()) - 7200
        predicted = self.start - 120
        core = SimpleNamespace(ctx=SimpleNamespace(league="NBA", date="2026-11-04", home="Home", away="Away"),
            meta=dict(generated_at=predicted, expected_home=107.5, expected_away=107.5))
        teams = {side: dict(key=name, captured_at_utc=predicted-1, records=[
            dict(ts_utc=self.start-86400-i, pts_for=110, pts_against=105, pace=99, home=True,
                 source="SYNTHETIC_TEST_PROVIDER", game_id=f"{side}-{i}",
                 timestamp_precision="exact", pace_evidence=None) for i in range(6)])
                 for side, name in (("home", "Home"), ("away", "Away"))}
        snapshot = seal_prediction_inputs(core, teams["home"], teams["away"])
        record_verified_prematch_projection(self.ledger, league="NBA", fixture_id="local-1",
            provider="ESPN", provider_fixture_id="99001", tipoff_utc=self.start,
            prediction_utc=predicted, expected_home=107.5, expected_away=107.5, input_snapshot=snapshot)
        self.adapter = ESPNAdapter()
        self.adapter._get_json = AsyncMock(return_value=summary(self.start))
        self.adapter.resolve_team = AsyncMock(side_effect=lambda name: {"id": "1" if name == "Home" else "2"})

    async def collect(self):
        return await reconcile_bound_result(adapter=self.adapter, ledger=self.ledger, fixture_id="local-1")

    def assert_empty_outcomes(self):
        with self.ledger._connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM outcome_evidence").fetchone()[0], 0)

    async def test_final_result_replays_and_strict_report_counts_one_small_sample(self):
        self.assertEqual((await self.collect())["status"], "accepted")
        reopened = PredictionLedger(self.path).load_outcome_evidence("NBA", "local-1")
        self.assertEqual(reopened["snapshot"]["event"]["actual_home"], 115)
        result = report_bound(self.path)
        self.assertEqual(result["sample_size"], 1)
        self.assertEqual(result["metrics"]["total_mae"], 8)
        self.assertEqual(result["sample_size_assessment"], "small_sample")
        self.assertEqual(result["calibration_status"], "NOT_ESTABLISHED")

    async def test_before_tipoff_does_not_fetch_or_record_results(self):
        future = int(time.time()) + 60
        with self.ledger._connect() as db:
            db.execute("UPDATE fixture_starts SET start_ts_utc=?", (future,))
            db.execute("UPDATE fixture_provenance SET start_ts_utc=?", (future,))
        self.assertEqual((await self.collect())["status"], "awaiting_tipoff")
        self.adapter._get_json.assert_not_awaited()
        self.assert_empty_outcomes()

    async def test_incomplete_unavailable_and_conflicting_statuses_never_become_results(self):
        conflicting = summary(self.start)
        conflicting["header"]["status"] = {"type": {"state": "pre", "completed": False}}
        for payload, expected in ((summary(self.start, final=False), "awaiting_final"),
                                  (None, "provider_unavailable"),
                                  (conflicting, "invalid_result")):
            with self.subTest(expected=expected):
                self.adapter._get_json.return_value = payload
                self.assertEqual((await self.collect())["status"], expected)
                self.assert_empty_outcomes()

    async def test_wrong_provider_fixture_or_start_is_rejected(self):
        for payload in (summary(self.start, source_id="99002"), summary(self.start-1)):
            self.adapter._get_json.return_value = payload
            self.assertEqual((await self.collect())["status"], "fixture_identity_conflict")
            self.assert_empty_outcomes()

    async def test_home_away_team_conflict_is_rejected(self):
        payload = summary(self.start)
        sides = payload["header"]["competitions"][0]["competitors"]
        sides[0]["team"]["id"], sides[1]["team"]["id"] = "2", "1"
        self.adapter._get_json.return_value = payload
        self.assertEqual((await self.collect())["status"], "team_identity_conflict")
        self.assert_empty_outcomes()

    async def test_unbound_prediction_cannot_collect_or_evaluate_results(self):
        with self.ledger._connect() as db:
            db.execute("DELETE FROM prediction_inputs")
        self.assertEqual((await self.collect())["status"], "missing_prediction_inputs")
        self.adapter._get_json.assert_not_awaited()
        self.assertEqual(report_bound(self.path)["excluded"]["missing_inputs"], 1)
        self.assert_empty_outcomes()

    async def test_repeat_fetch_preserves_original_observation_and_conflict_is_rejected(self):
        await self.collect()
        original = self.ledger.load_outcome_evidence("NBA", "local-1")
        self.assertEqual((await self.collect())["status"], "accepted")
        self.assertEqual(self.ledger.load_outcome_evidence("NBA", "local-1"), original)
        self.adapter._get_json.return_value = summary(self.start, home_score="116")
        self.assertEqual((await self.collect())["status"], "unmatched_or_conflicting_result")
        self.assertEqual(self.ledger.load_outcome_evidence("NBA", "local-1"), original)

    async def test_result_evidence_insert_failure_rolls_back_outcome(self):
        with self.ledger._connect() as db:
            db.execute("""CREATE TRIGGER fail_result_evidence BEFORE INSERT ON outcome_evidence
                          BEGIN SELECT RAISE(ABORT, 'synthetic disk failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            await self.collect()
        self.assert_empty_outcomes()

    async def test_legacy_result_cannot_receive_evidence_posthoc(self):
        self.ledger.record_outcome(OutcomeRecord("local-1", "NBA", int(time.time()), 115, 108))
        self.assertEqual((await self.collect())["status"], "unmatched_or_conflicting_result")
        result = report_bound(self.path)
        self.assertEqual(result["excluded"]["missing_result_evidence"], 1)
        self.assertIsNone(result["metrics"])

    async def test_sql_result_tampering_is_excluded_from_metrics(self):
        await self.collect()
        with self.ledger._connect() as db:
            db.execute("UPDATE outcomes SET actual_home=116")
        result = report_bound(self.path)
        self.assertEqual(result["excluded"]["invalid_result_evidence"], 1)
        self.assertIsNone(result["metrics"])

    async def test_malformed_result_json_is_rejected_on_read_and_repeat_collection(self):
        await self.collect()
        with self.ledger._connect() as db:
            db.execute("UPDATE outcome_evidence SET evidence_json='[]'")
        with self.assertRaises(ValueError):
            self.ledger.load_outcome_evidence("NBA", "local-1")
        self.assertEqual((await self.collect())["status"], "unmatched_or_conflicting_result")
        self.assertEqual(report_bound(self.path)["excluded"]["invalid_result_evidence"], 1)

    async def test_backdated_observation_and_wrong_input_digest_are_rejected(self):
        await self.collect()
        original = self.ledger.load_outcome_evidence("NBA", "local-1")
        event = original["snapshot"]["event"]
        observed = original["snapshot"]["observed_at_utc"] - 1
        evidence = capture_result_evidence(summary(self.start), observed_at_utc=observed,
            input_sha256=original["snapshot"]["prediction_input_sha256"], home_team_id="1", away_team_id="2")
        self.assertFalse(ingest_completed_espn_nba_event(self.ledger, "local-1", event, observed,
                                                       result_evidence=evidence))
        evidence = capture_result_evidence(summary(self.start), observed_at_utc=int(time.time()),
            input_sha256="0"*64, home_team_id="1", away_team_id="2")
        self.assertFalse(ingest_completed_espn_nba_event(self.ledger, "local-1", event,
            evidence["snapshot"]["observed_at_utc"], result_evidence=evidence))
        self.assertEqual(self.ledger.load_outcome_evidence("NBA", "local-1"), original)

    async def test_pending_and_scope_mismatched_results_have_no_metrics(self):
        result = report_bound(self.path)
        self.assertEqual(result["excluded"]["awaiting_result"], 1)
        self.assertIsNone(result["metrics"])
        self.ledger.record_outcome(OutcomeRecord("local-1", "NBA", int(time.time()), 100, 99, "REGULATION_ONLY"))
        result = report_bound(self.path)
        self.assertEqual(result["excluded"]["scope_mismatch"], 1)
        self.assertIsNone(result["metrics"])

    async def test_strict_cli_evaluates_a_copy_and_leaves_source_unchanged(self):
        await self.collect()
        original = Path(self.path).read_bytes()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = report_cli([self.path, "--require-bound-evidence"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["sample_size"], 1)
        self.assertEqual(Path(self.path).read_bytes(), original)


if __name__ == "__main__":
    unittest.main()

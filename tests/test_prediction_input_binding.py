"""Synthetic offline FAZ13 -> provider resolver -> atomic ledger input binding."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3
from statistics import mean, pstdev
import tempfile
import time
import unittest
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from baseline.team_baseline_store import TeamBaseline, TeamBaselineStore
from faz13_engine import Faz13Engine, PrematchRequest
from nba_prematch_orchestrator import persist_resolved_nba_prematch
from prediction_inputs import digest
from prediction_ledger import PredictionLedger
from prematch_ledger_bridge import record_verified_prematch_projection
from providers.espn_adapter import ESPNAdapter


class PredictionInputBindingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.store = TeamBaselineStore(str(Path(self.folder.name) / "baselines"))
        now = int(time.time())
        for team, pf, pa in (("BOS", 110, 100), ("NYK", 105, 108)):
            for i in range(6):
                self.store.append_game("NBA", team, pf+i, pa+i, 98+i, i % 2 == 0,
                    ts_utc=now-(i+1)*86400, game_id=f"synthetic-{team}-{i}",
                    source="SYNTHETIC_TEST_PROVIDER", timestamp_precision="exact")
            rows = self.store.get_series("NBA", team, 10)
            self.store.put(TeamBaseline("NBA", team, len(rows),
                mean(r.pts_for for r in rows), mean(r.pts_against for r in rows),
                mean(r.pace for r in rows), pstdev(r.pts_for+r.pts_against for r in rows), now))
        self.tipoff = now + 86400
        day = datetime.fromtimestamp(self.tipoff, ZoneInfo("Europe/Istanbul")).date().isoformat()
        self.engine = Faz13Engine("", "https://example.invalid", baseline_store=self.store)
        self.engine.espn = None
        self.request = PrematchRequest(0, "NBA", day, "BOS", "NYK")
        self.core = await self.engine.run_prematch(self.request)
        self.ledger = PredictionLedger(str(Path(self.folder.name) / "ledger.sqlite"))
        self.fixture = dict(provider="ESPN", provider_fixture_id="synthetic-target",
                            home_team_id="2", away_team_id="18", start_ts_utc=self.tipoff)
        self.adapter = ESPNAdapter()
        self.adapter.resolve_team = AsyncMock(side_effect=lambda name: {"id": "2" if name == "BOS" else "18"})
        self.adapter.fetch_scheduled_nba_scoreboard_date = AsyncMock(return_value=[self.fixture])

    async def persist(self):
        return await persist_resolved_nba_prematch(
            adapter=self.adapter, ledger=self.ledger, core=self.core,
            observed_at_utc=int(time.time()))

    def assert_no_prediction(self):
        with self.ledger._connect() as db:
            for table in ("predictions", "prediction_inputs"):
                self.assertEqual(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)

    async def test_actual_engine_captures_inputs_and_ledger_reopens_them(self):
        self.assertEqual(self.core.meta["input_snapshot_status"], "CAPTURED")
        self.assertEqual(self.core.meta["data_quality"], "VERIFIED_BASELINE")
        self.assertTrue((await self.persist())["inserted"])
        reopened = PredictionLedger(self.ledger.db_path)
        stored = reopened.load_prediction_inputs("NBA", "synthetic-target")
        self.assertEqual(stored, self.core.meta["input_snapshot"])
        self.assertEqual(len(stored["payload"]["teams"]["home"]["records"]), 6)
        self.assertFalse((await self.persist())["inserted"])
        self.assertEqual(self.ledger.audit_prediction_inputs("NBA"),
                         dict(predictions=1, bound=1, missing=0, invalid=0, orphaned=0))

    async def test_series_pruning_after_generation_cannot_change_bound_inputs(self):
        original = deepcopy(self.core.meta["input_snapshot"])
        for team in ("BOS", "NYK"):
            Path(self.store._series_path("NBA", team)).unlink()
            Path(self.store._baseline_path("NBA", team)).unlink()
        await self.persist()
        self.assertEqual(self.ledger.load_prediction_inputs("NBA", "synthetic-target"), original)

    async def test_inconsistent_aggregate_cannot_claim_captured_inputs(self):
        baseline = self.store.get("NBA", "BOS")
        baseline.pts_for += 10
        self.store.put(baseline)
        self.core = await self.engine.run_prematch(self.request)
        self.assertEqual(self.core.meta["input_snapshot_status"], "UNAVAILABLE")
        self.assertEqual(self.core.meta["data_quality"], "UNVERIFIED_BASELINE")
        with self.assertRaisesRegex(ValueError, "original input snapshot"):
            await self.persist()
        self.assert_no_prediction()

    async def test_retained_older_games_do_not_expand_the_aggregate_input_window(self):
        now = int(time.time())
        for team in ("BOS", "NYK"):
            for i in range(6):
                self.store.append_game("NBA", team, 90, 80, 95, True,
                    ts_utc=now-(i+20)*86400, game_id=f"older-{team}-{i}",
                    source="SYNTHETIC_TEST_PROVIDER", timestamp_precision="exact")
        self.core = await self.engine.run_prematch(self.request)
        self.assertEqual(self.core.meta["input_snapshot_status"], "CAPTURED")
        self.assertEqual(self.core.meta["data_quality"], "VERIFIED_BASELINE")
        await self.persist()
        stored = self.ledger.load_prediction_inputs("NBA", "synthetic-target")
        for team in stored["payload"]["teams"].values():
            self.assertEqual(len(team["records"]), 6)
            self.assertTrue(all(not row["game_id"].startswith("older-") for row in team["records"]))

    async def test_tampered_snapshot_is_rejected_before_any_write(self):
        self.core.meta["input_snapshot"]["payload"]["teams"]["home"]["records"][0]["pts_for"] += 1
        with self.assertRaisesRegex(ValueError, "integrity"):
            await self.persist()
        self.assert_no_prediction()

    async def test_recomputed_hash_cannot_hide_changed_scores(self):
        snapshot = self.core.meta["input_snapshot"]
        snapshot["payload"]["teams"]["home"]["records"][0]["pts_for"] += 10
        snapshot["sha256"] = digest(snapshot["payload"])
        with self.assertRaisesRegex(ValueError, "expected_home"):
            await self.persist()
        self.assert_no_prediction()

    async def test_post_prediction_capture_is_rejected(self):
        snapshot = self.core.meta["input_snapshot"]
        snapshot["payload"]["teams"]["home"]["captured_at_utc"] = self.core.meta["generated_at"] + 1
        snapshot["sha256"] = digest(snapshot["payload"])
        with self.assertRaisesRegex(ValueError, "unavailable before prediction"):
            await self.persist()
        self.assert_no_prediction()

    async def test_same_means_do_not_allow_replacing_original_input_games(self):
        await self.persist()
        original = self.ledger.load_prediction_inputs("NBA", "synthetic-target")
        snapshot = self.core.meta["input_snapshot"]
        rows = snapshot["payload"]["teams"]["home"]["records"]
        rows[0]["pts_for"] += 1
        rows[1]["pts_for"] -= 1
        snapshot["sha256"] = digest(snapshot["payload"])
        with self.assertRaisesRegex(ValueError, "input snapshot already differs"):
            await self.persist()
        self.assertEqual(self.ledger.load_prediction_inputs("NBA", "synthetic-target"), original)

    async def test_existing_prediction_cannot_receive_posthoc_inputs(self):
        record_verified_prematch_projection(self.ledger, league="NBA", fixture_id="synthetic-target",
            provider="ESPN", provider_fixture_id="synthetic-target", tipoff_utc=self.tipoff,
            prediction_utc=self.core.meta["generated_at"], expected_home=self.core.meta["expected_home"],
            expected_away=self.core.meta["expected_away"])
        with self.assertRaisesRegex(ValueError, "Cannot backfill"):
            await self.persist()
        self.assertIsNone(self.ledger.load_prediction_inputs("NBA", "synthetic-target"))
        self.assertEqual(self.ledger.audit_prediction_inputs("NBA")["missing"], 1)

    async def test_input_insert_failure_rolls_back_prediction_and_provenance(self):
        self.ledger.audit_provenance("NBA")
        with self.ledger._connect() as db:
            db.execute("""CREATE TRIGGER fail_inputs BEFORE INSERT ON prediction_inputs
                          BEGIN SELECT RAISE(ABORT, 'synthetic storage failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            await self.persist()
        self.assert_no_prediction()
        with self.ledger._connect() as db:
            for table in ("fixture_starts", "fixture_provenance"):
                self.assertEqual(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)

    async def test_sqlite_tampering_is_detected_on_replay(self):
        await self.persist()
        snapshot = self.ledger.load_prediction_inputs("NBA", "synthetic-target")
        snapshot["payload"]["expected_home"] += 10
        with self.ledger._connect() as db:
            db.execute("UPDATE prediction_inputs SET snapshot_json=?", (json.dumps(snapshot),))
        with self.assertRaisesRegex(ValueError, "integrity"):
            self.ledger.load_prediction_inputs("NBA", "synthetic-target")
        self.assertEqual(self.ledger.audit_prediction_inputs("NBA")["invalid"], 1)

    async def test_rehashed_same_start_collision_cannot_enter_ledger(self):
        snapshot = self.core.meta["input_snapshot"]
        rows = snapshot["payload"]["teams"]["home"]["records"]
        rows[-1]["ts_utc"] = rows[0]["ts_utc"]
        snapshot["sha256"] = digest(snapshot["payload"])
        with self.assertRaisesRegex(ValueError, "same-team fixture start"):
            await self.persist()
        self.assert_no_prediction()


if __name__ == "__main__":
    unittest.main()

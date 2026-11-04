"""Offline synthetic future fixtures with real-code FAZ13 and SQLite transaction checks."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import time
from uuid import uuid5, NAMESPACE_URL
from unittest.mock import AsyncMock, patch
import unittest
from zoneinfo import ZoneInfo

from baseline.team_baseline_store import TeamBaselineStore, TeamBaseline
from bound_backtest_report import report_bound
from euroleague_prematch_orchestrator import persist_resolved_euroleague_prematch
from faz13_engine import Faz13Engine, PrematchRequest
from prediction_inputs import canonical_json, digest
from prediction_ledger import PredictionLedger, PredictionRecord
from prematch_ledger_bridge import record_verified_prematch_projection
from providers.euroleague_fixture_evidence import capture_fixture_evidence
from providers.euroleague_live import BASE, EuroleagueLiveAdapter
from test_euroleague_live import source
from test_euroleague_baseline_binding import observation, values


NOW = int(datetime(2026, 11, 4, 18, tzinfo=timezone.utc).timestamp())


class EuroleaguePrematchBindingTests(unittest.IsolatedAsyncioTestCase):
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
            aggregate = self.store.compute_dynamic_baseline("EUROLEAGUE", team, 6)
            self.store.put(TeamBaseline(league="EUROLEAGUE", team=team, updated_ts=NOW, **aggregate))
        self.tipoff = NOW+86400
        self.day = datetime.fromtimestamp(self.tipoff, ZoneInfo("Europe/Istanbul")).date().isoformat()
        self.engine = Faz13Engine("", "https://example.invalid", baseline_store=self.store)
        self.engine.espn = None
        self.core = await self.engine.run_prematch(PrematchRequest(0, "EUROLEAGUE", self.day, "RED", "ZAL"))
        self.ledger = PredictionLedger(str(Path(self.folder.name) / "research.sqlite"))
        self.raw = source()["game"]
        self.raw.update(id=str(uuid5(NAMESPACE_URL, "synthetic-future-EuroLeague")), gameCode=9001,
            identifier="E2026_9001", played=False,
            utcDate=datetime.fromtimestamp(self.tipoff, timezone.utc).isoformat())
        for side in ("local", "road"):
            self.raw[side]["score"] = 0
            self.raw[side]["partials"] = dict(partials1=0, partials2=0, partials3=0, partials4=0, extraPeriods={})
        self.url = f"{BASE}/E/seasons/E2026/games/9001"
        fixture = source()
        self.responses = {f"{BASE}/E": fixture["competition"], f"{BASE}/E/seasons/E2026": fixture["season"],
            f"{BASE}/E/seasons/E2026/games": dict(total=1, data=[deepcopy(self.raw)]), self.url: deepcopy(self.raw)}
        self.adapter = EuroleagueLiveAdapter()
        self.adapter._get_json = AsyncMock(side_effect=lambda url: deepcopy(self.responses.get(url)))

    async def persist(self, year=2026):
        return await persist_resolved_euroleague_prematch(
            adapter=self.adapter, ledger=self.ledger, core=self.core, year=year)

    def assert_no_rows(self):
        with self.ledger._connect() as db:
            for table in ("predictions", "prediction_inputs", "fixture_observations"):
                self.assertEqual(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)

    async def test_real_engine_inputs_and_fixture_persist_together_under_actual_provider(self):
        result = await self.persist()
        self.assertTrue(result["inserted"])
        fixture = self.ledger.load_fixture_observation("EUROLEAGUE", "E2026_9001")
        self.assertEqual(fixture["payload"]["fixture"]["home_team_id"], "RED")
        with self.ledger._connect() as db:
            self.assertEqual(db.execute("SELECT provider, provider_fixture_id FROM fixture_provenance").fetchone(),
                             ("EUROLEAGUE_LIVE", "E2026_9001"))
        with self.assertRaises(ValueError):
            report_bound(self.ledger.db_path, "EUROLEAGUE")  # NBA evaluator is not silently reused.

    async def test_pruned_baselines_and_post_tipoff_reads_replay_original_evidence(self):
        await self.persist()
        original = self.ledger.load_fixture_observation("EUROLEAGUE", "E2026_9001")
        for team in ("RED", "ZAL"):
            Path(self.store._series_path("EUROLEAGUE", team)).unlink()
            Path(self.store._baseline_path("EUROLEAGUE", team)).unlink()
        self.clock.return_value = self.tipoff+3600
        reopened = PredictionLedger(self.ledger.db_path)
        self.assertEqual(reopened.load_fixture_observation("EUROLEAGUE", "E2026_9001"), original)
        self.assertIsNotNone(reopened.load_prediction_inputs("EUROLEAGUE", "E2026_9001"))

    async def test_later_identical_fixture_observation_does_not_replace_first(self):
        await self.persist()
        original = self.ledger.load_fixture_observation("EUROLEAGUE", "E2026_9001")
        self.clock.return_value = NOW+30
        repeated = await self.persist()
        self.assertFalse(repeated["inserted"])
        self.assertEqual(repeated["fixture_observation_sha256"], original["sha256"])
        self.assertEqual(self.ledger.load_fixture_observation("EUROLEAGUE", "E2026_9001"), original)

    async def test_live_or_scored_fixture_cannot_be_saved_as_prematch(self):
        for field in ("played", "score"):
            detail = deepcopy(self.raw)
            if field == "played":
                detail["played"] = True
            else:
                detail["local"]["score"] = 1
            self.responses[self.url] = detail
            with self.assertRaises(ValueError):
                await self.persist()
            self.assert_no_rows()

    async def test_no_post_tipoff_insertion_or_future_dated_projection(self):
        self.clock.return_value = self.tipoff
        with self.assertRaises(ValueError):
            await self.persist()
        self.assert_no_rows()
        self.clock.return_value = NOW
        self.core.meta["generated_at"] = NOW+1
        with self.assertRaisesRegex(ValueError, "future-dated"):
            await self.persist()

    async def test_wrong_day_or_swapped_teams_have_no_matching_fixture(self):
        for home, away, day in (("ZAL", "RED", self.day), ("RED", "ZAL", "2026-11-06")):
            self.core = await self.engine.run_prematch(PrematchRequest(0, "EUROLEAGUE", day, home, away))
            with self.assertRaisesRegex(ValueError, "Unique matching"):
                await self.persist()
            self.assert_no_rows()

    async def test_catalog_detail_start_disagreement_is_rejected(self):
        self.responses[self.url]["utcDate"] = datetime.fromtimestamp(self.tipoff+3600, timezone.utc).isoformat()
        with self.assertRaisesRegex(ValueError, "catalog and detail"):
            await self.persist()
        self.assert_no_rows()

    async def test_ambiguous_catalog_does_not_choose_a_fixture(self):
        another = deepcopy(self.raw)
        another.update(identifier="E2026_9002", gameCode=9002, id=str(uuid5(NAMESPACE_URL, "synthetic-second-fixture")))
        self.responses[f"{BASE}/E/seasons/E2026/games"] = dict(total=2, data=[self.raw, another])
        with self.assertRaisesRegex(ValueError, "Unique matching"):
            await self.persist()
        self.assert_no_rows()

    async def test_unavailable_catalog_has_no_stale_schedule_fallback(self):
        self.adapter._get_json.side_effect = None
        self.adapter._get_json.return_value = None
        with self.assertRaises(RuntimeError):
            await self.persist()
        self.assert_no_rows()

    async def test_missing_snapshot_and_unbound_metadata_are_rejected(self):
        original = deepcopy(self.core)
        for key, value in (("input_snapshot", None), ("home_baseline_games", 7), ("home_sources", ["MANUAL_BASELINE"])):
            self.core = deepcopy(original)
            self.core.meta[key] = value
            with self.assertRaises(ValueError):
                await self.persist()
            self.assert_no_rows()

    async def test_altered_scores_and_averages_are_rejected(self):
        original = deepcopy(self.core)
        for field in ("expected_home", "expected_total", "average"):
            self.core = deepcopy(original)
            if field == "average":
                self.core.home_avg.points_for += 2
            else:
                self.core.meta[field] += 2
            with self.assertRaises(ValueError):
                await self.persist()
            self.assert_no_rows()

    async def test_different_input_season_is_rejected_even_with_same_means(self):
        snapshot = self.core.meta["input_snapshot"]
        for side, home in (("home", True), ("away", False)):
            snapshot["payload"]["teams"][side]["records"] = [values(observation(year=2025, code=i)[1], home=home)
                                                              for i in range(1, 7)]
        snapshot["sha256"] = digest(snapshot["payload"])
        with self.assertRaisesRegex(ValueError, "different source or season"):
            await self.persist()
        self.assert_no_rows()

    async def test_unknown_input_provider_cannot_inherit_euroleague_identity(self):
        snapshot = self.core.meta["input_snapshot"]
        for team in snapshot["payload"]["teams"].values():
            for row in team["records"]:
                row.update(source="SYNTHETIC_UNBOUND", pace_evidence=None)
        snapshot["sha256"] = digest(snapshot["payload"])
        with self.assertRaisesRegex(ValueError, "different source or season"):
            await self.persist()
        self.assert_no_rows()

    async def test_storage_failure_rolls_back_all_prediction_and_fixture_rows(self):
        self.ledger.audit_provenance("EUROLEAGUE")
        with self.ledger._connect() as db:
            db.execute("""CREATE TRIGGER fail_fixture BEFORE INSERT ON fixture_observations
                          BEGIN SELECT RAISE(ABORT, 'synthetic storage failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            await self.persist()
        self.assert_no_rows()
        with self.ledger._connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM fixture_starts").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM fixture_provenance").fetchone()[0], 0)

    async def test_posthoc_fixture_attachment_is_rejected(self):
        self.ledger.record_prediction(PredictionRecord("E2026_9001", "EUROLEAGUE", NOW,
            self.core.meta["expected_home"], self.core.meta["expected_away"], None))
        snapshot = self.core.meta["input_snapshot"]
        with self.ledger._connect() as db:
            db.execute("INSERT INTO prediction_inputs VALUES (?,?,?,?)",
                ("EUROLEAGUE", "E2026_9001", canonical_json(snapshot), snapshot["sha256"]))
        with self.assertRaisesRegex(ValueError, "Cannot backfill fixture"):
            await self.persist()
        self.assertIsNone(self.ledger.load_fixture_observation("EUROLEAGUE", "E2026_9001"))

    async def test_modified_stored_observation_is_rejected_on_read(self):
        await self.persist()
        record = self.ledger.load_fixture_observation("EUROLEAGUE", "E2026_9001")
        record["payload"]["raw_game"]["gameCode"] = 9002
        with self.ledger._connect() as db:
            db.execute("UPDATE fixture_observations SET observation_json=?", (json.dumps(record),))
        with self.assertRaises(ValueError):
            self.ledger.load_fixture_observation("EUROLEAGUE", "E2026_9001")

    async def test_stale_fixture_observation_cannot_certify_a_newer_prediction(self):
        old = capture_fixture_evidence(self.raw, year=2026, observed_at_utc=NOW-1)
        with self.assertRaisesRegex(ValueError, "identity/time mismatch"):
            record_verified_prematch_projection(self.ledger, league="EUROLEAGUE", fixture_id="E2026_9001",
                provider="EUROLEAGUE_LIVE", provider_fixture_id="E2026_9001", tipoff_utc=self.tipoff,
                prediction_utc=NOW, expected_home=77, expected_away=83,
                input_snapshot=self.core.meta["input_snapshot"], fixture_evidence=old)
        self.assert_no_rows()

    async def test_provider_gate_requires_euroleague_inputs_and_fixture(self):
        evidence = capture_fixture_evidence(self.raw, year=2026, observed_at_utc=NOW)
        for league in ("NBA", "EUROCUP"):
            with self.assertRaises(ValueError):
                record_verified_prematch_projection(self.ledger, league=league, fixture_id="E2026_9001",
                    provider="EUROLEAGUE_LIVE", provider_fixture_id="E2026_9001", tipoff_utc=self.tipoff,
                    prediction_utc=NOW, expected_home=77, expected_away=83,
                    input_snapshot=self.core.meta["input_snapshot"], fixture_evidence=evidence)
        self.clock.return_value = self.tipoff
        with self.assertRaisesRegex(ValueError, "already started"):
            record_verified_prematch_projection(self.ledger, league="EUROLEAGUE", fixture_id="E2026_9001",
                provider="EUROLEAGUE_LIVE", provider_fixture_id="E2026_9001", tipoff_utc=self.tipoff,
                prediction_utc=NOW, expected_home=77, expected_away=83,
                input_snapshot=self.core.meta["input_snapshot"], fixture_evidence=evidence)
        self.clock.return_value = NOW
        self.core.ctx.league = "EUROCUP"
        with self.assertRaisesRegex(ValueError, "EuroCup"):
            await self.persist()
        self.assert_no_rows()


if __name__ == "__main__":
    unittest.main()

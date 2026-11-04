"""FAZ23 snapshot provenance and persistence regression tests."""
import asyncio
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from faz23_engine import Faz23Engine


class Faz23SnapshotContractTests(unittest.TestCase):
    def test_unverified_snapshot_never_written(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "snapshots.sqlite")
            engine = Faz23Engine(storage_path=path)
            core = SimpleNamespace(meta={}, ctx=SimpleNamespace(
                date="2026-11-04", home="Home", away="Away", league="NBA"
            ), market={}, notes=[])
            for invalid_quality in (None, "", "   ", 123, [], {}):
                core.meta = {} if invalid_quality is None else {"data_quality": invalid_quality}
                with self.subTest(quality=invalid_quality), self.assertRaises(ValueError):
                    asyncio.run(engine.record_snapshot(core))
            with sqlite3.connect(path) as con:
                self.assertEqual(con.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0], 0)

    def test_latest_snapshot_per_fixture_deduplicates_calibration_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            engine = Faz23Engine(storage_path=str(Path(folder) / "snapshots.sqlite"))
            core = SimpleNamespace(
                meta={"data_quality": "VERIFIED_BASELINE", "expected_total": 200},
                ctx=SimpleNamespace(date="2026-11-04", home="Home", away="Away", league="NBA"),
                market={}, notes=[],
            )
            asyncio.run(engine.record_snapshot(core))
            core.meta = {"data_quality": "VERIFIED_BASELINE", "expected_total": 205}
            asyncio.run(engine.record_snapshot(core))
            core.ctx = SimpleNamespace(date="2026-11-04", home="Other", away="Away", league="NBA")
            asyncio.run(engine.record_snapshot(core))
            latest = engine.latest_snapshots_by_fixture()
            self.assertEqual(len(latest), 2)
            first = next(item for item in latest if ":Home:Away:" in item["fixture_key"])
            self.assertEqual(first["payload"]["meta"]["expected_total"], 205)
            with sqlite3.connect(engine.path) as con:
                self.assertEqual(con.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0], 3)

    def test_prematch_selection_excludes_post_tipoff_and_unknown_fixtures(self):
        with tempfile.TemporaryDirectory() as folder:
            engine = Faz23Engine(storage_path=str(Path(folder) / "snapshots.sqlite"))
            key = "2026-11-04:Home:Away:NBA"
            with sqlite3.connect(engine.path) as con:
                for ts, fixture_key, expected in (
                    (100, key, 200), (150, key, 202), (200, key, 204),
                    (250, key, 206), (120, "2026-11-04:Other:Away:NBA", 190),
                ):
                    con.execute(
                        "INSERT INTO snapshots(ts, fixture_key, payload) VALUES(?,?,?)",
                        (ts, fixture_key, json.dumps({"meta": {"expected_total": expected}})),
                    )
                con.commit()
            chosen = engine.prematch_snapshots_for_calibration({key: 200})
            self.assertEqual(len(chosen), 1)
            self.assertEqual(chosen[0]["ts"], 150)
            self.assertEqual(chosen[0]["payload"]["meta"]["expected_total"], 202)
            self.assertEqual(engine.prematch_snapshots_for_calibration({}), [])
            with self.assertRaises(ValueError):
                engine.prematch_snapshots_for_calibration({key: True})

    def test_verified_snapshot_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "snapshots.sqlite")
            engine = Faz23Engine(storage_path=path)
            core = SimpleNamespace(
                meta={"data_quality": "VERIFIED_BASELINE", "confidence_pct": 70},
                ctx=SimpleNamespace(date="2026-11-04", home="Home", away="Away", league="NBA"),
                market={}, notes=["verified"],
            )
            asyncio.run(engine.record_snapshot(core))
            with sqlite3.connect(path) as con:
                row = con.execute("SELECT fixture_key, payload FROM snapshots").fetchone()
            self.assertEqual(row[0], "2026-11-04:Home:Away:NBA")
            self.assertEqual(json.loads(row[1])["meta"]["data_quality"], "VERIFIED_BASELINE")


if __name__ == "__main__":
    unittest.main()

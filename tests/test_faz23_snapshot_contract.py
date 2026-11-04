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

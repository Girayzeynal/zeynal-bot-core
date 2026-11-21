"""Archive census must never count model versions as additional fixtures."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from core.team_identity import digest
from hybrid_engine.archive_census import census, sqlite_report


class ArchiveCensusTests(unittest.TestCase):
    def test_read_only_sqlite_legacy_and_models(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"nba-hybrid.sqlite"
            with sqlite3.connect(path) as db:
                db.executescript("""
                    CREATE TABLE live_analysis_snapshots
                        (league TEXT,fixture_id TEXT,model_digest TEXT,created_utc INTEGER,
                        payload TEXT,sha256 TEXT);
                    CREATE TABLE live_analysis_commit_receipts
                        (league TEXT,fixture_id TEXT,model_digest TEXT,
                        snapshot_sha256 TEXT,completed_utc INTEGER);
                    CREATE TABLE predictions (league TEXT,fixture_id TEXT,
                        prediction_ts_utc INTEGER);
                    CREATE TABLE prediction_versions (league TEXT,fixture_id TEXT,
                        version_id INTEGER,prediction_ts_utc INTEGER);
                    CREATE TABLE verified_analysis_results
                        (league TEXT,fixture_id TEXT,scope TEXT);
                """)
                for fixture,model,committed in [("a","one",True),("a","two",True),("b","one",False)]:
                    db.execute("INSERT INTO live_analysis_snapshots VALUES(?,?,?,?,?,?)",
                        ("NBA",fixture,model,1000,"{}","pin"))
                    if committed:
                        db.execute("INSERT INTO live_analysis_commit_receipts VALUES(?,?,?,?,?)",
                            ("NBA",fixture,model,"pin",1002))
                db.executemany("INSERT INTO predictions VALUES(?,?,?)",
                    [("NBA","a",800),("NBA","old",900)])
                db.executemany("INSERT INTO prediction_versions VALUES(?,?,?,?)",
                    [("NBA","old",1,800),("NBA","old",2,900)])
                db.execute("INSERT INTO verified_analysis_results VALUES(?,?,?)",
                    ("NBA","a","REGULATION_ONLY"))
            before=path.read_bytes()
            result=sqlite_report(path)
            self.assertEqual(before,path.read_bytes())
            fresh=result["sources"]["verified_live"]
            self.assertEqual((fresh["NBA"]["unique_fixtures"],fresh["NBA"]["unique_model_forecasts"]), (1,2))
            self.assertEqual((fresh["committed_snapshots"],fresh["missing_commit_receipt"]),(2,1))
            self.assertEqual(fresh["verified_result_fixture_counts"]["NBA"],1)
            self.assertEqual(result["sources"]["legacy_first"]["NBA"]["unique_fixtures"],2)
            self.assertEqual(result["sources"]["legacy_versions"]["NBA"]["unique_fixtures"],1)
            self.assertEqual(result["sources"]["legacy_versions"]["count"],2)

    def test_europe_counts_first_publication_once(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"data"
            directory=root/"europe"/"euroleague"
            directory.mkdir(parents=True)
            forecast=dict(fixture=dict(canonical_id="match1",start_ts_utc=2000),
                version="M1")
            sha=digest(forecast)
            (directory/("forecast-"+sha+".json")).write_text(json.dumps(forecast))
            pub=dict(forecast=dict(file="forecast-"+sha+".json",sha256=sha),
                first_archived_at_utc=1200,classification="PREMATCH")
            (directory/"first-first.json").write_text(json.dumps(dict(payload=pub,sha256=digest(pub))))
            result=census(root)
            report=result["european_original_publications"]["EUROLEAGUE"]
            self.assertEqual(report["unique_fixtures"],1)
            self.assertEqual(report["unique_model_forecasts"],1)
            self.assertEqual(report["invalid_or_unsupported"],0)
            self.assertEqual(result["nba_sqlite"]["status"],"NOT_PRESENT")
            self.assertEqual(result["scope"],"THIS_LOCAL_INSTALLATION_ONLY__NOT_REMOTE_FLY_PRODUCTION")

    def test_no_empty_database_created(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"missing.sqlite"
            self.assertEqual(sqlite_report(path)["status"],"NOT_PRESENT")
            self.assertFalse(path.exists())


if __name__=="__main__":
    unittest.main()

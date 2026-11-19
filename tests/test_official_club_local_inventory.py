"""No-network local identity inventory: partial scan honest + immutable SQLite."""
import json
import sqlite3
import time

from hybrid_engine import official_club_local_inventory as inv
from core.league_identity import resolve_league
from core.team_identity import digest,internal_team_id


def _participants():
    now=int(time.time())
    spec=resolve_league("NBA")
    pid="7"
    part=dict(
        internal_id=internal_team_id(spec.identity_namespace,pid),
        provider="ESPN",provider_id=pid,
        official_name="Denver Nuggets",aliases=[])
    p=dict(format="SEASON_PARTICIPANTS_V1",league_id="NBA",
           year=2026,season_id="2026/2027",
           observed_at_utc=now-180,ingested_at_utc=now-140,
           participant_count=1,participants=[part],
           source_pins={},
           membership_basis="SEASON_PARTICIPANT_ENDPOINT_NOT_GAME_SAMPLES",
           source_attestation="LOCAL_HASH_NOT_INDEPENDENT_ATTESTATION")
    return dict(payload=p,sha256=digest(p))


def test_more_than_500_unrelated_json_files_does_not_hide_priority_named_snapshot(tmp_path):
    root=tmp_path/"isolated"
    root.mkdir()
    clutter=root/"aaa-ledger"
    clutter.mkdir()
    for n in range(550):
        (clutter/f"{n:04d}-forecast.json").write_text('{"unrelated": true}')
    folder=root/"zz-season"
    folder.mkdir()
    (folder/"season_participants_2026.json").write_text(json.dumps(_participants()))
    report=inv.inspect_local_source_inventory(root=root)
    assert report["json_files_enumerated"]==551
    assert report["scanned_json_files"]==551
    assert not report["scan_capped"]
    assert report["status"]=="LOCAL_IDENTITY_SOURCE_CANDIDATES_UNVERIFIED"
    assert report["candidate_files"][0]["relative_path"]=="zz-season/season_participants_2026.json"
    assert report["snapshot_sha_independently_pinned"] is False
    assert report["requests"]==0
    assert report["model_input"] is False


def test_partial_json_scan_is_explicit_incomplete_not_no_data(tmp_path,monkeypatch):
    root=tmp_path/"isolated"
    root.mkdir()
    for n in range(4):
        (root/f"{n:02d}-unrelated.json").write_text('{"row": 1}')
    monkeypatch.setattr(inv,"MAX_JSON_READS",2)
    report=inv.inspect_local_source_inventory(root=root)
    assert report["scan_capped"] is True
    assert "JSON_CANDIDATE_READ_LIMIT" in report["scan_cap_reasons"]
    assert report["status"]=="LOCAL_IDENTITY_SCAN_INCOMPLETE_NO_MATCH"
    assert report["json_files_enumerated"]==4
    assert report["scanned_json_files"]==2
    assert report["requests"]==0


def test_readonly_sqlite_schema_catalog_catches_existing_database_without_rows(tmp_path):
    root=tmp_path/"isolated"
    folder=root/"live-nba"
    folder.mkdir(parents=True)
    database=folder/"nba-hybrid.sqlite"
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE team_identity_audit(id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO team_identity_audit(value) VALUES ('private payload')")
        conn.execute("CREATE TABLE other_events(id INTEGER PRIMARY KEY)")
    before=database.read_bytes()
    report=inv.inspect_local_source_inventory(root=root)
    after=database.read_bytes()
    assert before==after
    assert report["sqlite_files_enumerated"]==1
    assert report["sqlite_files_inspected"]==1
    assert report["sqlite_database_paths"]==["live-nba/nba-hybrid.sqlite"]
    assert report["sqlite_schema_candidates"][0]["relative_path"]=="live-nba/nba-hybrid.sqlite"
    assert report["sqlite_schema_candidates"][0]["table_names"]==["team_identity_audit"]
    assert report["status"]=="LOCAL_IDENTITY_SOURCE_CANDIDATES_UNVERIFIED"
    assert report["requests"]==0
    assert report["model_input"] is False
    assert report["historical_pregame_proof"] is False
    assert "private payload" not in json.dumps(report)


def test_sqlite_with_only_generic_tables_listed_but_not_falsely_proven_identity(tmp_path):
    root=tmp_path/"isolated"
    root.mkdir()
    with sqlite3.connect(root/"results.sqlite") as conn:
        conn.execute("CREATE TABLE prediction_ledger(id INTEGER PRIMARY KEY)")
    report=inv.inspect_local_source_inventory(root=root)
    assert report["sqlite_files_inspected"]==1
    assert report["sqlite_database_paths"]==["results.sqlite"]
    assert report["sqlite_schema_candidates"]==[]
    assert report["status"]=="NO_IDENTITY_SOURCE_FOUND_IN_SCANNED_LOCAL_SCOPE"
    assert report["snapshot_sha_independently_pinned"] is False


def test_external_symlink_not_inspected(tmp_path):
    outside=tmp_path/"external.sqlite"
    with sqlite3.connect(outside) as conn:
        conn.execute("CREATE TABLE team_identity(id INTEGER PRIMARY KEY)")
    root=tmp_path/"isolated"
    root.mkdir()
    (root/"pretend.sqlite").symlink_to(outside)
    report=inv.inspect_local_source_inventory(root=root)
    assert report["sqlite_files_inspected"]==0
    assert report["sqlite_schema_candidates"]==[]
    assert report["requests"]==0


def test_excess_sqlite_schema_files_reports_limit_not_no_matches(tmp_path,monkeypatch):
    root=tmp_path/"isolated"
    root.mkdir()
    for n in range(4):
        with sqlite3.connect(root/f"{n}.db") as conn:
            conn.execute("CREATE TABLE ledger(id INTEGER PRIMARY KEY)")
    monkeypatch.setattr(inv,"MAX_SQLITE_INSPECTED",2)
    report=inv.inspect_local_source_inventory(root=root)
    assert report["scan_capped"]
    assert "SQLITE_SCHEMA_FILE_LIMIT" in report["scan_cap_reasons"]
    assert report["status"]=="LOCAL_IDENTITY_SCAN_INCOMPLETE_NO_MATCH"
    assert report["sqlite_files_inspected"]==2


def test_root_absent_is_not_exhaustive_no_identity_proof(tmp_path):
    report=inv.inspect_local_source_inventory(root=tmp_path/"missing")
    assert report["status"]=="LOCAL_ISOLATED_DATA_ROOT_UNAVAILABLE"
    assert report["historical_pregame_proof"] is False
    assert report["requests"]==0


def test_targeted_db_schema_reports_snapshot_columns_only_and_preserves_bytes(tmp_path):
    root=tmp_path/"isolated"
    (root/"live-nba").mkdir(parents=True)
    path_a=root/"faz23_storage.sqlite"
    path_b=root/"live-nba"/"nba-hybrid.sqlite"
    with sqlite3.connect(path_a) as conn:
        conn.execute("CREATE TABLE snapshots(id INTEGER PRIMARY KEY, ts INTEGER, fixture_key TEXT, payload TEXT)")
        conn.execute("INSERT INTO snapshots(ts,fixture_key,payload) VALUES (1,'fixture',?)",
                     ("SENSITIVE_PRIVATE_ROW",))
    with sqlite3.connect(path_b) as conn:
        conn.execute("CREATE TABLE live_analysis_snapshots(league TEXT,fixture_id TEXT,model_digest TEXT,created_utc INTEGER,payload TEXT,sha256 TEXT)")
        conn.execute("INSERT INTO live_analysis_snapshots(league,fixture_id,model_digest,created_utc,payload,sha256) VALUES ('NBA','fixture','model',1,?,?)",
                     ("SENSITIVE_PRIVATE_ROW","f"*64))
    before_a,before_b=path_a.read_bytes(),path_b.read_bytes()
    report=inv.inspect_known_database_columns(root=root)
    assert path_a.read_bytes()==before_a
    assert path_b.read_bytes()==before_b
    assert report["status"]=="KNOWN_LOCAL_SCHEMAS_OBSERVED_NOT_IDENTITY_VALIDATED"
    assert len(report["inspected_tables"])==2
    assert report["inspected_tables"][0]["table"]=="snapshots"
    assert [x["name"] for x in report["inspected_tables"][0]["columns"]]==[
        "id","ts","fixture_key","payload"]
    assert report["inspected_tables"][1]["table"]=="live_analysis_snapshots"
    assert report["inspected_tables"][1]["contains_opaque_payload_column"] is True
    assert report["direct_provider_team_id_column_found"] is False
    assert report["extracted_records"]==0
    assert report["requests"]==0
    assert report["model_input"] is False
    assert "SENSITIVE_PRIVATE_ROW" not in json.dumps(report)
    assert report["sqlite_inspection_mode"]=="READ_ONLY_IMMUTABLE_SCHEMA_ONLY_WAL_NOT_INCLUDED"


def test_targeted_db_schema_absent_does_not_invent_identity(tmp_path):
    root=tmp_path/"isolated"
    root.mkdir()
    report=inv.inspect_known_database_columns(root=root)
    assert report["inspected_tables"]==[]
    assert len(report["unavailable_targets"])==3
    assert report["status"]=="NO_KNOWN_SQLITE_SCHEMAS_OBSERVED"
    assert report["participant_identity_verified"] is False
    assert report["requests"]==0


def test_targeted_db_schema_skips_symlinks_and_other_tables(tmp_path):
    root=tmp_path/"isolated"
    root.mkdir()
    outside=tmp_path/"outside.sqlite"
    with sqlite3.connect(outside) as conn:
        conn.execute("CREATE TABLE snapshots(provider_team_id TEXT)")
    (root/"faz23_storage.sqlite").symlink_to(outside)
    report=inv.inspect_known_database_columns(root=root)
    assert not report["inspected_tables"]
    assert report["direct_provider_team_id_column_found"] is False
    assert report["unavailable_targets"][0]["reason"]=="MISSING_OR_SYMLINK"


def test_old_faz23_and_live_analysis_snapshots_are_forecast_not_team_identity(tmp_path):
    root=tmp_path/"isolated"
    (root/"live-nba").mkdir(parents=True)
    with sqlite3.connect(root/"faz23_storage.sqlite") as conn:
        conn.execute("CREATE TABLE snapshots(id INTEGER PRIMARY KEY,fixture_key TEXT,payload TEXT)")
    with sqlite3.connect(root/"live-nba"/"nba-hybrid.sqlite") as conn:
        conn.execute("CREATE TABLE live_analysis_snapshots(league TEXT,fixture_id TEXT,model_digest TEXT,payload TEXT,sha256 TEXT)")
    report=inv.inspect_local_source_inventory(root=root)
    assert report["sqlite_files_inspected"]==2
    assert report["scan_capped"] is False
    assert report["status"]=="LOCAL_FORECAST_SCHEMAS_ONLY_NOT_IDENTITY_SOURCE"
    assert all(x["schema_role"]=="FORECAST_SNAPSHOT_SCHEMA_ONLY"
               for x in report["sqlite_schema_candidates"])
    assert report["snapshot_sha_independently_pinned"] is False
    assert report["requests"]==0
    assert report["model_input"] is False


def test_forecast_only_sqlite_and_capped_json_is_still_incomplete(tmp_path,monkeypatch):
    root=tmp_path/"isolated"
    root.mkdir()
    with sqlite3.connect(root/"faz23_storage.sqlite") as conn:
        conn.execute("CREATE TABLE snapshots(id INTEGER PRIMARY KEY,payload TEXT)")
    for i in range(4):
        (root/f"other-{i}.json").write_text('{"just":"irrelevant"}')
    monkeypatch.setattr(inv,"MAX_JSON_READS",2)
    report=inv.inspect_local_source_inventory(root=root)
    assert report["scan_capped"] is True
    assert report["status"]=="LOCAL_IDENTITY_SCAN_INCOMPLETE_NO_MATCH"
    assert report["sqlite_schema_candidates"][0]["schema_role"]=="FORECAST_SNAPSHOT_SCHEMA_ONLY"

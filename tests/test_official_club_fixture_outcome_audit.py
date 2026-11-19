"""Synthetic, isolated read-only NBA native source final replay contracts."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import sqlite3

from core.team_identity import digest
from hybrid_engine import official_club_fixture_outcome_audit as audit

START=int(datetime(2026,10,25,23,tzinfo=timezone.utc).timestamp())
CREATED=START-1200
MODEL="c"*64
PROVIDER_EVENT="401000123"


def native_event():
    status={"type":{"state":"post","completed":True,"name":"STATUS_FINAL"}}
    competitors=[]
    for side,tid,values in [
        ("home","7",[25,30,30,30]),("away","3",[25,28,28,28])]:
        competitors.append(dict(
            homeAway=side,team={"id":tid},score=str(sum(values)),
            linescores=[{"value":v} for v in values]))
    return dict(
        id=PROVIDER_EVENT,date="2026-10-25T23:00:00Z",
        season={"year":2027,"type":2},
        status=deepcopy(status),
        competitions=[dict(id=PROVIDER_EVENT,status=status,
                           competitors=competitors)])


def frozen():
    identity=dict(provider="ESPN",league="NBA",season_start_year=2026,
                  start_ts_utc=START,home_team_id="7",away_team_id="3")
    return dict(
        record_type="LIVE_PREMATCH_PREDICTION",
        league="NBA",season="2026/2027",fixture_id=digest(identity),
        model_digest=MODEL,model_version="EXACT_FROZEN_TEST",
        scope="REGULATION_ONLY",fixture_start_utc=START,
        record_deadline_utc=START-200,
        created_at_utc=CREATED,cutoff_utc=CREATED,
        prediction_generated_at_utc=CREATED,
        home=dict(provider_id="7"),away=dict(provider_id="3"),
        provider_fixture_ids=[PROVIDER_EVENT],
        evaluation_class="LIVE_RECORDED",actual=None,
        prediction=dict(home=116.2,away=106.1),
        input_clocks=[
            dict(observed_at_utc=CREATED-90,ingested_at_utc=CREATED-30)])


def final(p):
    event=native_event()
    return dict(
        record_type="VERIFIED_FINAL_RESULT",league="NBA",
        fixture_id=p["fixture_id"],scope="REGULATION_ONLY",
        actual=[115,109],final_with_ot=[115,109],
        periods=dict(home=[25,30,30,30],away=[25,28,28,28]),
        source_catalog_sha256="e"*64,
        observed_at_utc=START+15000,ingested_at_utc=START+15100,
        source_fixture=[event],source_fixture_sha256=digest([event]))


def ledger(tmp_path, *, valid_final=True):
    root=tmp_path/"isolated"
    folder=root/"live-nba"
    folder.mkdir(parents=True)
    file=folder/"nba-hybrid.sqlite"
    with sqlite3.connect(file) as db:
        db.execute("""CREATE TABLE live_analysis_snapshots
            (league TEXT, fixture_id TEXT, model_digest TEXT, created_utc INTEGER,
             payload TEXT, sha256 TEXT,PRIMARY KEY(league,fixture_id,model_digest))""")
        db.execute("""CREATE TABLE live_analysis_commit_receipts
            (league TEXT,fixture_id TEXT,model_digest TEXT,
             snapshot_sha256 TEXT,completed_utc INTEGER,
             PRIMARY KEY(league,fixture_id,model_digest))""")
        db.execute("""CREATE TABLE verified_analysis_results
            (league TEXT,fixture_id TEXT,scope TEXT,payload TEXT,sha256 TEXT,
             PRIMARY KEY(league,fixture_id,scope))""")
    p=frozen()
    with sqlite3.connect(file) as db:
        db.execute("INSERT INTO live_analysis_snapshots VALUES(?,?,?,?,?,?)",
                   ("NBA",p["fixture_id"],MODEL,CREATED,
                    json.dumps(p,sort_keys=True),digest(p)))
        db.execute("INSERT INTO live_analysis_commit_receipts VALUES(?,?,?,?,?)",
                   ("NBA",p["fixture_id"],MODEL,digest(p),CREATED+2))
        if valid_final:
            r=final(p)
            db.execute("INSERT INTO verified_analysis_results VALUES(?,?,?,?,?)",
                       ("NBA",p["fixture_id"],"REGULATION_ONLY",
                        json.dumps(r,sort_keys=True),digest(r)))
    return root,file,p


def test_valid_local_espn_final_replays_with_frozen_fixture_identity_readonly(tmp_path):
    root,file,p=ledger(tmp_path)
    before=file.read_bytes()
    r=audit.inspect_local_nba_final_fixture_links(root=root)
    assert r["status"]=="LOCAL_FINAL_SOURCE_REPLAY_MATCHES_NOT_EXTERNALLY_ATTESTED"
    assert r["candidate_rows"]==1
    assert r["consistent_frozen_snapshots"]==1
    assert r["local_native_fixture_identity_matches"]==1
    assert r["local_final_source_replays"]==1
    assert r["final_outcomes_missing"]==0
    assert r["invalid_final_source_replays"]==0
    assert r["requests"]==0
    assert r["records_exported"]==0
    assert r["model_input"] is False
    assert r["archives_modified"] is False
    assert r["historical_pregame_source_proof"] is False
    assert r["official_external_fixture_identity_verified"] is False
    assert r["player_identity_verified"] is False
    assert r["verified_fixture_examples"][0]["fixture_id"]==p["fixture_id"]
    assert r["verified_fixture_examples"][0]["provider_fixture_ids"]==[PROVIDER_EVENT]
    assert r["verified_fixture_examples"][0]["source_catalog_sha256"]=="e"*64
    assert "116.2" not in json.dumps(r)  # Forecast numbers stay hidden.
    assert file.read_bytes()==before


def test_no_final_outcomes_does_not_pretend_to_have_a_source_replay(tmp_path):
    root,file,p=ledger(tmp_path,valid_final=False)
    r=audit.inspect_local_nba_final_fixture_links(root=root)
    assert r["status"]=="NO_LOCALLY_STORED_FINAL_EVENTS_FOR_CONSISTENT_FORECASTS"
    assert r["consistent_frozen_snapshots"]==1
    assert r["final_outcomes_missing"]==1
    assert r["local_final_source_replays"]==0
    assert r["official_external_fixture_identity_verified"] is False


def test_final_source_sha_mismatch_abstains(tmp_path):
    root,file,p=ledger(tmp_path)
    with sqlite3.connect(file) as db:
        original=json.loads(db.execute(
            "SELECT payload FROM verified_analysis_results").fetchone()[0])
        original["source_fixture_sha256"]="9"*64
        db.execute("UPDATE verified_analysis_results SET payload=?,sha256=?",
                   (json.dumps(original,sort_keys=True),digest(original)))
    r=audit.inspect_local_nba_final_fixture_links(root=root)
    assert r["status"]=="ABSTAIN_FIXTURE_OR_LOCAL_SOURCE_CONFLICT"
    assert r["invalid_final_source_replays"]==1
    assert r["local_final_source_replays"]==0


def test_locally_rehashed_but_wrong_native_event_team_abstains(tmp_path):
    root,file,p=ledger(tmp_path)
    with sqlite3.connect(file) as db:
        original=json.loads(db.execute(
            "SELECT payload FROM verified_analysis_results").fetchone()[0])
        original["source_fixture"][0]["competitions"][0]["competitors"][0]["team"]["id"]="29"
        original["source_fixture_sha256"]=digest(original["source_fixture"])
        db.execute("UPDATE verified_analysis_results SET payload=?,sha256=?",
                   (json.dumps(original,sort_keys=True),digest(original)))
    r=audit.inspect_local_nba_final_fixture_links(root=root)
    assert r["status"]=="ABSTAIN_FIXTURE_OR_LOCAL_SOURCE_CONFLICT"
    assert r["invalid_final_source_replays"]==1
    assert r["local_final_source_replays"]==0


def test_wrong_frozen_canonical_fixture_id_stops_before_final_replay(tmp_path):
    root,file,p=ledger(tmp_path)
    wrong="a"*64
    with sqlite3.connect(file) as db:
        row=json.loads(db.execute(
            "SELECT payload FROM live_analysis_snapshots").fetchone()[0])
        row["fixture_id"]=wrong
        db.execute("UPDATE live_analysis_snapshots SET fixture_id=?,payload=?,sha256=?",
                   (wrong,json.dumps(row,sort_keys=True),digest(row)))
        db.execute("UPDATE live_analysis_commit_receipts SET fixture_id=?,snapshot_sha256=?",
                   (wrong,digest(row)))
    r=audit.inspect_local_nba_final_fixture_links(root=root)
    assert r["status"]=="ABSTAIN_FIXTURE_OR_LOCAL_SOURCE_CONFLICT"
    assert r["invalid_frozen_snapshots"]==1
    assert r["local_final_source_replays"]==0


def test_wal_sidecar_forbids_immutable_replay(tmp_path):
    root,file,p=ledger(tmp_path)
    (file.parent/(file.name+"-wal")).write_bytes(b"WAL")
    r=audit.inspect_local_nba_final_fixture_links(root=root)
    assert r["status"]=="ABSTAIN_WAL_PRESENT_IMMUTABLE_VIEW_INCOMPLETE"
    assert r["candidate_rows"]==0


def test_orphan_commit_receipt_stops_full_audit(tmp_path):
    root,file,p=ledger(tmp_path)
    with sqlite3.connect(file) as db:
        db.execute("INSERT INTO live_analysis_commit_receipts VALUES(?,?,?,?,?)",
                   ("NBA","orphan","x"*64,"z"*64,CREATED))
    r=audit.inspect_local_nba_final_fixture_links(root=root)
    assert r["status"]=="ABSTAIN_ORPHAN_COMMIT_RECEIPTS"
    assert r["orphan_receipts_detected"] is True


def test_bounded_one_row_does_not_claim_complete_archive(tmp_path,monkeypatch):
    root,file,p=ledger(tmp_path)
    other=deepcopy(p)
    other["fixture_id"]="b"*64
    with sqlite3.connect(file) as db:
        db.execute("INSERT INTO live_analysis_snapshots VALUES(?,?,?,?,?,?)",
                   ("NBA",other["fixture_id"],MODEL,CREATED+1,
                    json.dumps(other,sort_keys=True),digest(other)))
        db.execute("INSERT INTO live_analysis_commit_receipts VALUES(?,?,?,?,?)",
                   ("NBA",other["fixture_id"],MODEL,digest(other),CREATED+3))
    monkeypatch.setattr(audit,"MAX_ROWS",1)
    r=audit.inspect_local_nba_final_fixture_links(root=root)
    assert r["status"]=="INCOMPLETE_LOCAL_FIXTURE_AUDIT"
    assert r["scan_capped"] is True
    assert "NBA_FROZEN_ROW_LIMIT" in r["scan_cap_reasons"]

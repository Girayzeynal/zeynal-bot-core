"""Offline no-write frozen NBA receipt audit, as-of and malformed record regression."""
import json
import sqlite3
import time
from pathlib import Path

from core.team_identity import digest
from hybrid_engine import official_club_frozen_receipt_audit as aud


def _ledger(tmp_path):
    root=tmp_path/"isolated"
    folder=root/"live-nba"
    folder.mkdir(parents=True)
    file=folder/"nba-hybrid.sqlite"
    with sqlite3.connect(file) as db:
        db.execute("""CREATE TABLE live_analysis_snapshots(
            league TEXT,fixture_id TEXT,model_digest TEXT,created_utc INTEGER,
            payload TEXT,sha256 TEXT,
            PRIMARY KEY(league,fixture_id,model_digest))""")
        db.execute("""CREATE TABLE live_analysis_commit_receipts(
            league TEXT,fixture_id TEXT,model_digest TEXT,
            snapshot_sha256 TEXT,completed_utc INTEGER,
            PRIMARY KEY(league,fixture_id,model_digest))""")
    return root,file


def _forecast(now,*,fixture="0022600312"):
    model="d"*64
    return dict(record_type="LIVE_PREMATCH_PREDICTION",
        league="NBA",season="2026/2027",fixture_id=fixture,
        model_digest=model,model_version="ELITE_FROZEN_V1",
        fixture_start_utc=now+3600,record_deadline_utc=now+2400,
        created_at_utc=now,cutoff_utc=now,
        home=dict(provider_id="7"),away=dict(provider_id="3"),
        evaluation_class="LIVE_RECORDED",actual=None,
        prediction=dict(home=112.4,away=107.3),
        input_clocks=[
            dict(observed_at_utc=now-60,ingested_at_utc=now-30)])


def _insert(file,p,*,add_receipt=True,alter_payload=False,
            invalid_receipt_pin=False):
    text=json.dumps(p,sort_keys=True)
    if alter_payload:
        text=text.replace('"home": 112.4','"home": 132.4')
    pin=digest(p)
    with sqlite3.connect(file) as db:
        db.execute("INSERT INTO live_analysis_snapshots VALUES (?,?,?,?,?,?)",
                   (p["league"],p["fixture_id"],p["model_digest"],
                    p["created_at_utc"],text,pin))
        if add_receipt:
            db.execute("INSERT INTO live_analysis_commit_receipts VALUES (?,?,?,?,?)",
                       (p["league"],p["fixture_id"],p["model_digest"],
                        "0"*64 if invalid_receipt_pin else pin,
                        p["created_at_utc"]+5))


def test_local_consistent_record_reads_no_source_body_and_does_not_change_db(tmp_path):
    root,file=_ledger(tmp_path)
    p=_forecast(int(time.time())-100)
    _insert(file,p)
    original=file.read_bytes()
    r=aud.audit_isolated_nba_frozen_receipts(root=root)
    assert r["status"]=="LOCALLY_CONSISTENT_FROZEN_RECEIPTS_NOT_EXTERNALLY_ATTESTED"
    assert r["candidate_rows"]==1
    assert r["verified_local_receipts"]==1
    assert r["missing_receipts"]==0
    assert r["historical_pregame_source_proof"] is False
    assert r["official_fixture_identity_verified"] is False
    assert r["player_identity_verified"] is False
    assert r["archives_modified"] is False
    assert r["requests"]==0
    assert r["model_input"] is False
    sample=r["verified_fixture_examples"][0]
    assert sample["fixture_id"]==p["fixture_id"]
    assert sample["home_provider_team_id"]=="7"
    assert sample["away_provider_team_id"]=="3"
    assert sample["snapshot_sha256"]==digest(p)
    assert "prediction" not in json.dumps(r)
    assert file.read_bytes()==original


def test_unconfirmed_snapshot_is_not_a_verified_live_prediction(tmp_path):
    root,file=_ledger(tmp_path)
    _insert(file,_forecast(int(time.time())-100),add_receipt=False)
    result=aud.audit_isolated_nba_frozen_receipts(root=root)
    assert result["status"]=="ABSTAIN_INVALID_OR_UNCONFIRMED_FROZEN_ROWS"
    assert result["missing_receipts"]==1
    assert result["verified_local_receipts"]==0
    assert result["historical_pregame_source_proof"] is False


def test_payload_modified_without_hash_change_is_refused(tmp_path):
    root,file=_ledger(tmp_path)
    _insert(file,_forecast(int(time.time())-100),alter_payload=True)
    result=aud.audit_isolated_nba_frozen_receipts(root=root)
    assert result["status"]=="ABSTAIN_INVALID_OR_UNCONFIRMED_FROZEN_ROWS"
    assert result["invalid_snapshots"]==1
    assert result["verified_local_receipts"]==0


def test_commit_receipt_pin_mismatch_is_not_accepted(tmp_path):
    root,file=_ledger(tmp_path)
    _insert(file,_forecast(int(time.time())-100),invalid_receipt_pin=True)
    result=aud.audit_isolated_nba_frozen_receipts(root=root)
    assert result["status"]=="ABSTAIN_INVALID_OR_UNCONFIRMED_FROZEN_ROWS"
    assert result["invalid_receipts"]==1
    assert result["verified_local_receipts"]==0


def test_wal_presence_fail_closed_before_any_record_read(tmp_path):
    root,file=_ledger(tmp_path)
    _insert(file,_forecast(int(time.time())-100))
    Path(str(file)+"-wal").write_bytes(b"artificially present journal")
    result=aud.audit_isolated_nba_frozen_receipts(root=root)
    assert result["status"]=="ABSTAIN_WAL_SIDECAR_PRESENT_NOT_SNAPSHOT_COMPLETE"
    assert result["sqlite_wal_present"] is True
    assert result["verified_local_receipts"]==0


def test_bounded_snapshot_limit_reports_incomplete_not_verified_complete(tmp_path,monkeypatch):
    root,file=_ledger(tmp_path)
    now=int(time.time())-100
    _insert(file,_forecast(now,fixture="0022600312"))
    _insert(file,_forecast(now,fixture="0022600313"))
    monkeypatch.setattr(aud,"MAX_ROWS",1)
    result=aud.audit_isolated_nba_frozen_receipts(root=root)
    assert result["status"]=="AUDIT_INCOMPLETE_BOUND_REACHED"
    assert result["scan_capped"] is True
    assert result["candidate_rows"]==1
    assert "FROZEN_ROW_LIMIT" in result["scan_cap_reasons"]


def test_missing_table_never_creates_it(tmp_path):
    root,file=_ledger(tmp_path)
    with sqlite3.connect(file) as db:
        db.execute("DROP TABLE live_analysis_commit_receipts")
    before=file.read_bytes()
    result=aud.audit_isolated_nba_frozen_receipts(root=root)
    assert result["status"]=="ABSTAIN_FROZEN_RECEIPT_SCHEMA_MISSING"
    assert result["schema_missing"]==["live_analysis_commit_receipts"]
    assert file.read_bytes()==before


def test_empty_ledger_explicitly_has_no_confirmed_nba_records(tmp_path):
    root,file=_ledger(tmp_path)
    result=aud.audit_isolated_nba_frozen_receipts(root=root)
    assert result["status"]=="NO_CONFIRMED_NBA_FROZEN_SNAPSHOTS_IN_THIS_DB"
    assert result["verified_local_receipts"]==0


def test_symlink_forecast_db_rejected_without_write(tmp_path):
    root,file=_ledger(tmp_path)
    other=tmp_path/"external.sqlite"
    other.write_bytes(file.read_bytes())
    file.unlink()
    file.symlink_to(other)
    result=aud.audit_isolated_nba_frozen_receipts(root=root)
    assert result["status"]=="ISOLATED_FROZEN_LEDGER_UNAVAILABLE"
    assert result["requests"]==0

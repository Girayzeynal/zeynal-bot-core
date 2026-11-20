"""No-network frozen NBA missing final audit correctness and refusal tests."""
import json
import sqlite3

from core.team_identity import digest
from hybrid_engine import official_club_missing_final_audit as gaps
from tests.test_official_club_fixture_outcome_audit import (
    ledger, START, CREATED, MODEL)


def test_missing_local_final_before_tipoff_is_not_a_failure_or_game_final(tmp_path):
    root,file,p=ledger(tmp_path,valid_final=False)
    original=file.read_bytes()
    r=gaps.inspect_local_missing_finals(root=root,asof_utc=START-100)
    assert r["status"]=="LOCAL_MISSING_FINALS_CLASSIFIED_NO_EXTERNAL_PROOF"
    assert r["frozen_records"]==1
    assert r["locally_replayed_final_records"]==0
    assert r["missing_final_record_count"]==1
    assert r["missing_final_unique_fixture_count"]==1
    assert r["future_tipoff_missing_records"]==1
    assert r["tipoff_elapsed_missing_records"]==0
    e=r["missing_final_examples"][0]
    assert e["classification"]=="TIPOFF_NOT_YET_REACHED_LOCAL_CLOCK"
    assert e["provider_fixture_ids"]==["401000123"]
    assert e["home_espn_provider_team_id"]=="7"
    assert e["away_espn_provider_team_id"]=="3"
    assert r["missing_game_not_assumed_final"] is True
    assert r["external_fixture_identity_verified"] is False
    assert r["model_input"] is False
    assert r["archives_modified"] is False
    assert r["requests"]==0
    assert file.read_bytes()==original
    assert "116.2" not in json.dumps(r)


def test_elapsed_tipoff_is_only_local_missing_not_confirmed_finished(tmp_path):
    root,file,p=ledger(tmp_path,valid_final=False)
    r=gaps.inspect_local_missing_finals(root=root,asof_utc=START+86400)
    assert r["status"]=="LOCAL_MISSING_FINALS_CLASSIFIED_NO_EXTERNAL_PROOF"
    assert r["future_tipoff_missing_records"]==0
    assert r["tipoff_elapsed_missing_records"]==1
    assert r["missing_final_examples"][0]["classification"]=="TIPOFF_ELAPSED_BUT_LOCAL_FINAL_MISSING"
    assert r["missing_final_examples"][0]["final_status_independently_verified"] is False
    assert r["source_attestation"]=="LOCAL_STORE_ONLY_NOT_INDEPENDENT_ESPN"


def test_replayed_final_is_not_misclassified_missing(tmp_path):
    root,file,p=ledger(tmp_path,valid_final=True)
    r=gaps.inspect_local_missing_finals(root=root,asof_utc=START+86400)
    assert r["status"]=="LOCAL_MISSING_FINALS_CLASSIFIED_NO_EXTERNAL_PROOF"
    assert r["locally_replayed_final_records"]==1
    assert r["missing_final_record_count"]==0
    assert r["missing_final_examples"]==[]


def test_two_models_same_fixture_count_as_two_snapshots_one_game(tmp_path):
    root,file,p=ledger(tmp_path,valid_final=False)
    second=dict(p,model_digest="e"*64)
    with sqlite3.connect(file) as db:
        db.execute("INSERT INTO live_analysis_snapshots VALUES (?,?,?,?,?,?)",
                   ("NBA",p["fixture_id"],second["model_digest"],CREATED,
                    json.dumps(second,sort_keys=True),digest(second)))
        db.execute("INSERT INTO live_analysis_commit_receipts VALUES (?,?,?,?,?)",
                   ("NBA",p["fixture_id"],second["model_digest"],digest(second),
                    CREATED+2))
    r=gaps.inspect_local_missing_finals(root=root,asof_utc=START+86400)
    assert r["missing_final_record_count"]==2
    assert r["missing_final_unique_fixture_count"]==1
    assert len(r["missing_final_examples"])==1
    assert r["tipoff_elapsed_missing_records"]==2


def test_missing_or_tampered_local_commit_blocks_gap_reclassification(tmp_path):
    root,file,p=ledger(tmp_path,valid_final=False)
    with sqlite3.connect(file) as db:
        db.execute("UPDATE live_analysis_commit_receipts SET snapshot_sha256=?",
                   ("f"*64,))
    r=gaps.inspect_local_missing_finals(root=root,asof_utc=START+86400)
    assert r["status"]=="ABSTAIN_PRIOR_FULL_LOCAL_AUDIT_NOT_CLEAN"
    assert r["missing_final_examples"]==[]
    assert r["model_input"] is False


def test_wal_sidecar_prevents_lookahead_or_incomplete_immutable_view(tmp_path):
    root,file,p=ledger(tmp_path,valid_final=False)
    (file.parent/(file.name+"-wal")).write_bytes(b"present")
    r=gaps.inspect_local_missing_finals(root=root,asof_utc=START+86400)
    assert r["status"]=="ABSTAIN_PRIOR_FULL_LOCAL_AUDIT_NOT_CLEAN"
    assert r["missing_final_examples"]==[]
    assert r["requests"]==0


def test_limit_and_bad_asof_fail_closed(tmp_path,monkeypatch):
    root,file,p=ledger(tmp_path,valid_final=False)
    monkeypatch.setattr(gaps,"MAX_GAPS",0)
    r=gaps.inspect_local_missing_finals(root=root,asof_utc=START+86400)
    assert r["status"]=="ABSTAIN_GAP_LIMIT_REACHED"
    assert r["scan_capped"] is True
    assert r["missing_final_examples"]==[]
    import pytest
    with pytest.raises(ValueError):
        gaps.inspect_local_missing_finals(root=root,asof_utc=-1)

"""An isolated copy must never change any original NBA ledger byte."""
import json
import sqlite3
from pathlib import Path

from hybrid_engine.official_club_final_staging import prepare_isolated_final_stage
from tests.test_official_club_fixture_outcome_audit import ledger


def test_new_staging_copy_clones_frozen_and_finals_without_touching_original(tmp_path):
    root,original,_=ledger(tmp_path)
    before=original.read_bytes()
    r=prepare_isolated_final_stage(root=root)
    assert r["status"]=="STAGE_COPY_READY_NO_NATIVE_FINAL_RECEIPTS"
    assert r["source_file_unchanged"] is True
    assert r["native_final_results_appended"]==0
    assert r["native_final_receipts_supplied"] is False
    assert r["production_changed"] is False
    assert r["original_archive_modified"] is False
    assert r["model_input"] is False
    assert r["requests"]==0
    assert r["staged_snapshot_rows"]==1
    assert r["staged_commit_receipt_rows"]==1
    assert r["staged_final_rows"]==1
    assert r["prior_missing_nba_final_records"]==0
    stage=Path(r["staged_file"])
    assert stage.is_file()
    assert stage!=original
    assert stage.parent==root/"club-pilot-evidence"/"final-staging"
    assert original.read_bytes()==before
    with sqlite3.connect(stage) as copy:
        assert copy.execute(
            "SELECT COUNT(*) FROM verified_analysis_results").fetchone()[0]==1
    # The existing stage is never overwritten in an accidental rerun.
    again=prepare_isolated_final_stage(root=root)
    assert again["status"]=="ABSTAIN_STAGING_FILE_EXISTS_NEVER_OVERWRITE"
    assert stage.is_file()
    assert original.read_bytes()==before


def test_staging_missing_native_finals_keeps_them_missing_not_synthesized(tmp_path):
    root,original,_=ledger(tmp_path,valid_final=False)
    before=original.read_bytes()
    r=prepare_isolated_final_stage(root=root)
    assert r["status"]=="STAGE_COPY_READY_NO_NATIVE_FINAL_RECEIPTS"
    assert r["prior_missing_nba_final_records"]==1
    assert r["staged_final_rows"]==0
    with sqlite3.connect(r["staged_file"]) as copy:
        assert copy.execute(
            "SELECT COUNT(*) FROM verified_analysis_results").fetchone()[0]==0
    assert original.read_bytes()==before


def test_bad_source_receipt_rejected_before_creating_copy(tmp_path):
    root,original,_=ledger(tmp_path)
    with sqlite3.connect(original) as conn:
        conn.execute(
            "UPDATE live_analysis_commit_receipts SET snapshot_sha256=?",
            ("9"*64,))
    r=prepare_isolated_final_stage(root=root)
    assert r["status"]=="ABSTAIN_LOCAL_FROZEN_OR_FINAL_AUDIT_NOT_CLEAN"
    assert not (root/"club-pilot-evidence"/"final-staging").exists()


def test_wal_or_symlinked_source_or_destination_rejected(tmp_path):
    root,source,_=ledger(tmp_path)
    wal=Path(str(source)+"-wal")
    wal.write_bytes(b"not a clean checkpoint")
    r=prepare_isolated_final_stage(root=root)
    assert r["status"]=="ABSTAIN_SYMLINK_OR_SQLITE_WAL_PRESENT"
    wal.unlink()
    external=tmp_path/"private"
    external.mkdir()
    (root/"club-pilot-evidence").symlink_to(external,target_is_directory=True)
    r=prepare_isolated_final_stage(root=root)
    assert r["status"]=="ABSTAIN_SYMLINK_OR_SQLITE_WAL_PRESENT"
    assert not list(external.iterdir())


def test_no_missing_file_creation_or_writes_outside_isolated_root(tmp_path):
    root=tmp_path/"isolated"
    root.mkdir()
    report=prepare_isolated_final_stage(root=root)
    assert report["status"]=="ABSTAIN_ISOLATED_PATH_NOT_APPROVED"
    assert not list(root.iterdir())


def test_no_source_prediction_values_or_native_game_scores_exported(tmp_path):
    root,original,_=ledger(tmp_path)
    r=prepare_isolated_final_stage(root=root)
    assert "116.2" not in json.dumps(r)
    assert "115" not in json.dumps({
        "format":r["format"],
        "status":r["status"],
        "model_input":r["model_input"]})



def test_synthetic_offline_native_final_reconciles_only_on_staged_copy_twice(tmp_path):
    """Demonstrates real ledger append-only algorithm, NOT user game backfill."""
    from tests.test_official_club_fixture_outcome_audit import native_event, START
    from season_archive_inventory import archive_catalog
    from live_analysis_ledger import LiveAnalysisLedger
    root,original,_=ledger(tmp_path,valid_final=False)
    before=original.read_bytes()
    staged=prepare_isolated_final_stage(root=root)
    assert staged["status"]=="STAGE_COPY_READY_NO_NATIVE_FINAL_RECEIPTS"
    events={"events":[native_event()]}
    catalog=archive_catalog(events,provider="ESPN",season_start_year=2026,
        observed_at_utc=START+20000,ingested_at_utc=START+20005)
    copy_ledger=LiveAnalysisLedger(staged["staged_file"])
    first=copy_ledger.reconcile(catalog,trusted_sha256=catalog["sha256"])
    second=copy_ledger.reconcile(catalog,trusted_sha256=catalog["sha256"])
    assert first==1
    assert second==0
    with sqlite3.connect(staged["staged_file"]) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM verified_analysis_results").fetchone()[0]==1
    with sqlite3.connect(original) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM verified_analysis_results").fetchone()[0]==0
    assert original.read_bytes()==before
    assert copy_ledger.integrity()["verified_results"]==1


def test_synthetic_wrong_espn_fixture_is_not_assigned_to_user_game(tmp_path):
    from tests.test_official_club_fixture_outcome_audit import native_event, START
    from season_archive_inventory import archive_catalog
    from live_analysis_ledger import LiveAnalysisLedger
    root,original,_=ledger(tmp_path,valid_final=False)
    before=original.read_bytes()
    staged=prepare_isolated_final_stage(root=root)
    e=native_event()
    e["competitions"][0]["competitors"][0]["team"]["id"]="29"
    catalog=archive_catalog({"events":[e]},provider="ESPN",season_start_year=2026,
        observed_at_utc=START+20000,ingested_at_utc=START+20005)
    copy_ledger=LiveAnalysisLedger(staged["staged_file"])
    assert copy_ledger.reconcile(catalog,trusted_sha256=catalog["sha256"])==0
    assert copy_ledger.integrity()["verified_results"]==0
    assert original.read_bytes()==before

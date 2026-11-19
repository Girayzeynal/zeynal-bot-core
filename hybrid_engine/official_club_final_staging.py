"""Safely clone the isolated NBA ledger for *offline* native final staging.

This command never retrieves an ESPN document and NEVER appends a fabricated
outcome. It creates a unique new SQLite copy only under the isolated
club-pilot-evidence directory, with an original-file SHA proof and a
clean local frozen/commit/native-final audit prerequisite. Future native
final receipts must be independently validated before *separate* explicit
reconciliation on THIS copy only. Existing 23 finals remain unchanged.
"""
from contextlib import closing
from pathlib import Path
from urllib.parse import quote
import hashlib
import os
import sqlite3

from hybrid_engine.official_club_fixture_outcome_audit import (
    inspect_local_nba_final_fixture_links)

FORMAT="OFFICIAL_NBA_ISOLATED_FINAL_STAGING_V1"
MAX_LEDGER_BYTES=256*1024*1024
CHUNK=1024*1024


def _sha256_file(path):
    h=hashlib.sha256()
    with path.open("rb") as src:
        while True:
            chunk=src.read(CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def prepare_isolated_final_stage(*,root,stage_dir=None):
    root=Path(root).expanduser().absolute()
    default=(root/"club-pilot-evidence"/"final-staging").absolute()
    dest_dir=Path(stage_dir).expanduser().absolute() if stage_dir else default
    src=root/"live-nba"/"nba-hybrid.sqlite"
    base=dict(format=FORMAT,status="ABSTAIN",
              input_path="live-nba/nba-hybrid.sqlite",
              source_mode="ISOLATED_COPY_ONLY_NO_SOURCE_FETCH",
              source_file_sha256=None,stage_file_sha256=None,
              source_file_unchanged=None,
              staged_file=None,staged_snapshot_rows=None,
              staged_final_rows=None,staged_commit_receipt_rows=None,
              native_final_receipts_supplied=False,
              native_final_results_appended=0,
              stage_only_no_real_final_reconciliation=True,
              external_fixture_identity_verified=False,
              historical_pregame_source_proof=False,
              production_changed=False,original_archive_modified=False,
              model_input=False,requests=0)
    if (not root.is_dir() or root.is_symlink() or
        dest_dir!=default or src.is_symlink() or
        (root/"live-nba").is_symlink() or
        not src.is_file()):
        return dict(base,status="ABSTAIN_ISOLATED_PATH_NOT_APPROVED")
    if (any(p.is_symlink() for p in (
        root/"club-pilot-evidence",default)) or
        Path(str(src)+"-wal").exists()):
        return dict(base,status="ABSTAIN_SYMLINK_OR_SQLITE_WAL_PRESENT")
    if (not 0<src.stat().st_size<=MAX_LEDGER_BYTES):
        return dict(base,status="ABSTAIN_LEDGER_SIZE_BOUND")
    prior=inspect_local_nba_final_fixture_links(root=root)
    if prior["status"] not in (
        "LOCAL_FINAL_SOURCE_REPLAY_MATCHES_NOT_EXTERNALLY_ATTESTED",
        "NO_LOCALLY_STORED_FINAL_EVENTS_FOR_CONSISTENT_FORECASTS"):
        return dict(base,status="ABSTAIN_LOCAL_FROZEN_OR_FINAL_AUDIT_NOT_CLEAN",
                    prior_audit_status=prior["status"])
    original=_sha256_file(src)
    stage=default/("nba-final-staging-"+original[:24]+".sqlite")
    if stage.exists() or stage.is_symlink():
        return dict(base,status="ABSTAIN_STAGING_FILE_EXISTS_NEVER_OVERWRITE",
                    source_file_sha256=original)
    # New directory under user's explicitly isolated test root.
    default.mkdir(parents=True,exist_ok=True)
    if default.is_symlink():
        return dict(base,status="ABSTAIN_STAGING_SYMLINK")
    uri="file:"+quote(str(src),safe="/")+"?mode=ro&immutable=1"
    created=False
    try:
        # The O_EXCL creation reserves the exact new filename; only the
        # freshly created isolated file is ever opened for staging writes.
        fd=os.open(stage,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        os.close(fd)
        created=True
        with closing(sqlite3.connect(uri,uri=True,timeout=.5)) as source:
            source.execute("PRAGMA query_only=ON")
            with closing(sqlite3.connect(stage,timeout=2)) as target:
                source.backup(target,pages=256,sleep=0.01)
                status=target.execute("PRAGMA integrity_check").fetchone()[0]
                if status!="ok":
                    raise ValueError("COPIED_LEDGER_INTEGRITY_FAILED")
                counts={}
                for name in ("live_analysis_snapshots",
                             "live_analysis_commit_receipts",
                             "verified_analysis_results"):
                    counts[name]=target.execute(
                        'SELECT COUNT(*) FROM "'+name+'"').fetchone()[0]
        if _sha256_file(src)!=original:
            raise ValueError("SOURCE_LEDGER_CHANGED_DURING_STAGE")
        if (counts["live_analysis_snapshots"]<
            prior["consistent_frozen_snapshots"] or
            counts["verified_analysis_results"]<
            prior["local_final_source_replays"]):
            raise ValueError("STAGED_COUNTS_LOST")
        return dict(base,status="STAGE_COPY_READY_NO_NATIVE_FINAL_RECEIPTS",
            source_file_sha256=original,stage_file_sha256=_sha256_file(stage),
            source_file_unchanged=True,staged_file=str(stage),
            staged_snapshot_rows=counts["live_analysis_snapshots"],
            staged_commit_receipt_rows=counts["live_analysis_commit_receipts"],
            staged_final_rows=counts["verified_analysis_results"],
            prior_consistent_nba_records=prior["consistent_frozen_snapshots"],
            prior_local_nba_final_replays=prior["local_final_source_replays"],
            prior_missing_nba_final_records=prior["final_outcomes_missing"])
    except (OSError,sqlite3.Error,ValueError):
        # Only a NEW staged file may be deleted on failure. The original is
        # never changed and no already-existing staged file is touched.
        if created:
            try:stage.unlink(missing_ok=True)
            except OSError:pass
        return dict(base,status="ABSTAIN_ISOLATED_COPY_OR_INTEGRITY_ERROR",
                    source_file_sha256=original)

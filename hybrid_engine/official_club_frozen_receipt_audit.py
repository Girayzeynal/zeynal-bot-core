"""Read-only frozen NBA forecast + immutable commit receipt audit.

Strictly one known isolated SQLite file, zero network, no SQLite writes,
no original forecast modification or content export. A consistent DB
snapshot+commit receipt is a LOCAL integrity proof, *not* independent
historical timestamp attestation, official fixture ID or player identity.

SQLite URI immutable=1 excludes outstanding WAL frames: if a WAL sidecar
exists, refuse an auditable success rather than misstate the persisted view.
"""
from contextlib import closing
from pathlib import Path
from urllib.parse import quote
import json
import sqlite3

from core.team_identity import digest
from research_record_store import LIVE_PREMATCH_PREDICTION,validate_record

FORMAT="OFFICIAL_CLUB_FROZEN_RECEIPTS_AUDIT_V1"
MAX_ROWS=128
MAX_PAYLOAD_BYTES=512*1024
MAX_TOTAL_BYTES=8*1024*1024
MAX_EXAMPLES=8

def audit_isolated_nba_frozen_receipts(*,root):
    base=Path(root).expanduser().absolute()
    path=base/"live-nba"/"nba-hybrid.sqlite"
    report=dict(format=FORMAT,
        status="ABSTAIN_NOT_READ",
        relative_path="live-nba/nba-hybrid.sqlite",
        source_mode="READ_ONLY_IMMUTABLE_FROZEN_FORECAST_RECEIPT_AUDIT",
        candidate_rows=0,verified_local_receipts=0,
        missing_receipts=0,invalid_snapshots=0,invalid_receipts=0,
        schema_missing=[],verified_fixture_examples=[],
        scan_capped=False,scan_cap_reasons=[],payload_bytes_read=0,
        sqlite_wal_present=False,
        local_receipt_is_independent_timestamp_attestation=False,
        historical_pregame_source_proof=False,
        official_fixture_identity_verified=False,
        player_identity_verified=False,
        model_input=False,production_changed=False,requests=0,
        archives_modified=False)
    if (not base.is_dir() or base.is_symlink() or
        path.is_symlink() or (base/"live-nba").is_symlink() or
        not path.is_file()):
        report["status"]="ISOLATED_FROZEN_LEDGER_UNAVAILABLE"
        return report
    # Immutable=1 does not include uncheckpointed WAL transactions.
    wal=Path(str(path)+"-wal")
    if wal.exists():
        report["sqlite_wal_present"]=True
        report["status"]="ABSTAIN_WAL_SIDECAR_PRESENT_NOT_SNAPSHOT_COMPLETE"
        return report
    uri="file:"+quote(str(path),safe="/")+"?mode=ro&immutable=1"
    try:
        with closing(sqlite3.connect(uri,uri=True,timeout=.3)) as db:
            db.execute("PRAGMA query_only=ON")
            table_names={row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            needed=frozenset(("live_analysis_snapshots",
                              "live_analysis_commit_receipts"))
            missing=sorted(needed-table_names)
            if missing:
                report["status"]="ABSTAIN_FROZEN_RECEIPT_SCHEMA_MISSING"
                report["schema_missing"]=missing
                return report
            snapshots=db.execute(
                """SELECT s.league,s.fixture_id,s.model_digest,s.created_utc,
                          s.sha256,length(CAST(s.payload AS BLOB)),
                          r.snapshot_sha256,r.completed_utc
                   FROM live_analysis_snapshots s
                   LEFT JOIN live_analysis_commit_receipts r
                   ON r.league=s.league AND r.fixture_id=s.fixture_id
                      AND r.model_digest=s.model_digest
                   WHERE s.league='NBA'
                   ORDER BY s.created_utc,s.fixture_id,s.model_digest
                   LIMIT ?""",(MAX_ROWS+1,)).fetchall()
            report["scan_capped"]=len(snapshots)>MAX_ROWS
            if report["scan_capped"]:
                report["scan_cap_reasons"].append("FROZEN_ROW_LIMIT")
            for league,fixture,model,created,pin,size,receipt_pin,completed in snapshots[:MAX_ROWS]:
                report["candidate_rows"]+=1
                if receipt_pin is None:
                    report["missing_receipts"]+=1
                    continue
                if (type(size) is not int or size<=0 or
                    size>MAX_PAYLOAD_BYTES or
                    report["payload_bytes_read"]+size>MAX_TOTAL_BYTES):
                    report["scan_capped"]=True
                    report["scan_cap_reasons"].append("FROZEN_PAYLOAD_READ_BUDGET")
                    break
                row=db.execute(
                    """SELECT payload FROM live_analysis_snapshots
                       WHERE league=? AND fixture_id=? AND model_digest=?""",
                    (league,fixture,model)).fetchone()
                if row is None:
                    report["invalid_snapshots"]+=1
                    continue
                report["payload_bytes_read"]+=size
                try:
                    p=json.loads(row[0])
                    if (type(p) is not dict or
                        digest(p)!=pin or
                        type(created) is not int or
                        p.get("created_at_utc")!=created or
                        (p.get("league"),p.get("fixture_id"),
                         p.get("model_digest"))!=(league,fixture,model)):
                        raise ValueError("FROZEN_SNAPSHOT_INDEX_OR_PIN_INVALID")
                    validate_record(LIVE_PREMATCH_PREDICTION,p,created)
                    deadline=p.get("record_deadline_utc",
                                   p["fixture_start_utc"])
                    if (type(completed) is not int or
                        type(deadline) is not int or
                        receipt_pin!=pin or not created<=completed<deadline):
                        report["invalid_receipts"]+=1
                        continue
                    home=p.get("home")
                    away=p.get("away")
                    if (type(home) is not dict or type(away) is not dict or
                        type(home.get("provider_id")) is not str or
                        type(away.get("provider_id")) is not str or
                        not home["provider_id"] or not away["provider_id"]):
                        report["invalid_snapshots"]+=1
                        continue
                    report["verified_local_receipts"]+=1
                    if len(report["verified_fixture_examples"])<MAX_EXAMPLES:
                        report["verified_fixture_examples"].append(dict(
                            league=league,fixture_id=fixture,
                            model_digest=model,
                            snapshot_sha256=pin,
                            created_at_utc=created,
                            cutoff_utc=p["cutoff_utc"],
                            fixture_start_utc=p["fixture_start_utc"],
                            local_commit_completed_utc=completed,
                            home_provider_team_id=home["provider_id"],
                            away_provider_team_id=away["provider_id"],
                            provider_namespace="FORECAST_SOURCE_NOT_INDEPENDENTLY_CROSSCHECKED",
                            status="LOCALLY_CONSISTENT_SNAPSHOT_AND_COMMIT_RECEIPT"))
                except (ValueError,TypeError,KeyError,OverflowError,RecursionError):
                    report["invalid_snapshots"]+=1
        if report["scan_capped"]:
            report["status"]="AUDIT_INCOMPLETE_BOUND_REACHED"
        elif (report["invalid_snapshots"] or report["invalid_receipts"] or
              report["missing_receipts"]):
            report["status"]="ABSTAIN_INVALID_OR_UNCONFIRMED_FROZEN_ROWS"
        elif report["verified_local_receipts"]:
            report["status"]="LOCALLY_CONSISTENT_FROZEN_RECEIPTS_NOT_EXTERNALLY_ATTESTED"
        else:
            report["status"]="NO_CONFIRMED_NBA_FROZEN_SNAPSHOTS_IN_THIS_DB"
    except (OSError,sqlite3.Error):
        report["status"]="ABSTAIN_READ_ONLY_SQLITE_ERROR"
    report["scan_cap_reasons"]=sorted(set(report["scan_cap_reasons"]))
    return report

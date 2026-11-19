"""Offline-only forensic replay of frozen NBA fixtures against stored final events.

All source bytes come from one already-existing isolated SQLite database;
a matching forecast/result pair proves only LOCAL schema/pin/identity
consistency. This NEVER independently verifies ESPN server authenticity,
pregame publication or article visibility, player roster, or model superiority.

No network calls, no writes, no forecast modification, no model input.
"""
from contextlib import closing
from pathlib import Path
from urllib.parse import quote
import json
import sqlite3

from core.team_identity import digest
from research_record_store import LIVE_PREMATCH_PREDICTION,validate_record
from season_archive_inventory import archive_catalog

FORMAT="OFFICIAL_NBA_LOCAL_FIXTURE_FINAL_LINK_AUDIT_V1"
MAX_ROWS=128
MAX_PAYLOAD=512*1024
MAX_TOTAL=8*1024*1024
MAX_EXAMPLES=8


def inspect_local_nba_final_fixture_links(*,root):
    base=Path(root).expanduser().absolute()
    file=base/"live-nba"/"nba-hybrid.sqlite"
    report=dict(format=FORMAT,
        status="ABSTAIN_NOT_READ",
        source_mode="READ_ONLY_IMMUTABLE_LOCAL_ESPN_FINAL_REPLAY",
        relative_path="live-nba/nba-hybrid.sqlite",
        candidate_rows=0,consistent_frozen_snapshots=0,
        local_native_fixture_identity_matches=0,
        local_final_source_replays=0,
        final_outcomes_missing=0,
        invalid_frozen_snapshots=0,
        invalid_commit_receipts=0,
        invalid_final_source_replays=0,
        missing_commit_receipts=0,
        orphan_receipts_detected=False,scan_capped=False,
        scan_cap_reasons=[],payload_bytes_read=0,
        verified_fixture_examples=[],
        local_source_pins_are_independent_provider_attestation=False,
        historical_pregame_source_proof=False,
        official_external_fixture_identity_verified=False,
        player_identity_verified=False,
        records_exported=0,archives_modified=False,
        requests=0,model_input=False,production_changed=False)
    if (not base.is_dir() or base.is_symlink() or
        (base/"live-nba").is_symlink() or file.is_symlink() or
        not file.is_file()):
        report["status"]="ABSTAIN_ISOLATED_LEDGER_UNAVAILABLE"
        return report
    if Path(str(file)+"-wal").exists():
        report["status"]="ABSTAIN_WAL_PRESENT_IMMUTABLE_VIEW_INCOMPLETE"
        return report
    uri="file:"+quote(str(file),safe="/")+"?mode=ro&immutable=1"
    try:
        with closing(sqlite3.connect(uri,uri=True,timeout=.3)) as db:
            db.execute("PRAGMA query_only=ON")
            names={x[0] for x in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            needed={"live_analysis_snapshots",
                    "live_analysis_commit_receipts","verified_analysis_results"}
            if not needed.issubset(names):
                report["status"]="ABSTAIN_REQUIRED_TABLES_MISSING"
                report["schema_missing"]=sorted(needed-names)
                return report
            report["orphan_receipts_detected"]=bool(db.execute(
                """SELECT 1 FROM live_analysis_commit_receipts r
                   LEFT JOIN live_analysis_snapshots s
                   USING (league,fixture_id,model_digest)
                   WHERE r.league='NBA' AND s.fixture_id IS NULL LIMIT 1"""
            ).fetchone())
            rows=db.execute(
                """SELECT s.league,s.fixture_id,s.model_digest,s.created_utc,
                          s.sha256,r.snapshot_sha256,r.completed_utc,
                          length(CAST(s.payload AS BLOB)),
                          length(CAST(o.payload AS BLOB)),o.sha256
                   FROM live_analysis_snapshots s
                   LEFT JOIN live_analysis_commit_receipts r
                     USING(league,fixture_id,model_digest)
                   LEFT JOIN verified_analysis_results o
                     ON o.league=s.league AND o.fixture_id=s.fixture_id
                       AND o.scope='REGULATION_ONLY'
                   WHERE s.league='NBA'
                   ORDER BY s.created_utc,s.fixture_id,s.model_digest
                   LIMIT ?""",(MAX_ROWS+1,)).fetchall()
            if len(rows)>MAX_ROWS:
                report["scan_capped"]=True
                report["scan_cap_reasons"].append("NBA_FROZEN_ROW_LIMIT")
            for (league,fixture,model,created,pin,receipt_pin,completed,
                 size,final_size,final_pin) in rows[:MAX_ROWS]:
                report["candidate_rows"]+=1
                if receipt_pin is None:
                    report["missing_commit_receipts"]+=1
                    continue
                requested=(size or 0)+(final_size or 0)
                if (type(size) is not int or size<=0 or size>MAX_PAYLOAD or
                    (final_size is not None and
                     (final_size<=0 or final_size>MAX_PAYLOAD)) or
                    report["payload_bytes_read"]+requested>MAX_TOTAL):
                    report["scan_capped"]=True
                    report["scan_cap_reasons"].append("LOCAL_PAYLOAD_BYTE_LIMIT")
                    break
                record=db.execute(
                    "SELECT payload FROM live_analysis_snapshots WHERE league=? AND fixture_id=? AND model_digest=?",
                    (league,fixture,model)).fetchone()
                if record is None:
                    report["invalid_frozen_snapshots"]+=1
                    continue
                report["payload_bytes_read"]+=size
                replay_started=False
                try:
                    p=json.loads(record[0])
                    if (digest(p)!=pin or
                        p.get("record_type")!=LIVE_PREMATCH_PREDICTION or
                        p.get("created_at_utc")!=created or
                        (p.get("league"),p.get("fixture_id"),
                         p.get("model_digest"))!=(league,fixture,model)):
                        raise ValueError("INVALID_FROZEN_PIN")
                    validate_record(LIVE_PREMATCH_PREDICTION,p,created)
                    deadline=p.get("record_deadline_utc",
                                   p["fixture_start_utc"])
                    if (type(completed) is not int or
                        receipt_pin!=pin or type(deadline) is not int or
                        not created<=completed<deadline<=p["fixture_start_utc"]):
                        report["invalid_commit_receipts"]+=1
                        continue
                    home=p.get("home")
                    away=p.get("away")
                    ids=p.get("provider_fixture_ids")
                    if (not isinstance(home,dict) or not isinstance(away,dict)
                        or not isinstance(home.get("provider_id"),str)
                        or not isinstance(away.get("provider_id"),str)
                        or not isinstance(ids,list) or len(ids)==0
                        or len(ids)>10 or any(
                            type(x) is not str or not x.isascii() or
                            not x.isdigit() for x in ids)):
                        raise ValueError("NBA_PROVIDER_ID_SCHEMA_REQUIRED")
                    identity=dict(
                        provider="ESPN",league="NBA",
                        season_start_year=int(p["season"].split("/")[0]),
                        start_ts_utc=p["fixture_start_utc"],
                        home_team_id=home["provider_id"],
                        away_team_id=away["provider_id"])
                    if digest(identity)!=fixture:
                        raise ValueError("FROZEN_CANONICAL_FIXTURE_ID_CONFLICT")
                    report["consistent_frozen_snapshots"]+=1
                    report["local_native_fixture_identity_matches"]+=1
                    if final_size is None:
                        report["final_outcomes_missing"]+=1
                        continue
                    final=db.execute(
                        "SELECT payload FROM verified_analysis_results WHERE league=? AND fixture_id=? AND scope='REGULATION_ONLY'",
                        (league,fixture)).fetchone()
                    if final is None:
                        report["invalid_final_source_replays"]+=1
                        continue
                    report["payload_bytes_read"]+=final_size
                    replay_started=True
                    r=json.loads(final[0])
                    if (digest(r)!=final_pin or
                        r.get("record_type")!="VERIFIED_FINAL_RESULT" or
                        r.get("scope")!="REGULATION_ONLY" or
                        (r.get("league"),r.get("fixture_id"))!=(league,fixture)
                        or not isinstance(r.get("source_fixture"),list) or
                        len(r["source_fixture"])>10 or
                        digest(r["source_fixture"])!=r.get("source_fixture_sha256")
                        or type(r.get("source_catalog_sha256")) is not str
                        or len(r["source_catalog_sha256"])!=64):
                        raise ValueError("SOURCE_RESULT_PIN_OR_SCOPE_CONFLICT")
                    cat=archive_catalog(
                        {"events":r["source_fixture"]},provider="ESPN",
                        season_start_year=identity["season_start_year"],
                        observed_at_utc=r["observed_at_utc"],
                        ingested_at_utc=r["ingested_at_utc"])
                    matches=[g for g in cat["payload"]["fixtures"] if
                             g["canonical_id"]==fixture and g["completed"]
                             and g["periods"] is not None]
                    if len(matches)!=1:
                        raise ValueError("LOCAL_NATIVE_EVENT_IDENTITY_MISSING")
                    g=matches[0]
                    if (g["start_ts_utc"]!=p["fixture_start_utc"] or
                        g["home_team_id"]!=home["provider_id"] or
                        g["away_team_id"]!=away["provider_id"] or
                        not set(ids)&set(g["provider_fixture_ids"]) or
                        g["periods"]!=r["periods"] or
                        g["final_scores"]!=r["final_with_ot"] or
                        [sum(g["periods"][side][:4])
                            for side in ("home","away")]!=r["actual"] or
                        r["observed_at_utc"]<=p["fixture_start_utc"]):
                        raise ValueError("SOURCE_RESULT_NATIVE_FIXTURE_CONFLICT")
                    report["local_final_source_replays"]+=1
                    if len(report["verified_fixture_examples"])<MAX_EXAMPLES:
                        report["verified_fixture_examples"].append(dict(
                            fixture_id=fixture,
                            provider_fixture_ids=sorted(set(ids)),
                            start_ts_utc=p["fixture_start_utc"],
                            home_provider_team_id=home["provider_id"],
                            away_provider_team_id=away["provider_id"],
                            frozen_snapshot_sha256=pin,
                            source_catalog_sha256=r["source_catalog_sha256"],
                            local_replay_status="LOCALLY_REPRODUCIBLE_ESPN_RESULT_NO_EXTERNAL_ATTESTATION"))
                except (ValueError,TypeError,KeyError,OverflowError,
                        RecursionError,AttributeError):
                    # A source replay conflict is not a permission to rewrite
                    # a settled historical result or fit the model.
                    if replay_started:
                        report["invalid_final_source_replays"]+=1
                    else:
                        report["invalid_frozen_snapshots"]+=1
            if report["orphan_receipts_detected"]:
                report["status"]="ABSTAIN_ORPHAN_COMMIT_RECEIPTS"
            elif report["scan_capped"]:
                report["status"]="INCOMPLETE_LOCAL_FIXTURE_AUDIT"
            elif (report["missing_commit_receipts"] or
                  report["invalid_frozen_snapshots"] or
                  report["invalid_commit_receipts"] or
                  report["invalid_final_source_replays"]):
                report["status"]="ABSTAIN_FIXTURE_OR_LOCAL_SOURCE_CONFLICT"
            elif report["local_final_source_replays"]:
                report["status"]="LOCAL_FINAL_SOURCE_REPLAY_MATCHES_NOT_EXTERNALLY_ATTESTED"
            elif report["consistent_frozen_snapshots"]:
                report["status"]="NO_LOCALLY_STORED_FINAL_EVENTS_FOR_CONSISTENT_FORECASTS"
            else:
                report["status"]="NO_NBA_FROZEN_SNAPSHOTS_FOUND"
    except (OSError,sqlite3.Error):
        report["status"]="ABSTAIN_READ_ONLY_SQLITE_ERROR"
    report["scan_cap_reasons"]=sorted(set(report["scan_cap_reasons"]))
    return report

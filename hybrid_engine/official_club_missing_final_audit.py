"""Targeted read-only inventory for NBA final result gaps in a frozen ledger.

Before reporting gaps, reruns the existing full frozen/ESPN local replay gate.
Each missing final is then checked against pinned snapshot, commit receipt
and canonical provider/fixture ID. Uses the LOCAL device clock only to
divide future tipoffs from elapsed tipoffs, not to assert game completion.
Never contacts ESPN, writes the archive or creates synthetic outcomes.
"""
from contextlib import closing
from pathlib import Path
from urllib.parse import quote
import json
import sqlite3
import time

from core.team_identity import digest
from research_record_store import LIVE_PREMATCH_PREDICTION, validate_record
from hybrid_engine.official_club_fixture_outcome_audit import inspect_local_nba_final_fixture_links

FORMAT="OFFICIAL_NBA_LOCAL_FINAL_GAPS_V1"
MAX_GAPS=64
MAX_PAYLOAD=512*1024
MAX_TOTAL=8*1024*1024

def inspect_local_missing_finals(*,root,asof_utc=None):
    if asof_utc is None:
        asof_utc=int(time.time())
    if type(asof_utc) is not int or asof_utc<=0:
        raise ValueError("LOCAL_ASOF_UTC_REQUIRED")
    base=Path(root).expanduser().absolute()
    report=dict(format=FORMAT,status="ABSTAIN",
        source_mode="ZERO_NETWORK_IMMUTABLE_LOCAL_GAP_INVENTORY",
        checked_at_utc=asof_utc,
        clock_source="LOCAL_DEVICE_CLOCK_NOT_INDEPENDENTLY_ATTESTED",
        prior_full_local_replay_status=None,
        frozen_records=0,locally_replayed_final_records=0,
        missing_final_record_count=0,missing_final_unique_fixture_count=0,
        future_tipoff_missing_records=0,
        tipoff_elapsed_missing_records=0,
        missing_final_examples=[],scan_capped=False,
        source_attestation="LOCAL_STORE_ONLY_NOT_INDEPENDENT_ESPN",
        missing_game_not_assumed_final=True,
        external_fixture_identity_verified=False,
        historical_pregame_source_proof=False,
        model_input=False,production_changed=False,
        archives_modified=False,requests=0)
    previous=inspect_local_nba_final_fixture_links(root=base)
    report["prior_full_local_replay_status"]=previous["status"]
    if previous["status"] not in (
        "LOCAL_FINAL_SOURCE_REPLAY_MATCHES_NOT_EXTERNALLY_ATTESTED",
        "NO_LOCALLY_STORED_FINAL_EVENTS_FOR_CONSISTENT_FORECASTS"):
        report["status"]="ABSTAIN_PRIOR_FULL_LOCAL_AUDIT_NOT_CLEAN"
        return report
    report["frozen_records"]=previous["consistent_frozen_snapshots"]
    report["locally_replayed_final_records"]=previous["local_final_source_replays"]
    file=base/"live-nba"/"nba-hybrid.sqlite"
    if (not file.is_file() or file.is_symlink() or
        (base/"live-nba").is_symlink() or
        Path(str(file)+"-wal").exists()):
        report["status"]="ABSTAIN_LOCAL_SQLITE_VIEW_CHANGED"
        return report
    uri="file:"+quote(str(file),safe="/")+"?mode=ro&immutable=1"
    seen=set()
    read=0
    try:
        with closing(sqlite3.connect(uri,uri=True,timeout=.3)) as db:
            db.execute("PRAGMA query_only=ON")
            rows=db.execute(
                """SELECT s.fixture_id,s.model_digest,s.created_utc,
                          s.sha256,s.payload,r.snapshot_sha256,r.completed_utc,
                          length(CAST(s.payload AS BLOB))
                   FROM live_analysis_snapshots s
                   JOIN live_analysis_commit_receipts r
                     USING (league,fixture_id,model_digest)
                   LEFT JOIN verified_analysis_results o
                     ON o.league=s.league AND o.fixture_id=s.fixture_id
                      AND o.scope='REGULATION_ONLY'
                   WHERE s.league='NBA' AND o.fixture_id IS NULL
                   ORDER BY s.created_utc,s.fixture_id,s.model_digest
                   LIMIT ?""",(MAX_GAPS+1,)).fetchall()
            if len(rows)>MAX_GAPS:
                report["scan_capped"]=True
                report["status"]="ABSTAIN_GAP_LIMIT_REACHED"
                return report
            for fixture,model,created,pin,raw,receipt_pin,completed,size in rows:
                if (type(size) is not int or not 0<size<=MAX_PAYLOAD or
                    read+size>MAX_TOTAL):
                    report["scan_capped"]=True
                    report["status"]="ABSTAIN_PAYLOAD_BUDGET"
                    return report
                read+=size
                p=json.loads(raw)
                validate_record(LIVE_PREMATCH_PREDICTION,p,created)
                deadline=p.get("record_deadline_utc",p["fixture_start_utc"])
                if (digest(p)!=pin or p["fixture_id"]!=fixture or
                    p["model_digest"]!=model or
                    p["created_at_utc"]!=created or
                    type(completed) is not int or
                    receipt_pin!=pin or type(deadline) is not int or
                    not created<=completed<deadline<=p["fixture_start_utc"]):
                    raise ValueError("FROZEN_GAP_COMMIT_PIN_CONFLICT")
                ids=p["provider_fixture_ids"]
                if (not isinstance(ids,list) or not 0<len(ids)<=10 or
                    any(type(x) is not str or not x.isascii() or not x.isdigit()
                        for x in ids)):
                    raise ValueError("ESPN_PROVIDER_GAME_IDS_REQUIRED")
                home=p["home"]["provider_id"]
                away=p["away"]["provider_id"]
                identity=dict(provider="ESPN",league="NBA",
                    season_start_year=int(p["season"].split("/")[0]),
                    start_ts_utc=p["fixture_start_utc"],
                    home_team_id=home,away_team_id=away)
                if digest(identity)!=fixture:
                    raise ValueError("FROZEN_GAP_CANONICAL_FIXTURE_CONFLICT")
                report["missing_final_record_count"]+=1
                future=p["fixture_start_utc"]>asof_utc
                key="future_tipoff_missing_records" if future else "tipoff_elapsed_missing_records"
                report[key]+=1
                if fixture not in seen:
                    seen.add(fixture)
                    report["missing_final_examples"].append(dict(
                        fixture_id=fixture,
                        provider_fixture_ids=sorted(set(ids)),
                        model_digest=model,source_snapshot_sha256=pin,
                        fixture_start_utc=p["fixture_start_utc"],
                        frozen_created_utc=created,
                        local_commit_completed_utc=completed,
                        home_espn_provider_team_id=home,
                        away_espn_provider_team_id=away,
                        classification=(
                            "TIPOFF_NOT_YET_REACHED_LOCAL_CLOCK"
                            if future else
                            "TIPOFF_ELAPSED_BUT_LOCAL_FINAL_MISSING"),
                        final_status_independently_verified=False))
    except (sqlite3.Error,OSError,UnicodeError,ValueError,TypeError,
            KeyError,OverflowError,RecursionError):
        report["status"]="ABSTAIN_GAP_PAYLOAD_OR_SQLITE_CONFLICT"
        report["missing_final_examples"]=[]
        return report
    report["missing_final_unique_fixture_count"]=len(seen)
    if report["missing_final_record_count"]!=previous["final_outcomes_missing"]:
        report["status"]="ABSTAIN_LOCAL_REPLAY_CHANGED_DURING_GAP_AUDIT"
        report["missing_final_examples"]=[]
    else:
        report["status"]="LOCAL_MISSING_FINALS_CLASSIFIED_NO_EXTERNAL_PROOF"
    return report

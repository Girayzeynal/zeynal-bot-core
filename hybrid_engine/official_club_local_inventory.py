"""Read-only, zero-network inventory for isolated source identity evidence.

Never writes SQLite, reads SQLite rows, exports raw documents, computes a
self-authenticating trust pin, touches a model/forecast or bypasses robots.
A partial inventory is NEVER reported as a complete absence of data.

Only ~/zeynal-test-isolated/data (or explicitly injected test root); bounded
metadata walk, candidate-prioritized JSON reading, and immutable SQLite
schema introspection. SQLite immutable mode can miss uncheckpointed WAL data.
"""
from pathlib import Path
from contextlib import closing
from urllib.parse import quote
import json
import os
import sqlite3

FORMAT="OFFICIAL_CLUB_LOCAL_SOURCE_INVENTORY_V2"
MAX_ENTRIES=20000
MAX_DIRS=4000
MAX_JSON_READS=3000
MAX_JSON_BYTES=32*1024*1024
MAX_ONE_JSON=4*1024*1024
MAX_SQLITE_INSPECTED=16
MAX_SCHEMA_ROWS=120
MAX_RESULTS=16
MAX_DEPTH=6
_KEYWORDS=("participant","team","identity","roster","season","snapshot","catalog")
_TABLE_KEYWORDS=("participant","team","identity","roster","snapshot","source","fixture")
_SQL_EXTENSIONS=(".sqlite",".sqlite3",".db")


def _candidate_score(path):
    txt=(path.name+" "+path.parent.name).casefold()
    return sum(1 for s in _KEYWORDS if s in txt)


def _peek_json(file, stats):
    n=file.stat().st_size
    if n<=0 or n>MAX_ONE_JSON or n>MAX_JSON_BYTES-stats["json_bytes_read"]:
        if n>MAX_JSON_BYTES-stats["json_bytes_read"]:
            stats["scan_capped"]=True
            stats["scan_cap_reasons"].add("JSON_READ_BYTE_BUDGET")
        return None
    # Inspect candidate files only; no arbitrary source bodies in output.
    raw=file.read_bytes()
    stats["json_bytes_read"]+=n
    stats["scanned_json_files"]+=1
    try:
        obj=json.loads(raw)
    except (ValueError,UnicodeError,RecursionError,OverflowError):
        return None
    if (type(obj) is dict and type(obj.get("payload")) is dict and
        obj["payload"].get("format")=="SEASON_PARTICIPANTS_V1" and
        obj["payload"].get("league_id")=="NBA" and
        obj["payload"].get("season_id")=="2026/2027"):
        p=obj["payload"]
        return dict(relative_path=None,claimed_snapshot_sha256=obj.get("sha256"),
                    source_ingested_at_utc=p.get("ingested_at_utc"),
                    source_observed_at_utc=p.get("observed_at_utc"),
                    participant_count=p.get("participant_count"),
                    status="UNTRUSTED_SNAPSHOT_CANDIDATE_NOT_ASOF_PROOF")
    return None


def _sqlite_tables(file):
    # Immutable readonly URI prevents journal writes. Never SELECT data rows.
    uri="file:"+quote(str(file),safe="/")+"?mode=ro&immutable=1"
    connection=sqlite3.connect(uri,uri=True,timeout=.3)
    try:
        connection.execute("PRAGMA query_only=ON")
        tables=[str(x[0]) for x in connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type IN ('table','view') ORDER BY name LIMIT ?",
            (MAX_SCHEMA_ROWS+1,))]
        capped=len(tables)>MAX_SCHEMA_ROWS
        interesting=[v[:100] for v in tables[:MAX_SCHEMA_ROWS]
                     if any(t in v.casefold() for t in _TABLE_KEYWORDS)]
        return interesting[:MAX_RESULTS],capped
    finally:
        connection.close()


def inspect_local_source_inventory(*,root):
    root=Path(root).expanduser().absolute()
    report=dict(format=FORMAT,
                status="LOCAL_ISOLATED_DATA_ROOT_UNAVAILABLE",
                source_mode="LOCAL_ISOLATED_READ_ONLY_INVENTORY",
                json_files_enumerated=0,scanned_json_files=0,
                sqlite_files_enumerated=0,sqlite_files_inspected=0,
                candidate_files=[],sqlite_schema_candidates=[],
                sqlite_database_paths=[],scan_capped=False,
                scan_cap_reasons=[],
                metadata_entries_examined=0,json_bytes_read=0,
                sqlite_inspection_mode="READ_ONLY_IMMUTABLE_SCHEMA_ONLY_WAL_NOT_INCLUDED",
                snapshot_sha_independently_pinned=False,
                historical_pregame_proof=False,
                requests=0,model_input=False,production_changed=False)
    if not root.is_dir() or root.is_symlink():
        return report
    stats=dict(scan_capped=False,scan_cap_reasons=set(),
               json_bytes_read=0,scanned_json_files=0)
    jsons=[];sqlitefiles=[]
    total=0;stop=False;visited_dirs=0
    # Metadata-only bounded traversal. Symlinked directories/files excluded.
    for where,dirs,files in os.walk(root,followlinks=False):
        visited_dirs+=1
        if visited_dirs>MAX_DIRS:
            stats["scan_capped"]=True
            stats["scan_cap_reasons"].add("DIRECTORY_METADATA_LIMIT")
            break
        place=Path(where)
        depth=len(place.relative_to(root).parts)
        if depth>MAX_DEPTH:
            stats["scan_capped"]=True
            stats["scan_cap_reasons"].add("DIRECTORY_DEPTH_LIMIT")
            dirs[:]=[]
            continue
        dirs[:]=sorted(d for d in dirs if not (place/d).is_symlink())
        if depth==MAX_DEPTH and dirs:
            stats["scan_capped"]=True
            stats["scan_cap_reasons"].add("DIRECTORY_DEPTH_LIMIT")
            dirs[:]=[]
        for name in sorted(files):
            if total>=MAX_ENTRIES:
                stats["scan_capped"]=True
                stats["scan_cap_reasons"].add("METADATA_ENTRY_LIMIT")
                stop=True
                break
            total+=1
            p=place/name
            if p.is_symlink():
                continue
            kind=p.suffix.casefold()
            if kind==".json":
                jsons.append(p)
            elif kind in _SQL_EXTENSIONS:
                sqlitefiles.append(p)
        if stop:break
    report["metadata_entries_examined"]=total
    report["json_files_enumerated"]=len(jsons)
    report["sqlite_files_enumerated"]=len(sqlitefiles)
    # Prioritize source/season-specific filenames; not first 500
    # alphabetically in the largest unrelated forecast/result folder.
    jsons.sort(key=lambda p:(-_candidate_score(p),str(p.relative_to(root))))
    for i,file in enumerate(jsons):
        if i>=MAX_JSON_READS or len(report["candidate_files"])>=MAX_RESULTS:
            stats["scan_capped"]=True
            stats["scan_cap_reasons"].add("JSON_CANDIDATE_READ_LIMIT")
            break
        try:
            candidate=_peek_json(file,stats)
        except (OSError,PermissionError):
            stats["scan_capped"]=True
            stats["scan_cap_reasons"].add("JSON_READ_ERROR")
            continue
        if candidate is not None:
            candidate["relative_path"]=str(file.relative_to(root))
            report["candidate_files"].append(candidate)
        if "JSON_READ_BYTE_BUDGET" in stats["scan_cap_reasons"]:
            break
    sqlitefiles.sort(key=lambda p:(-_candidate_score(p),str(p.relative_to(root))))
    if len(sqlitefiles)>MAX_SQLITE_INSPECTED:
        stats["scan_capped"]=True
        stats["scan_cap_reasons"].add("SQLITE_SCHEMA_FILE_LIMIT")
    for file in sqlitefiles[:MAX_SQLITE_INSPECTED]:
        try:
            if file.stat().st_size<=0:
                continue
            names,capped=_sqlite_tables(file)
            report["sqlite_files_inspected"]+=1
            relative=str(file.relative_to(root))
            if len(report["sqlite_database_paths"])<MAX_RESULTS:
                report["sqlite_database_paths"].append(relative)
            if names:
                report["sqlite_schema_candidates"].append(dict(
                    relative_path=relative,table_names=names,
                    status="SCHEMA_NAMES_ONLY_NOT_SOURCE_PROOF"))
            if capped:
                stats["scan_capped"]=True
                stats["scan_cap_reasons"].add("SQLITE_SCHEMA_TABLE_LIMIT")
        except (OSError,sqlite3.Error,ValueError):
            stats["scan_capped"]=True
            stats["scan_cap_reasons"].add("SQLITE_SCHEMA_READ_ERROR")
    report.update(
        scanned_json_files=stats["scanned_json_files"],
        json_bytes_read=stats["json_bytes_read"],
        scan_capped=stats["scan_capped"],
        scan_cap_reasons=sorted(stats["scan_cap_reasons"]))
    if report["candidate_files"] or report["sqlite_schema_candidates"]:
        report["status"]="LOCAL_IDENTITY_SOURCE_CANDIDATES_UNVERIFIED"
    elif report["scan_capped"]:
        report["status"]="LOCAL_IDENTITY_SCAN_INCOMPLETE_NO_MATCH"
    else:
        report["status"]="NO_IDENTITY_SOURCE_FOUND_IN_SCANNED_LOCAL_SCOPE"
    return report


# Fixed user-observed database locations and known forecasting snapshot tables.
# This targeted diagnostics function reads SQLite schema only, never record rows.
_KNOWN_SCHEMA_TARGETS=(
    ("faz23_storage.sqlite","snapshots","FAZ23_ANALYSIS_SNAPSHOT"),
    ("live-nba/nba-hybrid.sqlite","live_analysis_snapshots",
     "FROZEN_LIVE_FORECAST_SNAPSHOT"),
    ("telegram-delivery.sqlite","delivery_events","TELEGRAM_DELIVERY_EVENT"),
)


def inspect_known_database_columns(*,root):
    """Bounded, targeted SQLite PRAGMA table_info on observed databases.

    No user-provided SQL identifiers; no generic database crawling.
    The presence of a payload column does not validate identities or
    authorize extracting that payload or rewriting an existing forecast.
    """
    root=Path(root).expanduser().absolute()
    report=dict(
        format="OFFICIAL_CLUB_LOCAL_DB_SCHEMA_DETAIL_V1",
        status="ISOLATED_DATA_ROOT_UNAVAILABLE",
        source_mode="KNOWN_SQLITE_SCHEMA_ONLY",
        inspected_tables=[],unavailable_targets=[],
        sqlite_inspection_mode="READ_ONLY_IMMUTABLE_SCHEMA_ONLY_WAL_NOT_INCLUDED",
        direct_provider_team_id_column_found=False,
        extracted_records=0,first_issued_forecast_proof=False,
        participant_identity_verified=False,verified_player_id=None,
        requests=0,model_input=False,production_changed=False)
    if not root.is_dir() or root.is_symlink():
        return report
    for relative,table,role in _KNOWN_SCHEMA_TARGETS:
        file=root/relative
        if (file.is_symlink() or
            any(part.is_symlink() for part in (file.parent,) if part!=root)
            or not file.is_file()):
            report["unavailable_targets"].append(
                dict(relative_path=relative,reason="MISSING_OR_SYMLINK"))
            continue
        try:
            uri="file:"+quote(str(file),safe="/")+"?mode=ro&immutable=1"
            with closing(sqlite3.connect(uri,uri=True,timeout=.3)) as conn:
                conn.execute("PRAGMA query_only=ON")
                # table is a hardcoded constant from our source, not user input.
                schema=conn.execute('PRAGMA table_info("'+table+'")').fetchall()
                if not schema:
                    report["unavailable_targets"].append(
                        dict(relative_path=relative,reason="KNOWN_TABLE_NOT_VISIBLE"))
                    continue
                columns=[dict(name=str(x[1])[:80],type=str(x[2])[:60],
                              primary_key=bool(x[5])) for x in schema[:48]]
                names={x["name"].casefold() for x in columns}
                direct=("provider_team_id" in names or
                        "espn_team_id" in names or "nba_team_id" in names)
                report["direct_provider_team_id_column_found"]|=direct
                report["inspected_tables"].append(dict(
                    relative_path=relative,table=table,
                    inferred_table_role=role,
                    columns=columns,
                    schema_column_count=len(schema),
                    schema_column_limit_reached=len(schema)>48,
                    contains_opaque_payload_column=("payload" in names),
                    direct_provider_team_id_columns_visible=direct,
                    status="SCHEMA_METADATA_ONLY_NOT_PARTICIPANT_PROOF"))
        except (OSError,sqlite3.Error,ValueError):
            report["unavailable_targets"].append(
                dict(relative_path=relative,reason="READ_ONLY_SCHEMA_ERROR"))
    report["status"]=(
        "KNOWN_LOCAL_SCHEMAS_OBSERVED_NOT_IDENTITY_VALIDATED"
        if report["inspected_tables"] else
        "NO_KNOWN_SQLITE_SCHEMAS_OBSERVED")
    return report

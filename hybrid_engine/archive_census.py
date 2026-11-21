"""Read-only local first-to-now forecast inventory (not model validation).

Counts distinct fixtures and separate model versions, never training/history rows.
The caller's phone files are not the remote Fly.io volume.
No provider, Telegram, network, model fit or SQLite writes.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

from core.team_identity import digest

MAX_ROWS = 25000
MAX_FILES = 8000
TSI = ZoneInfo("Europe/Istanbul")


def stamp(ts):
    return None if not isinstance(ts, int) or ts <= 0 else datetime.fromtimestamp(
        ts, TSI).strftime("%Y-%m-%d %H:%M:%S TSİ")


def readonly_database(path):
    if not path.is_file():
        return None
    if path.is_symlink() or path.resolve() != path:
        raise ValueError("CENSUS_SYMLINK_DATABASE_REFUSED")
    return sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2)


def _group(rows):
    groups = defaultdict(list)
    for league, fixture, model, first in rows:
        groups[league].append((str(fixture), str(model), first))
    results = {}
    for league, entries in sorted(groups.items()):
        ids = {(f, m) for f, m, _ in entries}
        times = [t for _, _, t in entries if isinstance(t, int) and t > 0]
        results[league] = dict(unique_fixtures=len({f for f, _, _ in entries}),
            unique_model_forecasts=len(ids), earliest_forecast_tsi=stamp(min(times)) if times else None,
            latest_forecast_tsi=stamp(max(times)) if times else None)
    return results


def sqlite_report(path):
    db = readonly_database(path)
    if db is None:
        return dict(status="NOT_PRESENT")
    try:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        report = dict(status="READ_ONLY", sources={})
        if {"live_analysis_snapshots", "live_analysis_commit_receipts"} <= tables:
            records = db.execute("""SELECT s.league, s.fixture_id, s.model_digest, s.created_utc,
                r.completed_utc FROM live_analysis_snapshots s
                LEFT JOIN live_analysis_commit_receipts r
                  USING(league,fixture_id,model_digest)
                LIMIT ?""", (MAX_ROWS+1,)).fetchall()
            if len(records)>MAX_ROWS:
                raise ValueError("CENSUS_SQL_ROW_BUDGET")
            committed = [r for r in records if isinstance(r[4], int) and r[4]>=r[3]]
            report["sources"]["verified_live"] = dict(
                **_group([(l,f,m,first) for l,f,m,first,_ in committed]),
                snapshots_all=len(records), committed_snapshots=len(committed),
                missing_commit_receipt=len(records)-len(committed),
                note="Versions of the same fixture are not distinct games")
            if "verified_analysis_results" in tables:
                outcomes = db.execute("""SELECT league, COUNT(DISTINCT fixture_id)
                    FROM verified_analysis_results WHERE scope='REGULATION_ONLY'
                    GROUP BY league""").fetchall()
                report["sources"]["verified_live"]["verified_result_fixture_counts"] = dict(outcomes)
        if "predictions" in tables:
            legacy = db.execute("""SELECT league,fixture_id,prediction_ts_utc
                FROM predictions LIMIT ?""", (MAX_ROWS+1,)).fetchall()
            if len(legacy)>MAX_ROWS:
                raise ValueError("CENSUS_SQL_ROW_BUDGET")
            report["sources"]["legacy_first"] = dict(
                **_group([(l,f,"LEGACY_FIRST",t) for l,f,t in legacy]),
                count=len(legacy), note="May overlap with verified_live; never add without identity matching")
        if "prediction_versions" in tables:
            revisions = db.execute("""SELECT league,fixture_id,version_id,prediction_ts_utc
                FROM prediction_versions LIMIT ?""", (MAX_ROWS+1,)).fetchall()
            if len(revisions)>MAX_ROWS:
                raise ValueError("CENSUS_SQL_ROW_BUDGET")
            report["sources"]["legacy_versions"] = dict(
                **_group([(l,f,str(v),t) for l,f,v,t in revisions]),
                count=len(revisions), note="Repeated requests can create new versions; not extra games")
        return report
    finally:
        db.close()


def europe_report(root):
    result={}
    for league in ("EUROLEAGUE", "EUROCUP"):
        d = root/"europe"/league.lower()
        if not d.is_dir():
            result[league]=dict(status="NOT_PRESENT")
            continue
        files=list(d.rglob("first-*.json"))
        if len(files)>MAX_FILES:
            result[league]=dict(status="FILE_BUDGET_EXCEEDED",count_lower_bound=MAX_FILES)
            continue
        collected=[]
        errors=0
        for slot in files:
            try:
                if slot.is_symlink() or slot.stat().st_size>262144:
                    raise ValueError("CENSUS_FILE_UNSAFE")
                wrapped=json.loads(slot.read_text())
                pub=wrapped["payload"]
                if digest(pub)!=wrapped["sha256"] or pub["classification"]!="PREMATCH":
                    raise ValueError("CENSUS_FIRST_PIN")
                ref=pub["forecast"]
                filename=ref["file"]
                if filename!=Path(filename).name or not filename.startswith("forecast-"):
                    raise ValueError("CENSUS_FORECAST_PATH")
                src=slot.parent/filename
                if src.is_symlink() or src.stat().st_size>1048576:
                    raise ValueError("CENSUS_SOURCE_UNSAFE")
                p=json.loads(src.read_text())
                if digest(p)!=ref["sha256"] or p["fixture"]["canonical_id"] is None:
                    raise ValueError("CENSUS_FORECAST_PIN")
                first=pub["first_archived_at_utc"]
                if not isinstance(first,int) or first>=p["fixture"]["start_ts_utc"]:
                    raise ValueError("CENSUS_FORECAST_NOT_PREMATCH")
                collected.append((league,p["fixture"]["canonical_id"],p["version"],first))
            except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError):
                errors+=1
        result[league]=dict(status="READ_ONLY" if errors==0 else "PARTIAL_UNVERIFIED",
            **_group(collected).get(league,dict(unique_fixtures=0,unique_model_forecasts=0,
                earliest_forecast_tsi=None,latest_forecast_tsi=None)),
            first_publication_files=len(files), invalid_or_unsupported=errors)
    return result


def frozen_report(directory):
    if directory is None or not directory.is_dir():
        return dict(status="NOT_INSPECTED")
    # A replay capture index is not a new forecast every time a model is replayed.
    files=list(directory.glob("index-*.json"))
    if len(files)!=1:
        return dict(status="NO_UNAMBIGUOUS_INDEX")
    try:
        index=json.loads(files[0].read_text())
        rows=index["records"]
        if len(rows)>MAX_ROWS:raise ValueError("CENSUS_INDEX_BUDGET")
        unique={r["fixture_id"] for r in rows}
        return dict(status="INDEX_METADATA_ONLY_NOT_NATIVE_VERIFIED",
            capture_index_entries=len(rows),unique_fixtures=len(unique),
            note="May overlap with live European registries; excluded from primary totals")
    except (OSError,KeyError,TypeError,ValueError,json.JSONDecodeError):
        return dict(status="INDEX_NOT_VERIFIED")


def census(data_directory, archive_directory=None, legacy_database=None):
    root=Path(data_directory).expanduser().absolute()
    if root.is_symlink():
        raise ValueError("CENSUS_ROOT_SYMLINK_REFUSED")
    legacy=None if legacy_database is None else sqlite_report(Path(legacy_database).expanduser().absolute())
    return dict(format="ZEYNAL_ARCHIVE_CENSUS_READ_ONLY_V1",
        scope="THIS_LOCAL_INSTALLATION_ONLY__NOT_REMOTE_FLY_PRODUCTION",
        season_history_and_training_rows_excluded=True,
        no_predictions_generated=True,archive_files_modified=False,
        nba_sqlite=sqlite_report(root/"live-nba"/"nba-hybrid.sqlite"),
        european_original_publications=europe_report(root),
        legacy_frozen_research=frozen_report(
            None if archive_directory is None else Path(archive_directory).expanduser().absolute()),
        optional_legacy_production_copy=legacy,
        caveat="Counts are per source and may overlap; historical source games and repeated model versions are not additional original games. Remote Fly database was NOT queried.")


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-directory",required=True)
    p.add_argument("--archive-directory")
    p.add_argument("--legacy-database")
    a=p.parse_args()
    print(json.dumps(census(a.data_directory,a.archive_directory,a.legacy_database),
        ensure_ascii=False,sort_keys=True,indent=2))


if __name__=="__main__":
    main()

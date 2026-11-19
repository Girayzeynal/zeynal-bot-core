"""Opt-in native NBA finals on an isolated existing SQLite COPY ONLY.

Default dry run: zero HTTP, zero writes. Explicit live mode calls the
existing native ESPN scoreboard settlement path only after a same-host
robots policy check. Max three dates. No NBA.com score injection, no
retrospective forecast changes, no production ledger access.
"""
import argparse
from datetime import datetime,timedelta
import json
from pathlib import Path
import re
import sqlite3
import time
from zoneinfo import ZoneInfo

from hybrid_engine.confirmed_nba import read_confirmed_nba
from hybrid_engine.nba_ledger_settlement import settle
from hybrid_engine.official_club_final_staging import _sha256_file
from hybrid_engine.official_club_sources import _request,allowed_by_robots,MAX_ROBOTS
from ledger_reports import LedgerReports
from live_analysis_ledger import LiveAnalysisLedger
from season_archive_collect import fetch_document

FORMAT="OFFICIAL_NBA_ISOLATED_NATIVE_SETTLEMENT_V1"
ROBOTS="https://site.api.espn.com/robots.txt"
URL_HEAD="https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates="
URL_TAIL="&limit=1000"
STAGE_NAME=re.compile(r"nba-final-staging-[0-9a-f]{24}\.sqlite\Z")


def _local_state(root,stage):
    root=Path(root).expanduser().absolute()
    old=root/"live-nba"/"nba-hybrid.sqlite"
    staged=Path(stage).expanduser().absolute()
    folder=root/"club-pilot-evidence"/"final-staging"
    if (not root.is_dir() or root.is_symlink() or
        staged.parent!=folder or not STAGE_NAME.fullmatch(staged.name)
        or any(p.is_symlink() for p in
               (root/"live-nba",root/"club-pilot-evidence",folder,old,staged))
        or not old.is_file() or not staged.is_file()
        or Path(str(old)+"-wal").exists()
        or Path(str(staged)+"-wal").exists()
        or not 0<old.stat().st_size<=256*1024*1024
        or not 0<staged.stat().st_size<=256*1024*1024):
        raise ValueError("STAGED_SQLITE_ISOLATED_SOURCE_REQUIRED")
    sha=_sha256_file(old)
    if staged.name!="nba-final-staging-"+sha[:24]+".sqlite":
        raise ValueError("STAGED_SQLITE_ORIGINAL_SHA_MISMATCH")
    return old,staged,sha


def _due_urls(path,now):
    report=LedgerReports(path).read("NBA")
    if report.get("status")!="VERIFIED_LIVE_REPORT":
        raise ValueError("STAGED_REPORT_NOT_AVAILABLE")
    records=read_confirmed_nba(path)
    if len(records)>128:
        raise ValueError("STAGED_FROZEN_RECORD_LIMIT")
    pending={(r["fixture_id"],r["snapshot_sha256"]) for r in
             report["forecasts"] if r["actual"] is None}
    due=[r for r in records if
         r["snapshot"]["fixture_start_utc"]<now and
         (r["snapshot"]["fixture_id"],r["snapshot_sha256"]) in pending]
    days=set()
    for row in due:
        day=datetime.fromtimestamp(
            row["snapshot"]["fixture_start_utc"],
            ZoneInfo("America/New_York")).date()
        days.update((day-timedelta(days=1),day,day+timedelta(days=1)))
    if len(days)>3:
        raise ValueError("STAGED_NATIVE_SOURCE_MORE_THAN_THREE_DATES")
    return tuple(URL_HEAD+d.strftime("%Y%m%d")+URL_TAIL
                 for d in sorted(days)),len(due),report["pending"]


def settle_isolated_stage(*,root,stage,live=False,
                          fetcher=fetch_document,robots_fetcher=_request,
                          asof_utc=None):
    report=dict(format=FORMAT,status="ABSTAIN",
        mode="EXPLICIT_LIVE_STAGE_ONLY" if live else "DRY_RUN",
        requests=0,stage_results_appended=0,
        source_policy_verified=False,stage_only=True,
        original_archive_modified=False,
        model_input=False,production_changed=False,
        historical_pregame_source_proof=False)
    try:
        old,target,old_sha=_local_state(root,stage)
        now=int(time.time()) if asof_utc is None else asof_utc
        if type(now) is not int or now<=0:
            raise ValueError("STAGED_TIME_INVALID")
        urls,due,pending=_due_urls(target,now)
        report.update(source_file_sha256=old_sha,source_file_unchanged=True,
                      due_forecasts=due,stage_pending_before=pending,
                      planned_source_documents=len(urls))
        if not live:
            report["status"]="DRY_RUN_NO_NETWORK_NO_WRITE"
            return report
        if not urls:
            report["status"]="NO_DUE_ISOLATED_NBA_FORECASTS"
            return report
        rob=robots_fetcher(ROBOTS,limit=MAX_ROBOTS,expected_mime="text/plain")
        report.update(requests=1,
                      robots_http_status=rob.get("http_status"),
                      robots_status=rob.get("status"))
        if rob.get("status")!="DOCUMENT_RECEIVED":
            report["status"]="ABSTAIN_ESPN_ROBOTS_NOT_VERIFIED"
            return report
        policy=rob["body"].decode("utf-8","replace")
        if any(not allowed_by_robots(policy,url) for url in urls):
            report["status"]="ABSTAIN_ESPN_ROBOTS_DISALLOW"
            return report
        report["source_policy_verified"]=True
        allowed=frozenset(urls)
        blocked=False
        def bound_fetch(provider,url):
            nonlocal blocked
            if provider!="ESPN" or url not in allowed:
                raise ValueError("UNLISTED_NATIVE_ESPN_SOURCE_URL")
            if blocked:
                return dict(status="SOURCE_BLOCKED_AFTER_ACCESS_DENIAL")
            receipt=fetcher(provider,url)
            report["requests"]+=1
            if type(receipt) is dict and receipt.get("status") in (
                "SOURCE_ACCESS_DENIED","SOURCE_RATE_LIMITED",
                "SOURCE_HTTP_ERROR","SOURCE_REDIRECT_REFUSED"):
                blocked=True
            return receipt
        output=settle(LiveAnalysisLedger(target),fetcher=bound_fetch)
        report.update(
            stage_results_appended=output["settled"],
            source_unavailable_dates=output["unavailable_dates"],
            source_invalid_dates=output["invalid_dates"],
            stage_pending_after=output["pending"],
            status=("STAGE_NATIVE_CHECK_COMPLETED" if
                    output["status"]=="CHECKED" else
                    "STAGE_NATIVE_SOURCE_INCOMPLETE"))
        if _sha256_file(old)!=old_sha:
            raise ValueError("ORIGINAL_CHANGED_DURING_STAGE_SETTLEMENT")
    except (ValueError,KeyError,TypeError,sqlite3.Error,OSError) as exc:
        report.update(status="ABSTAIN_STAGED_NATIVE_SETTLEMENT_ERROR",
                      error_type=type(exc).__name__)
        if "target" in locals() and target.is_file():
            try:
                after=LedgerReports(target).read("NBA")
                report["stage_pending_after"]=after.get("pending")
                if type(report.get("stage_pending_before")) is int and type(after.get("pending")) is int:
                    report["stage_results_appended"]=max(
                        0,report["stage_pending_before"]-after["pending"])
            except (OSError,ValueError,sqlite3.Error):
                pass
        if "old" in locals() and old.is_file() and "old_sha" in locals():
            unchanged=_sha256_file(old)==old_sha
            report["source_file_unchanged"]=unchanged
            report["original_archive_modified"]=not unchanged
    return report


def run(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--staged-file",required=True)
    p.add_argument("--live",action="store_true")
    a=p.parse_args(argv)
    root=Path.home()/"zeynal-test-isolated"/"data"
    print(json.dumps(settle_isolated_stage(
        root=root,stage=a.staged_file,live=a.live),
        sort_keys=True,ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(run())

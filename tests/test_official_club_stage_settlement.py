"""Strict native ESPN postgame settlement on a copy only; no real HTTP."""
import json
from pathlib import Path
import time

from core.team_identity import digest
from hybrid_engine.official_club_final_staging import prepare_isolated_final_stage
from hybrid_engine.official_club_stage_settlement import settle_isolated_stage
from tests.test_official_club_fixture_outcome_audit import (
    ledger,native_event,START)


def _stage(tmp_path,*,with_result=False):
    root,original,_=ledger(tmp_path,valid_final=with_result)
    before=original.read_bytes()
    stage=prepare_isolated_final_stage(root=root)
    assert stage["status"]=="STAGE_COPY_READY_NO_NATIVE_FINAL_RECEIPTS"
    return root,original,before,stage["staged_file"]


def _robots_allowed(url,*,limit,expected_mime):
    assert url=="https://site.api.espn.com/robots.txt"
    assert expected_mime=="text/plain"
    return dict(status="DOCUMENT_RECEIVED",http_status=200,
                body=b"User-agent: *\nAllow: /\n")


def _fake_espn(provider,url):
    assert provider=="ESPN"
    assert "site.api.espn.com/" in url
    assert url.endswith("&limit=1000")
    events=[native_event()] if "dates=20261025" in url else []
    document={"events":events}
    now=int(time.time())
    return dict(status="DOCUMENT_RECEIVED",provider="ESPN",
                source_url=url,http_status=200,
                document=document,document_sha256=digest(document),
                observed_at_utc=now,ingested_at_utc=now)


def test_dry_run_no_http_and_no_write(tmp_path):
    root,original,before,stage=_stage(tmp_path)
    stage_before=Path(stage).read_bytes()
    def error(*args,**kwargs):
        raise AssertionError("Dry run called HTTP")
    r=settle_isolated_stage(root=root,stage=stage,live=False,
                            fetcher=error,robots_fetcher=error)
    assert r["status"]=="DRY_RUN_NO_NETWORK_NO_WRITE"
    assert r["due_forecasts"]==1
    assert r["planned_source_documents"]==3
    assert r["requests"]==0
    assert r["stage_results_appended"]==0
    assert original.read_bytes()==before
    assert Path(stage).read_bytes()==stage_before


def test_denied_robots_stops_before_scoreboard_and_sqlite_writes(tmp_path):
    root,original,before,stage=_stage(tmp_path)
    stage_before=Path(stage).read_bytes()
    def deny(*args,**kwargs):
        return dict(status="SOURCE_ACCESS_REFUSED",http_status=403)
    def must_not_call(*args,**kwargs):
        raise AssertionError("ESPN was fetched despite robots refusal")
    r=settle_isolated_stage(root=root,stage=stage,live=True,
                            robots_fetcher=deny,fetcher=must_not_call)
    assert r["status"]=="ABSTAIN_ESPN_ROBOTS_NOT_VERIFIED"
    assert r["requests"]==1
    assert r["stage_results_appended"]==0
    assert original.read_bytes()==before
    assert Path(stage).read_bytes()==stage_before


def test_robots_disallow_forbids_native_fetch(tmp_path):
    root,original,before,stage=_stage(tmp_path)
    def disallow(url,*,limit,expected_mime):
        return dict(status="DOCUMENT_RECEIVED",http_status=200,
                    body=b"User-agent: *\nDisallow: /apis/site/\n")
    def fail(*args,**kwargs):
        raise AssertionError("Forbidden provider query")
    r=settle_isolated_stage(root=root,stage=stage,live=True,
                            robots_fetcher=disallow,fetcher=fail)
    assert r["status"]=="ABSTAIN_ESPN_ROBOTS_DISALLOW"
    assert r["requests"]==1
    assert r["source_policy_verified"] is False
    assert original.read_bytes()==before


def test_native_final_appends_only_copy_once_then_idempotent(tmp_path):
    root,original,before,stage=_stage(tmp_path)
    r=settle_isolated_stage(root=root,stage=stage,live=True,
                            robots_fetcher=_robots_allowed,fetcher=_fake_espn)
    assert r["status"]=="STAGE_NATIVE_CHECK_COMPLETED"
    assert r["stage_results_appended"]==1
    assert r["stage_pending_before"]==1
    assert r["stage_pending_after"]==0
    assert r["requests"]==4
    assert r["source_policy_verified"] is True
    assert r["original_archive_modified"] is False
    assert original.read_bytes()==before
    again=settle_isolated_stage(root=root,stage=stage,live=True,
                                robots_fetcher=_robots_allowed,fetcher=_fake_espn)
    assert again["status"]=="NO_DUE_ISOLATED_NBA_FORECASTS"
    assert again["requests"]==0
    assert again["stage_results_appended"]==0
    assert original.read_bytes()==before


def test_source_denial_leaves_stage_pending_and_original_unchanged(tmp_path):
    root,original,before,stage=_stage(tmp_path)
    calls=[]
    def access_denied(provider,url):
        calls.append(url)
        return dict(status="SOURCE_ACCESS_DENIED",http_status=403)
    r=settle_isolated_stage(root=root,stage=stage,live=True,
                            robots_fetcher=_robots_allowed,
                            fetcher=access_denied)
    assert r["status"]=="STAGE_NATIVE_SOURCE_INCOMPLETE"
    assert r["stage_results_appended"]==0
    assert r["stage_pending_after"]==1
    assert len(calls)==1
    assert original.read_bytes()==before


def test_stage_path_or_source_sha_mismatch_is_rejected(tmp_path):
    root,original,before,stage=_stage(tmp_path)
    invalid=root/"live-nba"/"nba-hybrid.sqlite"
    r=settle_isolated_stage(root=root,stage=invalid,live=False)
    assert r["status"]=="ABSTAIN_STAGED_NATIVE_SETTLEMENT_ERROR"
    assert r["requests"]==0
    assert original.read_bytes()==before
    new=root/"club-pilot-evidence"/"final-staging"/("nba-final-staging-"+("0"*24)+".sqlite")
    new.write_bytes(Path(stage).read_bytes())
    r=settle_isolated_stage(root=root,stage=new,live=False)
    assert r["status"]=="ABSTAIN_STAGED_NATIVE_SETTLEMENT_ERROR"
    assert original.read_bytes()==before

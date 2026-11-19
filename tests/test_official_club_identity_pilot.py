"""No-network bounded ESPN team identity field pilot contract tests."""
import json
import time

from hybrid_engine.official_club_identity_pilot import (
    capture_nba_espn_identity,run)
from hybrid_engine.official_club_sources import registry
from providers.season_participants import participant_urls


def club(key="nba_denver_nuggets"):
    return next(x for x in registry() if x["club_key"]==key)


def bodies(*,official_name="Denver Nuggets",espn_id="7"):
    member_ref=("https://sports.core.api.espn.com/v2/sports/basketball/"
                "leagues/nba/seasons/2027/teams/"+espn_id)
    membership=dict(count=1,pageCount=1,pageIndex=1,
                    items=[{"$ref":member_ref}])
    names=dict(sports=[{"leagues":[{
        "slug":"nba","year":2027,"season":{"year":2027},
        "teams":[{"team":{
            "id":espn_id,"displayName":official_name,"abbreviation":"DEN",
            "shortDisplayName":official_name,"name":"Nuggets"}}]}]}])
    return membership,names


def fake_fetcher(membership,names,*,bad_robots=False,html_fail=False):
    endpoints=participant_urls("NBA",2026)
    calls=[]
    now=int(time.time())
    def requester(url,*,limit,expected_mime):
        calls.append(url)
        if url.endswith("/robots.txt"):
            if bad_robots:
                return dict(status="SOURCE_ACCESS_REFUSED",http_status=403)
            return dict(status="DOCUMENT_RECEIVED",http_status=200,
                        body=b"User-agent: *\nDisallow: /private")
        if url==endpoints["membership"]:
            return dict(status="DOCUMENT_RECEIVED",http_status=200,
                        observed_at_utc=now-2,
                        body=json.dumps(membership).encode("utf-8"))
        if url==endpoints["names"]:
            if html_fail:
                return dict(status="SOURCE_HTTP_OR_MIME_REFUSED",http_status=200)
            return dict(status="DOCUMENT_RECEIVED",http_status=200,
                        observed_at_utc=now-1,
                        body=json.dumps(names).encode("utf-8"))
        raise AssertionError("unapproved-url")
    return requester,calls,now


def test_official_nba_to_espn_ids_resolved_only_from_pinned_participant_sources():
    m,n=bodies()
    requester,calls,now=fake_fetcher(m,n)
    result=capture_nba_espn_identity(club(),requester=requester,now_utc=now)
    assert result["status"]=="READ_ONLY_TEAM_CROSSWALK_CANDIDATE"
    assert result["nba_com_team_id"]=="1610612743"
    assert result["espn_team_id"]=="7"
    assert result["requests"]==4
    assert len(calls)==4
    assert result["source_participant_snapshot_sha256"]
    assert result["verified_fixture_id"] is None
    assert result["verified_player_id"] is None
    assert result["model_input"] is False


def test_unverified_or_missing_team_name_must_refuse():
    m,n=bodies(official_name="Some Other Team")
    req,calls,now=fake_fetcher(m,n)
    result=capture_nba_espn_identity(club(),requester=req,now_utc=now)
    assert result["status"]=="ABSTAIN"
    assert result["reason"]=="ESPN_PARTICIPANT_OR_CROSSWALK_REFUSED"
    assert result["model_input"] is False
    assert len(calls)==4


def test_robots_error_refuses_before_fetch_and_without_bypass():
    m,n=bodies()
    req,calls,now=fake_fetcher(m,n,bad_robots=True)
    result=capture_nba_espn_identity(club(),requester=req,now_utc=now)
    assert result["status"]=="ABSTAIN"
    assert result["reason"]=="ESPN_ROBOTS_UNAVAILABLE_OR_REFUSED"
    assert result["requests"]==1
    assert len(calls)==1


def test_network_or_mime_error_refuses_no_extra_requests():
    m,n=bodies()
    req,calls,now=fake_fetcher(m,n,html_fail=True)
    result=capture_nba_espn_identity(club(),requester=req,now_utc=now)
    assert result["status"]=="ABSTAIN"
    assert result["reason"]=="SOURCE_HTTP_OR_MIME_REFUSED"
    assert result["requests"]==4
    assert len(calls)==4


def test_dry_run_does_not_access_network(monkeypatch,capsys):
    import hybrid_engine.official_club_identity_pilot as mod
    monkeypatch.setattr(mod,"capture_nba_espn_identity",
                        lambda _:1/0)
    assert run(["--club","nba_denver_nuggets"])==0
    row=json.loads(capsys.readouterr().out.strip())
    assert row["status"]=="DRY_RUN_ZERO_HTTP"
    assert row["requests"]==0
    assert row["model_input"] is False


def test_name_directory_season_mismatch_is_refused_not_30_team_fanout():
    m,n=bodies()
    n["sports"][0]["leagues"][0]["year"]=2026
    req,calls,now=fake_fetcher(m,n)
    result=capture_nba_espn_identity(club(),requester=req,now_utc=now)
    assert result["status"]=="ABSTAIN"
    assert result["requests"]==4
    assert len(calls)==4


def test_no_cross_team_mapping_on_boston_pilot():
    m,n=bodies(official_name="Denver Nuggets")
    req,calls,now=fake_fetcher(m,n)
    result=capture_nba_espn_identity(club("nba_boston_celtics"),
                                     requester=req,now_utc=now)
    assert result["status"]=="ABSTAIN"
    assert result["model_input"] is False


def test_transport_never_accepts_unlisted_espn_url_even_if_same_host():
    from hybrid_engine.official_club_identity_pilot import pinned_espn_request
    import pytest
    with pytest.raises(ValueError,match="UNLISTED_URL"):
        pinned_espn_request(
            "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams?limit=1000",
            limit=1024,expected_mime="application/json")
    with pytest.raises(ValueError,match="HOST_NOT_ALLOWLISTED"):
        pinned_espn_request("https://evil.example/robots.txt",
                            limit=1024,expected_mime="text/plain")



def test_robot_failure_names_first_source_and_transport_without_bypass():
    m,n=bodies()
    req,calls,now=fake_fetcher(m,n,bad_robots=True)
    result=capture_nba_espn_identity(club(),requester=req,now_utc=now)
    assert result["status"]=="ABSTAIN"
    assert result["requests"]==1
    assert result["failed_stage"]=="ROBOTS_POLICY_CHECK"
    assert result["failed_source_role"]=="membership"
    assert result["failed_source_host"]=="sports.core.api.espn.com"
    assert result["robots_transport_status"]=="SOURCE_ACCESS_REFUSED"
    assert result["robots_http_status"]==403
    assert result["robots_decision"]=="UNVERIFIED_NO_DATA_REQUEST"
    assert len(calls)==1
    assert result["model_input"] is False


def _offline_snapshot(now):
    from core.team_identity import digest,internal_team_id
    from core.league_identity import resolve_league
    spec=resolve_league("NBA")
    observed=now-120
    ingested=now-100
    pid="7"
    participant=dict(
        internal_id=internal_team_id(spec.identity_namespace,pid),
        league="NBA",provider="ESPN",provider_id=pid,
        official_name="Denver Nuggets",
        aliases=[dict(name="Denver Nuggets",kind="SOURCE_displayName",
                      language="und",valid_from_utc=observed,
                      valid_until_utc=None)])
    payload=dict(
        format="SEASON_PARTICIPANTS_V1",league_id="NBA",year=2026,
        season_id="2026/2027",participant_count=1,
        observed_at_utc=observed,ingested_at_utc=ingested,
        participants=[participant],
        source_pins={"membership":dict(
            url="https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/seasons/2027/teams?limit=100",
            document_sha256="f"*64,observed_at_utc=observed,
            ingested_at_utc=ingested)},
        membership_basis="SEASON_PARTICIPANT_ENDPOINT_NOT_GAME_SAMPLES",
        source_attestation="LOCAL_HASH_NOT_INDEPENDENT_ATTESTATION")
    return dict(payload=payload,sha256=digest(payload))


def test_offline_user_pinned_snapshot_crosswalk_makes_zero_network_calls(tmp_path):
    from hybrid_engine.official_club_identity_pilot import offline_nba_espn_identity
    now=int(time.time())
    root=tmp_path/"isolated"
    root.mkdir()
    folder=root/"nba"
    folder.mkdir()
    file=folder/"season_participants.json"
    snap=_offline_snapshot(now)
    file.write_text(json.dumps(snap))
    result=offline_nba_espn_identity(
        club(),path=str(file),local_root=root,
        trusted_snapshot_sha256=snap["sha256"],asof_utc=now)
    assert result["status"]=="OFFLINE_TEAM_CROSSWALK_CANDIDATE_ONLY"
    assert result["requests"]==0
    assert result["nba_com_team_id"]=="1610612743"
    assert result["espn_team_id"]=="7"
    assert result["model_input"] is False
    assert result["verified_fixture_id"] is None
    assert result["verified_player_id"] is None
    assert result["first_issued_forecast_proof_established"] is False


def test_unpinned_or_postcutoff_local_snapshot_cannot_be_accepted(tmp_path):
    from hybrid_engine.official_club_identity_pilot import offline_nba_espn_identity
    now=int(time.time())
    root=tmp_path/"isolated"
    root.mkdir()
    file=root/"season_participants.json"
    snap=_offline_snapshot(now)
    file.write_text(json.dumps(snap))
    badpin=offline_nba_espn_identity(
        club(),path=file,local_root=root,
        trusted_snapshot_sha256="0"*64,asof_utc=now)
    assert badpin["status"]=="ABSTAIN"
    assert badpin["model_input"] is False
    later=offline_nba_espn_identity(
        club(),path=file,local_root=root,
        trusted_snapshot_sha256=snap["sha256"],
        asof_utc=now-101)
    assert later["status"]=="ABSTAIN"
    assert later["reason"]=="SEASON_SOURCE_NOT_AVAILABLE_AT_FORECAST_CUTOFF"


def test_offline_snapshot_refuses_outside_root_and_symlink(tmp_path):
    from hybrid_engine.official_club_identity_pilot import offline_nba_espn_identity
    import pytest
    now=int(time.time())
    root=tmp_path/"isolated"
    root.mkdir()
    outside=tmp_path/"private.json"
    snap=_offline_snapshot(now)
    outside.write_text(json.dumps(snap))
    result=offline_nba_espn_identity(
        club(),path=outside,local_root=root,
        trusted_snapshot_sha256=snap["sha256"],asof_utc=now)
    assert result["status"]=="ABSTAIN"
    assert result["reason"]=="ISOLATED_SNAPSHOT_PATH_REQUIRED"
    link=root/"linked.json"
    link.symlink_to(outside)
    result=offline_nba_espn_identity(
        club(),path=link,local_root=root,
        trusted_snapshot_sha256=snap["sha256"],asof_utc=now)
    assert result["status"]=="ABSTAIN"
    assert result["reason"]=="ISOLATED_SNAPSHOT_SYMLINK_REFUSED"


def test_offline_cli_requires_sha_and_explicit_cutoff_before_any_file_access(capsys):
    import pytest
    with pytest.raises(SystemExit) as e:
        run(["--club","nba_denver_nuggets",
             "--offline-snapshot","/does-not-exist"])
    assert e.value.code==2



def test_offline_inventory_finds_candidate_without_promoting_self_reported_sha(tmp_path):
    from hybrid_engine.official_club_identity_pilot import inspect_local_season_snapshot_candidates
    root=tmp_path/"isolated"
    folder=root/"nba"
    folder.mkdir(parents=True)
    now=int(time.time())
    snap=_offline_snapshot(now)
    (folder/"season-participants.json").write_text(json.dumps(snap))
    (folder/"ordinary-result-ledger.json").write_text('{"fixture_id": "not participants"}')
    report=inspect_local_season_snapshot_candidates(root=root)
    assert report["status"]=="LOCAL_IDENTITY_SOURCE_CANDIDATES_UNVERIFIED"
    assert len(report["candidate_files"])==1
    assert report["candidate_files"][0]["relative_path"]=="nba/season-participants.json"
    assert report["candidate_files"][0]["status"]=="UNTRUSTED_SNAPSHOT_CANDIDATE_NOT_ASOF_PROOF"
    assert report["snapshot_sha_independently_pinned"] is False
    assert report["historical_pregame_proof"] is False
    assert report["requests"]==0
    assert report["model_input"] is False


def test_offline_inventory_empty_does_not_claim_no_team_records_anywhere(tmp_path):
    from hybrid_engine.official_club_identity_pilot import inspect_local_season_snapshot_candidates
    root=tmp_path/"isolated"
    root.mkdir()
    report=inspect_local_season_snapshot_candidates(root=root)
    assert report["status"]=="NO_IDENTITY_SOURCE_FOUND_IN_SCANNED_LOCAL_SCOPE"
    assert report["candidate_files"]==[]
    assert report["requests"]==0


def test_offline_inventory_does_not_follow_external_symlinks(tmp_path):
    from hybrid_engine.official_club_identity_pilot import inspect_local_season_snapshot_candidates
    root=tmp_path/"isolated"
    root.mkdir()
    outside=tmp_path/"outside"
    outside.mkdir()
    (outside/"season.json").write_text(json.dumps(_offline_snapshot(int(time.time()))))
    (root/"external").symlink_to(outside,target_is_directory=True)
    report=inspect_local_season_snapshot_candidates(root=root)
    assert report["candidate_files"]==[]
    assert report["requests"]==0


def test_scan_local_cli_requires_no_web_and_never_uses_trusted_asof(monkeypatch,capsys):
    import hybrid_engine.official_club_identity_pilot as mod
    import pytest
    monkeypatch.setattr(mod,"capture_nba_espn_identity",lambda _:1/0)
    monkeypatch.setattr(mod,"inspect_local_season_snapshot_candidates",
                        lambda:dict(status="NO_IDENTITY_SOURCE_FOUND_IN_SCANNED_LOCAL_SCOPE",
                                    candidate_files=[],requests=0,model_input=False))
    assert run(["--club","nba_denver_nuggets","--scan-local"])==0
    data=json.loads(capsys.readouterr().out.strip())
    assert data["status"]=="NO_IDENTITY_SOURCE_FOUND_IN_SCANNED_LOCAL_SCOPE"
    with pytest.raises(SystemExit) as e:
        run(["--club","nba_denver_nuggets","--scan-local","--live"])
    assert e.value.code==2


def test_inspect_db_schema_cli_never_fetches_espn_or_reads_json(monkeypatch,capsys):
    import hybrid_engine.official_club_identity_pilot as mod
    import hybrid_engine.official_club_local_inventory as inventory
    import pytest
    monkeypatch.setattr(mod,"capture_nba_espn_identity",lambda _:1/0)
    monkeypatch.setattr(inventory,"inspect_local_source_inventory",lambda **kwargs:1/0)
    monkeypatch.setattr(inventory,"inspect_known_database_columns",
        lambda **kwargs:dict(
            format="OFFICIAL_CLUB_LOCAL_DB_SCHEMA_DETAIL_V1",
            status="NO_KNOWN_SQLITE_SCHEMAS_OBSERVED",
            inspected_tables=[],requests=0,
            model_input=False,production_changed=False))
    assert run(["--club","nba_denver_nuggets","--inspect-db-schema"])==0
    d=json.loads(capsys.readouterr().out.strip())
    assert d["requests"]==0
    assert d["status"]=="NO_KNOWN_SQLITE_SCHEMAS_OBSERVED"
    assert d["model_input"] is False
    with pytest.raises(SystemExit) as e:
        run(["--club","nba_denver_nuggets","--inspect-db-schema",
             "--scan-local"])
    assert e.value.code==2



def test_frozen_receipt_audit_cli_never_fetches_provider_or_scans_json(monkeypatch,capsys):
    import pytest
    import hybrid_engine.official_club_identity_pilot as mod
    import hybrid_engine.official_club_frozen_receipt_audit as audit
    monkeypatch.setattr(mod,"capture_nba_espn_identity",lambda _:1/0)
    monkeypatch.setattr(mod,"inspect_local_season_snapshot_candidates",lambda:1/0)
    monkeypatch.setattr(audit,"audit_isolated_nba_frozen_receipts",
        lambda **kwargs:dict(
            format="OFFICIAL_CLUB_FROZEN_RECEIPTS_AUDIT_V1",
            status="NO_CONFIRMED_NBA_FROZEN_SNAPSHOTS_IN_THIS_DB",
            candidate_rows=0,verified_local_receipts=0,
            requests=0,model_input=False,production_changed=False))
    assert run(["--club","nba_denver_nuggets","--audit-frozen-receipts"])==0
    result=json.loads(capsys.readouterr().out.strip())
    assert result["requests"]==0
    assert result["verified_local_receipts"]==0
    assert result["model_input"] is False
    with pytest.raises(SystemExit) as exc:
        run(["--club","nba_denver_nuggets","--audit-frozen-receipts","--live"])
    assert exc.value.code==2

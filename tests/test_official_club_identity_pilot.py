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

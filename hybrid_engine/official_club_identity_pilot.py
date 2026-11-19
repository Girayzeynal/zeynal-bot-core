"""Opt-in, bounded ESPN/NBA.com team identity crosswalk field pilot.

Strict 2 fixed 2026/27 ESPN season member/name URLs. Each host's robots.txt
must permit access. No fallback to a 30-team historical fanout. HTML/JSON
not persisted. Output only a candidate team-ID bridge with observed source
timestamps and SHA pins; no player IDs, fixtures or model input.

Invocation:
 python -B -m hybrid_engine.official_club_identity_pilot --live --club nba_denver_nuggets
"""
import argparse
import json
import time
from urllib.parse import urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from hybrid_engine.official_club_sources import (
    _bounded_https, NoRedirect, USER_AGENT, TIMEOUT_SECONDS)

from core.team_identity import digest
from providers.season_participants import parse_participants,participant_urls
from hybrid_engine.official_club_sources import (
    registry, _request, allowed_by_robots, MAX_ROBOTS, MAX_BODY)
from hybrid_engine.official_club_team_crosswalk import audit_nba_team_crosswalk

FORMAT="OFFICIAL_NBA_ESPN_TEAM_IDENTITY_FIELD_V1"
HOSTS=frozenset(("site.api.espn.com","sports.core.api.espn.com"))


def pinned_espn_request(url,*,limit,expected_mime):
    # Existing general-purpose official-club transport correctly rejects
    # query strings. ESPN's two *fixed* first-party membership endpoints use
    # ?limit=100, so accept ONLY these exact URLs here, without broadening
    # the generic transport and its security policy.
    if url.endswith("/robots.txt"):
        _bounded_https(url)
        if urlsplit(url).hostname not in HOSTS:
            raise ValueError("ESPN_ROBOTS_HOST_NOT_ALLOWLISTED")
        return _request(url,limit=limit,expected_mime=expected_mime)
    if url not in frozenset(participant_urls("NBA",2026).values()):
        raise ValueError("ESPN_PARTICIPANT_UNLISTED_URL_REFUSED")
    req=Request(url,headers={"User-Agent":USER_AGENT,"Accept":expected_mime})
    try:
        with build_opener(NoRedirect).open(req,timeout=TIMEOUT_SECONDS) as response:
            status=response.status
            mime=response.headers.get_content_type()
            body=response.read(limit+1)
            if len(body)>limit:
                return dict(status="SOURCE_SIZE_LIMIT",http_status=status)
            if status!=200 or mime!=expected_mime:
                return dict(status="SOURCE_HTTP_OR_MIME_REFUSED",http_status=status)
            return dict(status="DOCUMENT_RECEIVED",http_status=200,body=body,
                        observed_at_utc=int(time.time()))
    except HTTPError as exc:
        return dict(status=("SOURCE_RATE_LIMITED" if exc.code==429 else
                            "SOURCE_ACCESS_REFUSED" if exc.code in (401,403) else
                            "SOURCE_REDIRECT_REFUSED" if exc.code in (301,302,303,307,308) else
                            "SOURCE_HTTP_ERROR"),http_status=exc.code)
    except (URLError,TimeoutError,OSError):
        return dict(status="SOURCE_NETWORK_ERROR")


def capture_nba_espn_identity(club, *, requester=pinned_espn_request, now_utc=None):
    if (type(club) is not dict or club.get("club_key") not in
        ("nba_denver_nuggets","nba_boston_celtics")):
        raise ValueError("NBA_ESP_IDENTITY_TWO_TEAM_PILOT_ONLY")
    now=int(time.time()) if now_utc is None else now_utc
    if type(now) is not int or now<=0:
        raise ValueError("ESPN_TEAM_IDENTITY_OBSERVATION_CLOCK")
    documents={}
    requests=0
    for name,url in participant_urls("NBA",2026).items():
        host=urlsplit(url).hostname
        if host not in HOSTS:
            raise ValueError("ESPN_PARTICIPANT_SOURCE_HOST_REFUSED")
        robots_url="https://"+host+"/robots.txt"
        robots=requester(robots_url,limit=MAX_ROBOTS,expected_mime="text/plain")
        requests+=1
        if robots.get("status")!="DOCUMENT_RECEIVED":
            if robots.get("http_status") not in (404,410):
                return dict(format=FORMAT,status="ABSTAIN",
                            reason="ESPN_ROBOTS_UNAVAILABLE_OR_REFUSED",
                            club_key=club["club_key"],requests=requests,
                            model_input=False,production_changed=False)
        elif not allowed_by_robots(robots["body"].decode("utf-8","replace"),url):
            return dict(format=FORMAT,status="ABSTAIN",
                        reason="ESPN_ROBOTS_DISALLOW",
                        club_key=club["club_key"],requests=requests,
                        model_input=False,production_changed=False)
        result=requester(url,limit=MAX_BODY,expected_mime="application/json")
        requests+=1
        if result.get("status")!="DOCUMENT_RECEIVED":
            return dict(format=FORMAT,status="ABSTAIN",
                        reason=result.get("status","ESPN_JSON_UNAVAILABLE"),
                        club_key=club["club_key"],requests=requests,
                        model_input=False,production_changed=False)
        observed=result.get("observed_at_utc")
        if (type(observed) is not int or observed<=0 or
            observed>now+30 or now-observed>120):
            return dict(format=FORMAT,status="ABSTAIN",
                        reason="ESPN_SOURCE_OBSERVATION_CLOCK_INVALID",
                        club_key=club["club_key"],requests=requests,
                        model_input=False,production_changed=False)
        try:
            document=json.loads(result["body"].decode("utf-8"))
        except (ValueError,UnicodeError,TypeError,AttributeError):
            return dict(format=FORMAT,status="ABSTAIN",
                        reason="ESPN_JSON_BODY_INVALID",
                        club_key=club["club_key"],requests=requests,
                        model_input=False,production_changed=False)
        documents[name]=dict(
            provider="ESPN",source_url=url,status="DOCUMENT_RECEIVED",
            http_status=200,document=document,
            observed_at_utc=observed,ingested_at_utc=max(observed,now),
            document_sha256=digest(document))
    # Explicitly NO historical fallback and no retrospective as-of claims.
    try:
        snapshot=parse_participants("NBA",2026,documents)
        bridge=audit_nba_team_crosswalk(
            club,snapshot,trusted_snapshot_sha256=snapshot["sha256"],
            asof_utc=max(now,max(v["ingested_at_utc"] for v in documents.values())))
    except (ValueError,TypeError,KeyError,OverflowError) as exc:
        return dict(format=FORMAT,status="ABSTAIN",
                    reason="ESPN_PARTICIPANT_OR_CROSSWALK_REFUSED",
                    detail=str(exc)[:100],club_key=club["club_key"],
                    requests=requests,model_input=False,
                    production_changed=False)
    return dict(format=FORMAT,
                status="READ_ONLY_TEAM_CROSSWALK_CANDIDATE",
                club_key=club["club_key"],league="NBA",
                nba_com_team_id=bridge["nba_com_team_id"],
                espn_team_id=bridge["espn_team_id"],
                official_team_name=bridge["source_name"],
                source_participant_snapshot_sha256=snapshot["sha256"],
                source_observed_utc=max(v["observed_at_utc"] for v in documents.values()),
                source_ingested_utc=max(v["ingested_at_utc"] for v in documents.values()),
                observed_asof_is_not_historical_proof=True,
                requests=requests,
                verified_fixture_id=None,verified_player_id=None,
                source_attestation="LOCAL_HASH_NOT_INDEPENDENT_PROVIDER_SIGNATURE",
                model_input=False,production_changed=False)


def run(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--live",action="store_true")
    p.add_argument("--club",required=True,choices=[
        "nba_denver_nuggets","nba_boston_celtics"])
    a=p.parse_args(argv)
    club=next(x for x in registry() if x["club_key"]==a.club)
    if not a.live:
        r=dict(format=FORMAT,status="DRY_RUN_ZERO_HTTP",
               club_key=a.club,requests=0,
               model_input=False,production_changed=False)
    else:
        r=capture_nba_espn_identity(club)
    print(json.dumps(r,ensure_ascii=False,sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(run())

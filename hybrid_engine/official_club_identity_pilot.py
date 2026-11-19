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
import re
import os
from pathlib import Path
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
                            failed_stage="ROBOTS_POLICY_CHECK",
                            failed_source_role=name,
                            failed_source_host=host,
                            robots_transport_status=robots.get("status"),
                            robots_http_status=robots.get("http_status"),
                            robots_decision="UNVERIFIED_NO_DATA_REQUEST",
                            club_key=club["club_key"],requests=requests,
                            model_input=False,production_changed=False)
        elif not allowed_by_robots(robots["body"].decode("utf-8","replace"),url):
            return dict(format=FORMAT,status="ABSTAIN",
                        reason="ESPN_ROBOTS_DISALLOW",
                        failed_stage="ROBOTS_POLICY_CHECK",
                        failed_source_role=name,
                        failed_source_host=host,
                        robots_transport_status=robots.get("status"),
                        robots_http_status=robots.get("http_status"),
                        robots_decision="DISALLOWED_NO_DATA_REQUEST",
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


_SNAPSHOT_SHA=re.compile(r"^[0-9a-f]{64}$")
_LOCAL_ROOT=(Path.home()/"zeynal-test-isolated"/"data").absolute()
_MAX_LOCAL_SNAPSHOT_BYTES=4*1024*1024


def offline_nba_espn_identity(club,*,path, trusted_snapshot_sha256,
                              asof_utc, local_root=None):
    """Read a user-selected prior season participant bundle; ZERO network.

    The SHA is an externally supplied pin; do NOT calculate a fresh 'trusted'
    SHA from the same untrusted file as if it were independent evidence.
    Local source timestamps are not secure third-party time attestations.
    """
    root=_LOCAL_ROOT if local_root is None else Path(local_root).expanduser().absolute()
    file=Path(path).expanduser().absolute()
    base=dict(format=FORMAT,club_key=club["club_key"],
              requests=0,model_input=False,production_changed=False,
              source_mode="OFFLINE_USER_PINNED_SEASON_SNAPSHOT")
    if (type(trusted_snapshot_sha256) is not str or
        not _SNAPSHOT_SHA.fullmatch(trusted_snapshot_sha256) or
        type(asof_utc) is not int or asof_utc<=0):
        return dict(base,status="ABSTAIN",reason="INDEPENDENT_SHA_AND_ASOF_REQUIRED")
    try:
        if file.suffix!=".json" or not file.is_relative_to(root):
            raise ValueError("ISOLATED_SNAPSHOT_PATH_REQUIRED")
        if any(n.is_symlink() for n in (file,*file.parents) if
               n==file or n.is_relative_to(root)):
            raise ValueError("ISOLATED_SNAPSHOT_SYMLINK_REFUSED")
        if not file.is_file() or file.stat().st_size>_MAX_LOCAL_SNAPSHOT_BYTES:
            raise ValueError("ISOLATED_SNAPSHOT_NOT_PRESENT_OR_TOO_LARGE")
        data=json.loads(file.read_bytes())
        bridge=audit_nba_team_crosswalk(
            club,data,trusted_snapshot_sha256=trusted_snapshot_sha256,
            asof_utc=asof_utc)
    except (OSError,UnicodeError,ValueError,TypeError,KeyError,
            OverflowError,RecursionError) as exc:
        # Don't expose untrusted filesystem or document contents.
        code=str(exc)
        reason=(code if code in (
            "ISOLATED_SNAPSHOT_PATH_REQUIRED",
            "ISOLATED_SNAPSHOT_SYMLINK_REFUSED",
            "ISOLATED_SNAPSHOT_NOT_PRESENT_OR_TOO_LARGE",
            "PARTICIPANT_SNAPSHOT_TRUST_ANCHOR_REQUIRED",
            "SEASON_SOURCE_NOT_AVAILABLE_AT_FORECAST_CUTOFF",
            "NBA_ESP_TEAM_NAME_NOT_UNIQUELY_MATCHED") else
            "PINNED_SEASON_SNAPSHOT_VALIDATION_REFUSED")
        return dict(base,status="ABSTAIN",reason=reason)
    return dict(base,status="OFFLINE_TEAM_CROSSWALK_CANDIDATE_ONLY",
                nba_com_team_id=bridge["nba_com_team_id"],
                espn_team_id=bridge["espn_team_id"],
                season=bridge["season"],league="NBA",
                source_participant_snapshot_sha256=trusted_snapshot_sha256,
                source_participant_ingested_at_utc=bridge[
                    "source_participant_ingested_at_utc"],
                asof_utc=asof_utc,
                first_issued_forecast_proof_established=False,
                verified_fixture_id=None,verified_player_id=None,
                source_attestation="LOCAL_HASH_NOT_INDEPENDENT_PROVIDER_SIGNATURE")


def inspect_local_season_snapshot_candidates(*,root=None):
    """Zero-network bounded scan: finds only possible old season bundles.

    A scanned JSON's own SHA field is *not* an independent prior trust pin.
    Do not feed scanner output directly into as-of forecast gating.
    """
    base=_LOCAL_ROOT if root is None else Path(root).expanduser().absolute()
    report=dict(format=FORMAT,status="LOCAL_SNAPSHOT_INVENTORY_ONLY",
                source_mode="LOCAL_ISOLATED_JSON_SCAN",
                scanned_json_files=0,scan_capped=False,candidate_files=[],
                snapshot_sha_independently_pinned=False,
                historical_pregame_proof=False,requests=0,model_input=False,
                production_changed=False)
    if not base.is_dir() or base.is_symlink():
        report["status"]="LOCAL_ISOLATED_DATA_ROOT_UNAVAILABLE"
        return report
    max_files=500
    max_bytes=16*1024*1024
    budget=0
    for current,dirs,files in os.walk(base,followlinks=False):
        folder=Path(current)
        if len(folder.relative_to(base).parts)>4:
            dirs[:]=[]
            continue
        dirs[:]=sorted(x for x in dirs if not (folder/x).is_symlink())
        for name in sorted(files):
            if not name.endswith(".json"):
                continue
            if report["scanned_json_files"]>=max_files or budget>=max_bytes:
                report["scan_capped"]=True
                break
            file=folder/name
            if file.is_symlink():
                continue
            report["scanned_json_files"]+=1
            try:
                n=file.stat().st_size
                if n<=0 or n>_MAX_LOCAL_SNAPSHOT_BYTES or n>max_bytes-budget:
                    continue
                # Avoid full JSON reads for ordinary ledgers/source samples.
                with file.open("rb") as fh:
                    head=fh.read(8192)
                if b"SEASON_PARTICIPANTS_V1" not in head:
                    continue
                budget+=n
                data=json.loads(file.read_bytes())
                if (not isinstance(data,dict) or
                    not isinstance(data.get("payload"),dict) or
                    data["payload"].get("format")!="SEASON_PARTICIPANTS_V1" or
                    data["payload"].get("league_id")!="NBA" or
                    data["payload"].get("season_id")!="2026/2027"):
                    continue
                report["candidate_files"].append(dict(
                    relative_path=str(file.relative_to(base)),
                    claimed_snapshot_sha256=data.get("sha256"),
                    source_ingested_at_utc=data["payload"].get("ingested_at_utc"),
                    status="UNTRUSTED_SNAPSHOT_CANDIDATE_NOT_ASOF_PROOF"))
                if len(report["candidate_files"])>=10:
                    report["scan_capped"]=True
                    break
            except (OSError,ValueError,UnicodeError,TypeError):
                continue
        if report["scan_capped"]:
            break
    if report["candidate_files"]:
        report["status"]="LOCAL_SNAPSHOT_CANDIDATES_REQUIRE_INDEPENDENT_PIN"
    else:
        report["status"]="NO_LOCAL_SEASON_SNAPSHOT_IN_BOUNDED_SCAN"
    return report


def run(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    mode=p.add_mutually_exclusive_group()
    mode.add_argument("--live",action="store_true")
    mode.add_argument("--offline-snapshot",
                      help="Existing 2026/27 season-participant JSON under ~/zeynal-test-isolated/data")
    mode.add_argument("--scan-local",action="store_true",
                      help="Bounded no-network inventory of existing 2026/27 NBA season snapshots; does not trust self-reported pins")
    p.add_argument("--trusted-sha256",
                   help="SHA256 independently pinned before this offline run")
    p.add_argument("--asof-utc",type=int,
                   help="Unix UTC second cutoff; never infer a historical timestamp")
    p.add_argument("--club",required=True,choices=[
        "nba_denver_nuggets","nba_boston_celtics"])
    a=p.parse_args(argv)
    club=next(x for x in registry() if x["club_key"]==a.club)
    if a.scan_local:
        if a.trusted_sha256 is not None or a.asof_utc is not None:
            p.error("--scan-local has no source pin or historical cutoff; inventory only")
        r=inspect_local_season_snapshot_candidates()
    elif a.offline_snapshot:
        if a.trusted_sha256 is None or a.asof_utc is None:
            p.error("--offline-snapshot requires --trusted-sha256 and --asof-utc")
        r=offline_nba_espn_identity(
            club,path=a.offline_snapshot,
            trusted_snapshot_sha256=a.trusted_sha256,asof_utc=a.asof_utc)
    elif a.live:
        if a.trusted_sha256 is not None or a.asof_utc is not None:
            p.error("--trusted-sha256 and --asof-utc are offline-only")
        r=capture_nba_espn_identity(club)
    else:
        if a.trusted_sha256 is not None or a.asof_utc is not None:
            p.error("--trusted-sha256 and --asof-utc require --offline-snapshot")
        r=dict(format=FORMAT,status="DRY_RUN_ZERO_HTTP",
               club_key=a.club,requests=0,
               model_input=False,production_changed=False)
    print(json.dumps(r,ensure_ascii=False,sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(run())

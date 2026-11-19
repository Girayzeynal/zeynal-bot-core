"""Single-command, all-82 official basketball club website/news intake.

2026/27 NBA 30 + EuroLeague 20 + EuroCup 32. This is one COMPLETE
season-scoped entry-point registry, not 82 confirmed team medical feeds.
No hidden background job, write, prediction, archive, roster or model
change. Live probes are explicit opt-in, robots gated, no redirects,
one index/home URL per club, bounded and grouped by source host.
"""
import argparse
from collections import Counter,defaultdict
import json
from pathlib import Path
import time
from urllib.parse import urlsplit

from hybrid_engine.official_club_coverage import load_coverage
from hybrid_engine.official_club_sources import (
    MAX_BODY,MAX_ROBOTS,_bounded_https,_pin,_request,allowed_by_robots,
    parse_metadata,registry as pilot_registry)

FORMAT="ZEYNAL_OFFICIAL_ALL_82_CLUB_SITE_AND_NEWS_CANDIDATES_V1"
RESULT_FORMAT="ZEYNAL_OFFICIAL_ALL_82_BATCH_PROBE_V1"
MANIFEST=Path(__file__).with_name("official_all_82_club_urls_2026_27.json")
EXPECTED={"NBA":30,"EUROLEAGUE":20,"EUROCUP":32}
MAX_REQUESTS=164
MAX_SECONDS=900
_SPECIAL_NEWS_HOSTS={
    "euroleague_fc_bayern_munich":("fcbayern.com","app.fcbayern.com"),
}

def _host_family(host):
    return host.removeprefix("www.")

def load_all_82(path=MANIFEST):
    obj=json.loads(Path(path).read_text(encoding="utf-8"))
    records=obj.get("records")
    if (obj.get("format")!=FORMAT or
        obj.get("league_season")!="2026/2027" or
        type(records) is not list or len(records)!=82 or
        obj.get("scope_counts")!=EXPECTED):
        raise ValueError("ALL_82_COVERAGE_MANIFEST_INVALID")
    roster=load_coverage()
    known={r["club_key"]:r for r in roster["teams"]}
    six={r["club_key"]:r for r in pilot_registry()}
    if len(known)!=82 or len(six)!=6:
        raise ValueError("ALL_82_SEASON_SCOPE_INCONSISTENT")
    counts=Counter();seen=set()
    for r in records:
        required=("league","season","club_key","official_team_name",
            "official_site_url","official_news_entry_url",
            "news_entry_kind","source_evidence_class","club_ownership_evidence_url",
            "live_http_status","robots_status","player_identity_verified",
            "fixture_identity_verified","injury_or_lineup_verified","model_input")
        if type(r) is not dict or any(k not in r for k in required):
            raise ValueError("ALL_82_ENTRY_FIELDS_REQUIRED")
        key=r["club_key"]
        if key not in known or key in seen:
            raise ValueError("ALL_82_TEAM_KEY_DUPLICATE_OR_UNKNOWN")
        seen.add(key)
        expected=known[key]
        if (r["league"]!=expected["league"] or
            r["official_team_name"]!=expected["team_name"] or
            r["season"]!="2026/2027" or
            r["club_ownership_evidence_url"]!=expected["membership_evidence_url"]):
            raise ValueError("ALL_82_SEASON_MEMBERSHIP_IDENTITY_CONFLICT")
        if (r["model_input"] is not False or
            r["injury_or_lineup_verified"] is not False or
            r["fixture_identity_verified"] is not False or
            r["player_identity_verified"] is not False or
            r["live_http_status"]!="NOT_CHECKED_IN_UNIFIED_82_BATCH" or
            r["robots_status"]!="NOT_CHECKED_IN_UNIFIED_82_BATCH"):
            raise ValueError("ALL_82_UNVERIFIED_SOURCE_MUST_NOT_PROMOTE_PLAYER")
        site=_bounded_https(r["official_site_url"])
        news=_bounded_https(r["official_news_entry_url"])
        _bounded_https(r["club_ownership_evidence_url"])
        if r["news_entry_kind"] not in (
            "DIRECT_NEWS","HOME_HAS_NEWS","HOME_HAS_LATEST_NEWS",
            "HOME_CLOUDFLARE_VERIFICATION","HOME_HAS_NEWS_WEB_ACCESS_RESTRICTED","DIRECT_NEWS_BLOCKED_ON_WEB_FETCH"):
            raise ValueError("ALL_82_INVALID_NEWS_ENTRY_CLASS")
        if (site.hostname!=news.hostname and
            _host_family(site.hostname)!=_host_family(news.hostname) and
            (site.hostname,news.hostname)!=_SPECIAL_NEWS_HOSTS.get(key)):
            raise ValueError("ALL_82_SITE_NEWS_HOST_RELATION_INVALID")
        if r["league"]=="NBA":
            if site.hostname!="www.nba.com":
                raise ValueError("ALL_82_NBA_NEWS_MUST_BE_NBA_OFFICIAL_HOST")
            prefix=site.path.rstrip("/")
            if (not prefix or prefix=="/" or
                not (news.path==prefix or news.path.startswith(prefix+"/"))):
                raise ValueError("ALL_82_NBA_NEWS_TEAM_PATH_MISMATCH")
        if key in six and r["official_news_entry_url"]!=six[key]["source_url"]:
            raise ValueError("ALL_82_ORIGINAL_PILOT_SITE_CHALLENGED")
        if key=="euroleague_paris_basketball":
            if site.hostname!="parisbasketball.com":
                raise ValueError("ALL_82_PARIS_MEDIA_IMPERSONATION")
        counts[r["league"]]+=1
    if dict(counts)!=EXPECTED or seen!=set(known):
        raise ValueError("ALL_82_NOT_EXHAUSTIVE")
    roma=[r for r in records if r["club_key"] in
          ("eurocup_maxima_roma","eurocup_roma_basketball")]
    if len(roma)!=2 or len({urlsplit(x["official_site_url"]).hostname
                            for x in roma})!=2:
        raise ValueError("ALL_82_ROMA_TEAMS_MUST_BE_DISTINCT")
    return tuple(records)

def _base_row(r):
    return dict(league=r["league"],club_key=r["club_key"],
        team_name=r["official_team_name"],
        official_site_url=r["official_site_url"],
        official_news_entry_url=r["official_news_entry_url"],
        news_entry_kind=r["news_entry_kind"],
        source_evidence_class=r["source_evidence_class"],
        player_identity_verified=False,injury_status_verified=False,
        lineup_verified=False,publication_time_verified=False,
        model_input=False)

def _transport_state(result):
    if type(result) is not dict:
        return "INVALID_TRANSPORT_RECEIPT"
    return str(result.get("status","NO_TRANSPORT_STATUS"))[:90]

def batch_probe(*,live=False,requester=_request,monotonic=time.monotonic,
                deadline_seconds=MAX_SECONDS):
    entries=load_all_82()
    totals={k:0 for k in EXPECTED}
    reports=[_base_row(r) for r in entries]
    for r in entries:
        totals[r["league"]]+=1
    output=dict(format=RESULT_FORMAT,season="2026/2027",
        scope="82_OFFICIAL_SITE_NEWS_ENTRY_POINTS_NEVER_PLAYER_STATUS_PROOF",
        registry_size=len(entries),league_counts=totals,
        live_probe_requested=bool(live),source_http_requests=0,
        distinct_news_hosts=len({urlsplit(r["official_news_entry_url"]).hostname
                                 for r in entries}),
        source_observed_count=0,source_blocked_or_unavailable_count=0,
        unattempted_count=82,scan_complete=False,scan_capped=False,
        player_injury_feed_connected_count=0,verified_player_count=0,
        official_player_injury_status_verified=False,
        official_team_lineup_verified=False,model_input=False,
        archives_modified=False,production_changed=False,
        results=reports)
    if not live:
        for row in reports:
            row["status"]="URL_REGISTERED_NOT_LIVE_CHECKED"
        output["status"]="ALL_82_URLS_REGISTERED_ZERO_NETWORK"
        return output
    if type(deadline_seconds) not in (int,float) or not 0<deadline_seconds<=MAX_SECONDS:
        raise ValueError("BATCH_TIME_BUDGET_REQUIRED")
    began=monotonic()
    per_host=defaultdict(list)
    for index,entry in enumerate(entries):
        host=urlsplit(entry["official_news_entry_url"]).hostname
        per_host[host].append(index)
    # One robots policy check per exact news host; no parallel requests
    # to one host. Full registry processed in one CLI invocation.
    for host in sorted(per_host,key=lambda h:(-len(per_host[h]),h)):
        indices=per_host[host]
        if output["source_http_requests"]>=MAX_REQUESTS or (
            monotonic()-began>=deadline_seconds):
            output["scan_capped"]=True
            for i in indices:
                reports[i]["status"]="NOT_ATTEMPTED_BATCH_BUDGET"
            continue
        robots_url="https://"+host+"/robots.txt"
        robots=requester(robots_url,limit=MAX_ROBOTS,
                         expected_mime="text/plain")
        output["source_http_requests"]+=1
        is_robots_ok=(type(robots) is dict and
                       robots.get("status")=="DOCUMENT_RECEIVED" and
                       type(robots.get("body")) is bytes and
                       len(robots["body"])<=MAX_ROBOTS)
        policy=(robots["body"].decode("utf-8","replace")
                if is_robots_ok else None)
        for i in indices:
            row=reports[i]
            if monotonic()-began>=deadline_seconds or (
                    output["source_http_requests"]>=MAX_REQUESTS):
                output["scan_capped"]=True
                row["status"]="NOT_ATTEMPTED_BATCH_BUDGET"
                continue
            if not is_robots_ok:
                row["status"]="ROBOTS_UNAVAILABLE_OR_REFUSED_NO_NEWS_FETCH"
                row["robots_transport_status"]=_transport_state(robots)
                row["robots_http_status"]=(robots.get("http_status")
                                           if type(robots) is dict else None)
                continue
            url=row["official_news_entry_url"]
            try: allowed=allowed_by_robots(policy,url)
            except (ValueError,TypeError): allowed=False
            if not allowed:
                row["status"]="ROBOTS_DISALLOW_NO_NEWS_FETCH"
                continue
            response=requester(url,limit=MAX_BODY,expected_mime="text/html")
            output["source_http_requests"]+=1
            if (type(response) is not dict or
                response.get("status")!="DOCUMENT_RECEIVED"):
                row["status"]="NEWS_INDEX_HTTP_OR_MIME_REFUSED"
                row["page_transport_status"]=_transport_state(response)
                row["source_http_status"]=(response.get("http_status")
                    if type(response) is dict else None)
                continue
            body=response.get("body")
            observed=response.get("observed_at_utc")
            if (type(body) is not bytes or not 0<len(body)<=MAX_BODY or
                type(observed) is not int or observed<=0):
                row["status"]="NEWS_INDEX_INVALID_SOURCE_RECEIPT"
                continue
            meta=parse_metadata(body,observed_at_utc=observed)
            title=(meta.get("page_title") or "").casefold()
            text=body[:8192].decode("utf-8","replace").casefold()
            if any(marker in title or marker in text for marker in (
                    "just a moment...","checking your browser",
                    "verify you are human","attention required! | cloudflare")):
                row["status"]="ANTI_BOT_CHALLENGE_NOT_NEWS_SOURCE"
                continue
            row.update(status="NEWS_ENTRY_HTTP_OBSERVED_NOT_INJURY_VERIFIED",
                       source_http_status=response.get("http_status"),
                       observed_at_utc=observed,body_sha256=_pin(body),
                       index_document_bytes=len(body),
                       index_title=meta.get("page_title"),
                       publication_time_verified=False)
    observed=0;blocked=0;unattempted=0
    for row in reports:
        st=row.get("status","NOT_ATTEMPTED_BATCH_BUDGET")
        if st=="NEWS_ENTRY_HTTP_OBSERVED_NOT_INJURY_VERIFIED":
            observed+=1
        elif st=="NOT_ATTEMPTED_BATCH_BUDGET":
            unattempted+=1
        else:
            blocked+=1
    output.update(source_observed_count=observed,
        source_blocked_or_unavailable_count=blocked,
        unattempted_count=unattempted,
        scan_complete=(unattempted==0),
        status=("ALL_82_BATCH_COMPLETE_WITH_PER_SOURCE_STATUS"
                if unattempted==0 else
                "ALL_82_BATCH_PARTIAL_BUDGET_WITH_PER_SOURCE_STATUS"))
    return output

def compact_summary(report):
    return dict((k,v) for k,v in report.items() if
                k!="results") | dict(
        results=[dict(league=r["league"],club_key=r["club_key"],
                      source_url=r["official_news_entry_url"],
                      status=r["status"],
                      source_http_status=r.get("source_http_status"),
                      robots_http_status=r.get("robots_http_status"))
                 for r in report["results"]])

def run(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live",action="store_true",
                        help="Opt in to ONE bounded, robots-gated pass across ALL 82 news entry pages")
    parser.add_argument("--summary",action="store_true")
    args=parser.parse_args(argv)
    report=batch_probe(live=args.live)
    if args.summary:
        report=compact_summary(report)
    print(json.dumps(report,sort_keys=True,ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(run())

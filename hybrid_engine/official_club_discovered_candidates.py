"""Four discovered club news links; optional, bounded live probe only.

This is NOT the six-source verified pilot manifest; these candidates have
NOT passed device live access/robots, source publication timestamps,
independent player/fixture IDs, and are never a model input.
"""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

from hybrid_engine.official_club_coverage import load_coverage
from hybrid_engine.official_club_sources import (
    _bounded_https,_request,allowed_by_robots,MAX_ROBOTS,MAX_BODY,
    parse_metadata,_pin)

MANIFEST=Path(__file__).with_name("official_club_discovered_candidates.json")
FORMAT="OFFICIAL_CLUB_NEWS_DISCOVERED_CANDIDATES_V1"
CANDIDATE_KEYS=frozenset((
    "nba_golden_state_warriors",
    "euroleague_anadolu_efes_istanbul",
    "euroleague_panathinaikos_athens",
    "eurocup_turk_telekom_ankara"))


def discovered_registry(path=MANIFEST):
    data=json.loads(Path(path).read_text(encoding="utf-8"))
    items=data.get("candidates")
    if (data.get("format")!=FORMAT or data.get("season")!="2026/2027"
            or type(items) is not list or len(items)!=4):
        raise ValueError("DISCOVERED_CLUB_CANDIDATE_MANIFEST_INVALID")
    members={v["club_key"]:v for v in load_coverage()["teams"]}
    seen=set()
    result=[]
    for row in items:
        if (type(row) is not dict or
            not {"club_key","league","name","native_team_id","source_url",
                 "site_evidence_url","evidence_kind","status"}<=row.keys()):
            raise ValueError("DISCOVERED_CLUB_SOURCE_SCHEMA_INVALID")
        key=row["club_key"]
        if (key not in CANDIDATE_KEYS or key in seen or
            row["league"]!=members[key]["league"] or
            row["name"]!=members[key]["team_name"] or
            row["status"]!="PUBLIC_LINK_DISCOVERED_NOT_PROBED" or
            members[key]["official_news_url"] is not None):
            raise ValueError("DISCOVERED_CLUB_IDENTITY_OR_EVIDENCE_CONFLICT")
        seen.add(key)
        _bounded_https(row["site_evidence_url"])
        info=_bounded_https(row["source_url"])
        # Source transport may not navigate arbitrary redirects or domains.
        if row["league"]=="NBA":
            if key!="nba_golden_state_warriors" or (
                row["native_team_id"]!="1610612744" or
                info.hostname!="www.nba.com"):
                raise ValueError("NBA_DISCOVERY_NATIVE_ID_OR_HOST_CONFLICT")
        else:
            if row["native_team_id"] is not None:
                raise ValueError("EUROPE_DISCOVERY_NATIVE_TEAM_ID_NOT_PINNED")
        result.append(dict(row,
            host=info.hostname,path=info.path))
    if seen!=CANDIDATE_KEYS:
        raise ValueError("DISCOVERED_CANDIDATE_SET_NOT_EXHAUSTIVE")
    return tuple(result)


def observe_candidate(club_key,*,live=False,requester=_request):
    candidates={x["club_key"]:x for x in discovered_registry()}
    if club_key not in candidates:
        raise ValueError("UNAPPROVED_CANDIDATE_KEY")
    selected=candidates[club_key]
    base=dict(format="OFFICIAL_CLUB_DISCOVERY_FIELD_V1",
              club_key=club_key,league=selected["league"],
              source_url=selected["source_url"],
              observed_claims=0,verified_player_ids=0,
              fixture_identity_verified=False,
              model_input=False,production_changed=False)
    if not live:
        return dict(base,status="DISCOVERED_URL_NOT_LIVE_CHECKED",
                    requests=0)
    # The original discovery/parser allowlist is intentionally SIX clubs
    # only; these FOUR new URLs must NOT get article/player parsers by
    # accidentally bypassing that manifest. Two requests maximum.
    url=selected["source_url"]
    robots=requester("https://"+selected["host"]+"/robots.txt",
                     limit=MAX_ROBOTS,expected_mime="text/plain")
    if robots.get("status")!="DOCUMENT_RECEIVED":
        # Even 404 requires independent policy review for new candidate
        # sources. Never assume allowed or probe on an unknown rule.
        return dict(base,status="ABSTAIN_CANDIDATE_SOURCE_NOT_ACCESS_VERIFIED",
                    source_status="ROBOTS_POLICY_UNVERIFIED",
                    robots_http_status=robots.get("http_status"),requests_max=1)
    if not allowed_by_robots(robots["body"].decode("utf-8","replace"),url):
        return dict(base,status="ABSTAIN_CANDIDATE_SOURCE_NOT_ACCESS_VERIFIED",
                    source_status="ROBOTS_DISALLOW",
                    robots_http_status=robots.get("http_status"),requests_max=1)
    page=requester(url,limit=MAX_BODY,expected_mime="text/html")
    if page.get("status")!="DOCUMENT_RECEIVED":
        return dict(base,status="ABSTAIN_CANDIDATE_SOURCE_NOT_ACCESS_VERIFIED",
                    source_status=page.get("status"),
                    source_http_status=page.get("http_status"),requests_max=2)
    raw=page.get("body")
    observed=page.get("observed_at_utc")
    if (type(raw) is not bytes or len(raw)>MAX_BODY or
        type(observed) is not int or observed<=0):
        return dict(base,status="ABSTAIN_CANDIDATE_SOURCE_NOT_ACCESS_VERIFIED",
                    source_status="INVALID_SOURCE_BODY_OR_OBSERVATION_CLOCK",
                    requests_max=2)
    meta=parse_metadata(raw,observed_at_utc=observed)
    # Not an article. Index listing clock is *not* an individual
    # published claim and never implies absence/injury.
    return dict(base,
        status="PUBLIC_NEWS_INDEX_OBSERVED_NOT_PLAYER_VERIFIED",
        observed_at_utc=observed,
        page_sha256=_pin(raw),
        article_url_candidate_count=0,
        article_discovery_enabled=False,
        publication_time_status="NEWS_INDEX_ARTICLE_TIME_NOT_VERIFIED",
        requests_max=2)


def run(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--club",choices=sorted(CANDIDATE_KEYS))
    p.add_argument("--live",action="store_true")
    a=p.parse_args(argv)
    if a.club is None:
        report=dict(format=FORMAT,status="FOUR_DISCOVERED_LINKS_NO_HTTP",
            candidates=[dict(club_key=c["club_key"],league=c["league"],
                             source_url=c["source_url"],
                             status="PUBLIC_LINK_DISCOVERED_NOT_PROBED")
                        for c in discovered_registry()],
            total_candidates=4,connected_player_feeds=0,
            requests=0,model_input=False,production_changed=False)
    else:
        report=observe_candidate(a.club,live=a.live)
    print(json.dumps(report,ensure_ascii=False,sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(run())

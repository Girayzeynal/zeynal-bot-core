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
    _bounded_https,probe,_request)

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
    # Probe first calls source-host robots, then only exact source URL.
    # If 403/redirect/robots disallow, fail closed. Never save HTML.
    evidence=probe(selected,requester=requester)
    if evidence["status"]!="PUBLIC_NEWS_PAGE_OBSERVED_NOT_PLAYER_VERIFIED":
        return dict(base,status="ABSTAIN_CANDIDATE_SOURCE_NOT_ACCESS_VERIFIED",
                    source_status=evidence["status"],
                    robots_http_status=evidence.get("robots_http_status"),
                    source_http_status=evidence.get("source_http_status"),
                    requests_max=2)
    return dict(base,
        status="PUBLIC_NEWS_INDEX_OBSERVED_NOT_PLAYER_VERIFIED",
        observed_at_utc=evidence["observed_at_utc"],
        page_sha256=evidence["body_sha256"],
        article_url_candidate_count=len(evidence["article_links"]),
        publication_time_status=evidence["publication_time_status"],
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

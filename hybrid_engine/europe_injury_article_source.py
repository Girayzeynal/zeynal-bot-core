"""Bounded same-origin article interpretation: textual leads, never roster proof.

No medical inference from generic 'injured' phrases, no model influence.
Each article must pass its own robots and strict HTTPS/same-host checks.
Only precise publication timestamps may qualify for chronological evidence.
"""
import hashlib
import re
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup

from hybrid_engine.official_club_sources import parse_metadata
from hybrid_engine.europe_injury_public_sources import MAX_BYTES,MAX_ROBOTS,UA,_safe_url,request,name_key

# The narrow status expressions avoid extrapolating vague treatment reports.
W=r"[A-ZÀ-ÖØ-ÞÇĞİÖŞÜ][a-zà-öø-ÿçğıöşü'’-]{1,30}"
NAME=rf"{W}(?:\s+{W}){{1,3}}"
EN=re.compile(rf"(?P<name>{NAME})\s+(?:is\s+)?(?P<status>ruled\s+out|out\s+for\s+the\s+game|will\s+miss\s+(?:the\s+)?game|will\s+not\s+play|won't\s+play)\b",re.I)
TR=re.compile(rf"(?P<name>{NAME})\s+(?:sakatlığ\w*\s+nedeniyle\s+)?(?P<status>forma\s+giyemeyecek|maç\s+kadrosunda\s+yer\s+almayacak)\b",re.I)
MAX_CANDIDATES=8
MAX_TEXT=10000


def text_candidates(body):
    if type(body) is not bytes or len(body)>MAX_BYTES:
        raise ValueError("ARTICLE_HTML_BOUND")
    soup=BeautifulSoup(body,"html.parser")
    for tag in soup(["script","style","nav","footer","header","form","noscript"]):
        tag.decompose()
    main=soup.find("article") or soup.find("main") or soup.body
    if main is None:
        return []
    text=" ".join(main.get_text(" ",strip=True).split())[:MAX_TEXT]
    found={}
    for rx in (EN,TR):
        for match in rx.finditer(text):
            name=" ".join(match.group("name").split())
            key=name_key(name)
            # Reject generic compound nouns as people; this remains a lead,
            # not a medical fact or verified roster claim.
            if key and key not in found and len(name)<=95:
                found[key]=dict(player_name_text=name,
                    source_reported_status="OUT_TEXT_CANDIDATE",
                    official_player_id=None,fixture_id=None,
                    match_availability_verified=False,model_input=False,
                    evidence_level="ARTICLE_TEXT_ONLY_UNVERIFIED")
            if len(found)>=MAX_CANDIDATES:
                break
    return list(found.values())[:MAX_CANDIDATES]


def observe_article(index_spec,link,*,requester=request,now):
    """At most one independent robots and one article HTML request."""
    root=urlsplit(index_spec["url"]);url=link["url"] if isinstance(link,dict) else ""
    result=dict(url=url,status="ARTICLE_NOT_ATTEMPTED",
        observed_at_utc=int(now),source_published_at_utc=None,
        publication_time_status="UNVERIFIED",body_sha256=None,
        player_status_verified=False,fixture_verified=False,
        model_input=False,unverified_player_candidates=[])
    if not isinstance(url,str) or not _safe_url(url) or urlsplit(url).hostname!=root.hostname:
        return dict(result,status="ARTICLE_HOST_OR_URL_REFUSED")
    robots=requester("https://"+root.hostname+"/robots.txt",mime="text/plain",limit=MAX_ROBOTS)
    robots_absent=(robots.get("http_status") in (404,410))
    if not robots_absent:
        if robots.get("status")!="RECEIVED" or type(robots.get("body")) is not bytes:
            return dict(result,status="ARTICLE_ROBOTS_UNAVAILABLE")
        rp=RobotFileParser()
        try:
            rp.parse(robots["body"].decode("utf-8","replace").splitlines())
            if not rp.can_fetch(UA,url):
                return dict(result,status="ARTICLE_ROBOTS_DISALLOW")
        except (ValueError,TypeError,UnicodeError):
            return dict(result,status="ARTICLE_ROBOTS_INVALID")
    payload=requester(url,mime="text/html",limit=MAX_BYTES)
    if payload.get("status") not in ("RECEIVED","RECEIVED_PARTIAL"):
        return dict(result,status="ARTICLE_"+str(payload.get("status","UNREACHABLE"))[:60],
                    http_status=payload.get("http_status"))
    incomplete=(payload.get("status")=="RECEIVED_PARTIAL")
    body=payload.get("body")
    if type(body) is not bytes or not 0<len(body)<=MAX_BYTES:
        return dict(result,status="ARTICLE_BODY_INVALID")
    meta=parse_metadata(body,observed_at_utc=int(now))
    # An index or undated article can still display text leads, but never
    # claim a pre-tipoff date when no precise source timestamp is available.
    published=(meta["published_utc"] if
               meta["publication_time_status"]=="PRECISE_PAGE_PUBLICATION_TIME" else None)
    return dict(result,status=("ARTICLE_TEXT_PARTIAL_CANDIDATES_ONLY" if incomplete
                               else "ARTICLE_TEXT_OBSERVED_CANDIDATES_ONLY"),
        incomplete_html=incomplete,captured_bytes=len(body),
        publication_time_status=meta["publication_time_status"],
        source_published_at_utc=published,
        title=meta["page_title"],body_sha256=hashlib.sha256(body).hexdigest(),
        unverified_player_candidates=text_candidates(body))

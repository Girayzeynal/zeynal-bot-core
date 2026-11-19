"""Bounded, source-pinned official club ARTICLE probe: no forecasts or player statuses.

Read robots, one indexed page, and one ARTICLE URL that must appear in that
fresh index. Never follow redirects, backfill a past prediction or infer a
player absence solely from an article link. Article body is processed in
memory, never archived. The publication clock is NOT "verified" when absent
or timezone-free.
"""
import hashlib
from html.parser import HTMLParser
from urllib.parse import urlsplit

from hybrid_engine.official_club_sources import (
    _bounded_https, _request, allowed_by_robots, parse_metadata,
    collect_article_candidates, MAX_BODY, MAX_ROBOTS, FORMAT
)

class ArticleText(HTMLParser):
    """Extract plain visible text, deliberately not scripts/styles."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden=0
        self.parts=[]
        self.size=0
    def handle_starttag(self,tag,attrs):
        if tag in ("script","style","noscript","svg"):
            self.hidden+=1
    def handle_endtag(self,tag):
        if tag in ("script","style","noscript","svg") and self.hidden>0:
            self.hidden-=1
    def handle_data(self,data):
        if self.hidden:return
        if self.size<8192:
            clean=" ".join(data.split())
            if clean:
                clean=clean[:512]
                self.parts.append(clean)
                self.size+=len(clean)
    def text(self):
        return " ".join(self.parts)[:8192]


def probe_article(club,url,*,requester=_request):
    """Three bounded requests max, same club host, one current news index."""
    homepage=club["source_url"]
    home_parts=_bounded_https(homepage,club["host"])
    target=_bounded_https(url)
    if target.hostname not in (home_parts.hostname,
                               "www."+home_parts.hostname if home_parts.hostname.startswith("www.") is False else home_parts.hostname.removeprefix("www.")):
        raise ValueError("ARTICLE_DIFFERENT_CLUB_DOMAIN")
    robots_url="https://"+home_parts.hostname+"/robots.txt"
    robots=requester(robots_url,limit=MAX_ROBOTS,expected_mime="text/plain")
    if robots.get("status")!="DOCUMENT_RECEIVED":
        if robots.get("http_status") not in (404,410):
            return dict(status="ROBOTS_UNAVAILABLE_OR_REFUSED",
                        source_url=url,club_key=club["club_key"],model_input=False)
    elif (not allowed_by_robots(robots["body"].decode("utf-8","replace"),homepage)
          or not allowed_by_robots(robots["body"].decode("utf-8","replace"),url)):
        return dict(status="ROBOTS_DISALLOW",source_url=url,club_key=club["club_key"],model_input=False)
    listing=requester(homepage,limit=MAX_BODY,expected_mime="text/html")
    if listing.get("status")!="DOCUMENT_RECEIVED":
        return dict(status="CLUB_NEWS_INDEX_UNAVAILABLE",club_key=club["club_key"],
                    index_status=listing.get("status"),model_input=False)
    candidates=collect_article_candidates(
        listing["body"],club,observed_at_utc=listing.get("observed_at_utc"))
    found=[c for c in candidates if c["url"]==url]
    if len(found)!=1:
        return dict(status="ARTICLE_NOT_VERIFIED_IN_CURRENT_INDEX",club_key=club["club_key"],
                    article_url=url,index_article_count=len(candidates),model_input=False)
    story=requester(url,limit=MAX_BODY,expected_mime="text/html")
    if story.get("status")!="DOCUMENT_RECEIVED":
        return dict(status=story.get("status","ARTICLE_SOURCE_UNAVAILABLE"),club_key=club["club_key"],
                    article_url=url,source_http_status=story.get("http_status"),
                    model_input=False)
    raw=story["body"]
    if not isinstance(raw,bytes) or len(raw)>MAX_BODY:
        raise ValueError("OFFICIAL_ARTICLE_BODY_INVALID")
    at=story.get("observed_at_utc")
    if type(at) is not int or at<=0:
        raise ValueError("OFFICIAL_ARTICLE_OBSERVED_CLOCK_REQUIRED")
    metadata=parse_metadata(raw,observed_at_utc=at)
    parser=ArticleText()
    parser.feed(raw.decode("utf-8","replace"))
    text=parser.text()
    from hybrid_engine.official_club_claims import injury_absence_candidates
    candidate_claims=injury_absence_candidates(text,club_key=club["club_key"])
    # Source text is distinct from verified roster status: neither native
    # player IDs nor this game's native fixture nor exact publication time
    # can be established by merely reading the official article.
    return dict(format="OFFICIAL_CLUB_ARTICLE_PROBE_V1",
                status="OFFICIAL_ARTICLE_OBSERVED_NOT_ROSTER_VERIFIED",
                league=club["league"],club_key=club["club_key"],
                source_url=url,source_http_status=200,fixture_id=None,
                observed_at_utc=at,body_sha256=hashlib.sha256(raw).hexdigest(),
                document_bytes=len(raw),article_title=metadata["page_title"],
                article_headline_from_index=found[0]["label"],
                index_candidate_origin=found[0].get("discovered_from","OFFICIAL_NEWS_INDEX_ANCHOR"),
                index_raw_date=found[0].get("source_raw_date"),
                index_raw_timestamp=found[0].get("source_raw_timestamp"),
                index_clock_status=found[0].get("source_clock_status","NOT_VERIFIED"),
                index_native_post_id=found[0].get("source_post_id"),
                injury_absence_claim_candidates=candidate_claims,
                injury_claim_evidence_status=("SOURCE_TEXT_CANDIDATES_ONLY" if candidate_claims else "NO_EXPLICIT_SOURCE_TEXT_CANDIDATES"),
                published_utc=metadata["published_utc"] if metadata["publication_time_status"]=="PRECISE_PAGE_PUBLICATION_TIME" else None,
                publication_time_status=metadata["publication_time_status"],
                visible_text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                visible_text_chars=len(text),
                article_index_url=homepage,
                match_identity_status="NATIVE_FIXTURE_NOT_BOUND",
                player_status_verified=False,injury_verified=False,
                lineup_verified=False,model_input=False,market_data=False,
                forecast_changed=False,production_changed=False)

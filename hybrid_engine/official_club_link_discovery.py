"""Extract bounded, SAME-CLUB candidate article links from a single official news index.

This is metadata discovery only. No article download, player status, lineup
assertion, copyrighted full-text archiving or inference. Preserve titles as
short labels and source URLs only; all candidates require separate verification.
"""
from html.parser import HTMLParser
import re
from urllib.parse import urljoin,urlsplit

from hybrid_engine.official_club_sources import _bounded_https

MAX_LINKS=12
MAX_LABEL=140
MAX_HREF=512

# Six manually reviewed, official paths. Do not infer unrelated sports/teams.
_PATTERNS={
    "nba_denver_nuggets":re.compile(r"/nuggets/news/[A-Za-z0-9][A-Za-z0-9-]{3,160}/?$"),
    "nba_boston_celtics":re.compile(r"/celtics/news/[A-Za-z0-9][A-Za-z0-9-]{3,160}/?$"),
    "euroleague_olympiacos":re.compile(r"/en/news/announcements/[0-9]{2,10}-[a-z0-9-]{4,140}\.html$"),
    "euroleague_zalgiris":re.compile(r"/(?:en/)?naujienos/[a-z0-9-]{5,160}/?$"),
    "eurocup_tofas":re.compile(r"/haber-[0-9]{2,10}-[a-zA-Z0-9_]{5,160}/?$"),
    # Site-specific: index at /en/news/ but official story URLs at /en/<slug>/.
    "eurocup_cedevita_olimpija":re.compile(r"/en/[a-z0-9][a-z0-9-]{5,160}/$"),
}
_ALIASES={
    "tofasspor.com":frozenset(("tofasspor.com","www.tofasspor.com")),
}
_CEDEVITA_NON_ARTICLE=frozenset((
    "/en/news/","/en/home/","/en/club/","/en/team/","/en/contact/",
    "/en/shop/","/en/schedule/","/en/","/en/tickets/",
))
# Verified category/landing page, NOT a dated Celtics news article.
_NON_ARTICLE_ROUTES={
    "nba_boston_celtics":frozenset(("/celtics/news/insiders",)),
}


def is_article_route(key,path):
    return (key in _PATTERNS and
            bool(_PATTERNS[key].fullmatch(path)) and
            path.rstrip("/") not in _NON_ARTICLE_ROUTES.get(key,frozenset()) and
            not (key=="eurocup_cedevita_olimpija" and
                 path in _CEDEVITA_NON_ARTICLE))


class Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.anchor=None
        self.links=[]

    def handle_starttag(self,tag,attrs):
        if tag!="a" or self.anchor is not None:return
        ref=dict(attrs).get("href")
        if not isinstance(ref,str) or len(ref)>MAX_HREF:return
        self.anchor=[ref,[]]

    def handle_data(self,text):
        if self.anchor is None:return
        if sum(len(x) for x in self.anchor[1])<MAX_LABEL:
            self.anchor[1].append(text[:MAX_LABEL])

    def handle_endtag(self,tag):
        if tag!="a" or self.anchor is None:return
        href,pieces=self.anchor
        label=" ".join(" ".join(pieces).split())[:MAX_LABEL]
        if label:self.links.append((href,label))
        self.anchor=None


def discover_article_links(index_html,club):
    if type(index_html) is not bytes or len(index_html)>512*1024:
        raise ValueError("OFFICIAL_NEWS_INDEX_BYTES_REQUIRED")
    key=club.get("club_key")
    if key not in _PATTERNS:raise ValueError("OFFICIAL_CLUB_NOT_IN_PILOT")
    base=club["source_url"]
    native_host=_bounded_https(base,club["host"]).hostname
    hosts=_ALIASES.get(native_host,frozenset((native_host,)))
    parser=Links()
    parser.feed(index_html.decode("utf-8","replace"))
    found=[];seen=set()
    for href,label in parser.links:
        try:
            # Reject non-HTTPS links even if urljoin would reinterpret them.
            if href.startswith(("http:","javascript:","data:","mailto:","tel:","#")):
                continue
            candidate=urljoin(base,href)
            p=_bounded_https(candidate)
        except (ValueError,TypeError):
            continue
        if p.hostname not in hosts or not is_article_route(key,p.path):
            continue
        candidate=p.geturl()
        if candidate in seen:continue
        seen.add(candidate)
        found.append(dict(url=candidate,label=label,
                          status="CANDIDATE_LINK_ONLY_NOT_ARTICLE_FETCHED",
                          published_utc=None,fixture_id=None,
                          player_status_verified=False))
        if len(found)==MAX_LINKS:break
    return found

"""Official club HTML link audit; no new requests, no article body storage.

Distinguish successful HTTP retrieval from parser mismatch/JS-only links. Never
trust links as sources before source host/path pinning.
"""
from html.parser import HTMLParser
from urllib.parse import urljoin

from hybrid_engine.official_club_sources import _bounded_https
from hybrid_engine.official_club_link_discovery import _ALIASES, _PATTERNS, is_article_route

MAX_AUDIT_LINKS=600
MAX_SAMPLES=8

class _Anchors(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows=[]
        self.anchor=None

    def handle_starttag(self,tag,attrs):
        if tag!="a" or self.anchor is not None or len(self.rows)>=MAX_AUDIT_LINKS:return
        d=dict(attrs)
        ref=d.get("href")
        if type(ref) is str and len(ref)<=512:
            self.anchor=[ref,bool(d.get("aria-label") or d.get("title")),False]

    def handle_data(self,data):
        if self.anchor is not None and data.strip():
            self.anchor[2]=True

    def handle_endtag(self,tag):
        if tag!="a" or self.anchor is None:return
        self.rows.append(tuple(self.anchor))
        self.anchor=None


def diagnose_links(index_html,club):
    if type(index_html) is not bytes or len(index_html)>512*1024:
        raise ValueError("OFFICIAL_NEWS_INDEX_BYTES_REQUIRED")
    key=club["club_key"]
    if key not in _PATTERNS:raise ValueError("OFFICIAL_CLUB_NOT_IN_PILOT")
    base=club["source_url"]
    original_host=_bounded_https(base,club["host"]).hostname
    hosts=_ALIASES.get(original_host,frozenset((original_host,)))
    parser=_Anchors();parser.feed(index_html.decode("utf-8","replace"))
    summary=dict(
        audited_anchor_count=len(parser.rows),
        audited_anchor_count_capped=len(parser.rows)>=MAX_AUDIT_LINKS,
        empty_label_count=0,invalid_or_unsupported_href_count=0,
        other_host_href_count=0,same_club_host_href_count=0,
        same_club_news_like_href_count=0,
        allowed_article_path_href_count=0,
        allowed_article_path_unlabelled_count=0,
        article_like_unmatched_paths_sample=[],
        nonarticle_same_club_paths_sample=[],
        js_runtime_markers=dict(
            next_data=(b"__NEXT_DATA__" in index_html),
            next_static=(b"/_next/" in index_html),
            embedded_json_ld=(b"application/ld+json" in index_html)),
        # These hints are not a verdict that pages require JavaScript rendering.
        diagnostic_only=True,model_input=False)
    seen_news=set();seen_other=set()
    for href,aria_label,visible_label in parser.rows:
        if not aria_label and not visible_label:summary["empty_label_count"]+=1
        if href.startswith(("http:","javascript:","data:","mailto:","tel:","#")):
            summary["invalid_or_unsupported_href_count"]+=1;continue
        try:p=_bounded_https(urljoin(base,href))
        except (ValueError,TypeError):
            summary["invalid_or_unsupported_href_count"]+=1;continue
        if p.hostname not in hosts:
            summary["other_host_href_count"]+=1;continue
        summary["same_club_host_href_count"]+=1
        path=p.path
        if is_article_route(key,path):
            summary["allowed_article_path_href_count"]+=1
            if not (aria_label or visible_label):
                summary["allowed_article_path_unlabelled_count"]+=1
        elif "news" in path.casefold() or "nuggets" in path.casefold() or "celtics" in path.casefold():
            summary["same_club_news_like_href_count"]+=1
            if path not in seen_news and len(summary["article_like_unmatched_paths_sample"])<MAX_SAMPLES:
                # Public URL paths only; never collect the querystring, title or HTML.
                summary["article_like_unmatched_paths_sample"].append(path[:180])
                seen_news.add(path)
        elif path not in seen_other and len(summary["nonarticle_same_club_paths_sample"])<MAX_SAMPLES:
            summary["nonarticle_same_club_paths_sample"].append(path[:180])
            seen_other.add(path)
    return summary

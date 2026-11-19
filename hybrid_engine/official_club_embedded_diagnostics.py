"""Bounded official NBA embedded-JSON news-link *diagnostics*, no extra requests.

Detect Next.js __NEXT_DATA__ / JSON-LD article URL candidates from already fetched
official page HTML. Never execute JS, download external URLs, publish copyrighted
text or assert any player, injury, fixture or publication-time evidence.

This module diagnoses whether a zero-anchor result is a parser mismatch,
server-rendered embedded data, or needs separate licensed/native API discovery.
"""
from html.parser import HTMLParser
import json
from urllib.parse import urljoin

from hybrid_engine.official_club_link_discovery import _PATTERNS
from hybrid_engine.official_club_sources import _bounded_https

MAX_HTML_BYTES = 512 * 1024
MAX_SCRIPT_BYTES = 384 * 1024
MAX_EMBEDDED_SCRIPTS = 8
MAX_NODES = 12000
MAX_DEPTH = 32
MAX_SAMPLES = 8
_LINK_FIELDS = frozenset(("url", "href", "path", "canonicalurl", "articleurl", "link"))
_ALLOWED_KEYS = frozenset(("nba_denver_nuggets", "nba_boston_celtics"))


class EmbeddedScripts(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.capturing = None
        self.buffers = []
        self.scripts = []
        self.truncated = 0

    def handle_starttag(self, tag, attrs):
        if tag != "script" or self.capturing is not None:
            return
        d = dict(attrs)
        kind = "NEXT_DATA" if d.get("id") == "__NEXT_DATA__" else (
            "JSON_LD" if d.get("type", "").lower() == "application/ld+json" else None)
        if not kind:
            return
        if len(self.scripts) >= MAX_EMBEDDED_SCRIPTS:
            self.truncated += 1
            return
        self.capturing = kind
        self.buffers = []
        self.size = 0

    def handle_data(self, data):
        if self.capturing is not None:
            self.size += len(data.encode("utf-8", "replace"))
            if self.size <= MAX_SCRIPT_BYTES:
                self.buffers.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.capturing is not None:
            if self.size <= MAX_SCRIPT_BYTES:
                self.scripts.append((self.capturing, "".join(self.buffers)))
            else:
                self.truncated += 1
            self.capturing = None
            self.buffers = []


def _same_team_article(value, club):
    if not isinstance(value, str) or not 1 <= len(value) <= 512:
        return None
    # Deliberately refuse any source with query params / fragment, credentials,
    # non-HTTP schemes, or a different team path.
    if value.startswith(("http:", "javascript:", "data:", "mailto:", "tel:", "#")):
        return None
    try:
        candidate = urljoin(club["source_url"], value)
        p = _bounded_https(candidate)
    except (ValueError, TypeError):
        return None
    if p.hostname != club["host"] or not _PATTERNS[club["club_key"]].fullmatch(p.path):
        return None
    return p.geturl()


def diagnose_embedded(index_html, club):
    if type(index_html) is not bytes or len(index_html) > MAX_HTML_BYTES:
        raise ValueError("OFFICIAL_EMBEDDED_HTML_BUDGET")
    if club["club_key"] not in _ALLOWED_KEYS:
        raise ValueError("OFFICIAL_EMBEDDED_NBA_ONLY")
    _bounded_https(club["source_url"], club["host"])
    parser = EmbeddedScripts()
    parser.feed(index_html.decode("utf-8", "replace"))
    report = dict(
        diagnostic_only=True, model_input=False,
        next_data_script_count=sum(kind == "NEXT_DATA" for kind, _ in parser.scripts),
        json_ld_script_count=sum(kind == "JSON_LD" for kind, _ in parser.scripts),
        oversized_or_excess_script_count=parser.truncated,
        parse_error_count=0, scanned_json_nodes=0,
        json_traversal_truncated=False, news_link_field_count=0,
        article_url_candidate_count=0, article_urls_sample=[],
        next_data_top_keys=[], has_page_props=False,
        source="EMBEDDED_OFFICIAL_HTML_NOT_PUBLISHED_ARTICLE")
    candidates=set()
    for kind, raw in parser.scripts:
        try:
            doc=json.loads(raw)
        except (ValueError, TypeError, RecursionError):
            report["parse_error_count"] += 1
            continue
        if kind=="NEXT_DATA" and isinstance(doc, dict):
            report["next_data_top_keys"] = sorted(
                k for k in doc if isinstance(k,str) and len(k)<=32)[:16]
            report["has_page_props"] = isinstance(doc.get("props"), dict) and (
                "pageProps" in doc["props"])
        stack=[(doc,0)]
        while stack:
            item,depth=stack.pop()
            report["scanned_json_nodes"] += 1
            if report["scanned_json_nodes"]>=MAX_NODES or depth>=MAX_DEPTH:
                report["json_traversal_truncated"]=True
                stack.clear()
                break
            if isinstance(item,dict):
                if len(item)>256: # Preserve budget on huge metadata dictionaries.
                    report["json_traversal_truncated"]=True
                    continue
                for key,value in item.items():
                    if not isinstance(key,str) or len(key)>64:continue
                    if key.casefold() in _LINK_FIELDS and isinstance(value,str):
                        report["news_link_field_count"] += 1
                        url=_same_team_article(value,club)
                        if url is not None:candidates.add(url)
                    elif isinstance(value,(dict,list)):
                        stack.append((value,depth+1))
            elif isinstance(item,list):
                if len(item)>2048:
                    report["json_traversal_truncated"]=True
                    continue
                stack.extend((value,depth+1) for value in item)
    report["article_url_candidate_count"]=len(candidates)
    report["article_urls_sample"]=sorted(candidates)[:MAX_SAMPLES]
    return report

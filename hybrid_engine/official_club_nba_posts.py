"""Bounded NBA official __NEXT_DATA__ post discovery from the current news index.

Each candidate must be an actual published-looking post with a native
permalink, slug, and post ID. URLs are pinned to the selected nba.com team.
The local source's date/timestamp are *unverified listing metadata*, never
automatically promoted into a historical prematch cutoff or a forecast input.

No extra requests, no JS execution, article fetch, raw HTML archive or
third-party source. This adapter is deliberately NBA pilot-only.
"""
from datetime import datetime, timezone
import json
import re

from hybrid_engine.official_club_embedded_diagnostics import (
    EmbeddedScripts, _same_team_article, MAX_HTML_BYTES, MAX_DEPTH,
    MAX_NODES, _ALLOWED_KEYS
)

MAX_CANDIDATES=24
MAX_LABEL_CHARS=140
_SLUG=re.compile(r"^[a-z0-9][a-z0-9-]{2,160}$")


def _source_clock(entry, *, observed_at_utc=None):
    raw=entry.get("date")
    stamp=entry.get("timestamp")
    date_s=None
    try:
        if isinstance(raw,str) and len(raw)<=40:
            d=datetime.fromisoformat(raw.replace("Z","+00:00"))
            if d.tzinfo is not None:
                date_s=int(d.astimezone(timezone.utc).timestamp())
    except (ValueError,OverflowError):
        pass
    timestamp_s=None
    if type(stamp) is int and 0<stamp<10**15:
        timestamp_s=stamp//1000 if stamp>10**11 else stamp
    if date_s is not None and timestamp_s is not None:
        clock=("LISTING_DATE_TIMESTAMP_CONFLICT" if abs(date_s-timestamp_s)>120 else
               "LISTING_DATE_TIMESTAMP_AGREE_UNVERIFIED")
    else:
        clock="LISTING_SOURCE_CLOCK_UNVERIFIED"
    if observed_at_utc is not None and (
        (date_s is not None and date_s>observed_at_utc+300) or
        (timestamp_s is not None and timestamp_s>observed_at_utc+300)):
        clock="FUTURE_SOURCE_CLOCK"
    sort_clock=date_s if clock=="LISTING_DATE_TIMESTAMP_AGREE_UNVERIFIED" else None
    return (
        raw[:40] if isinstance(raw,str) and len(raw)<=40 else None,
        stamp if type(stamp) is int and 0<stamp<10**15 else None,
        clock,sort_clock
    )


def discover_nba_official_posts(index_html,club,*,observed_at_utc=None):
    """Return URL candidate metadata, sorted by consistent raw source clock.

    Only explicit, current-index-listed NBA post objects are accepted. For
    unknown timestamp semantics sort to the end; never infer source freshness
    or assume an article existed before an older forecast was frozen.
    """
    if type(index_html) is not bytes or len(index_html)>MAX_HTML_BYTES:
        raise ValueError("OFFICIAL_NBA_POST_HTML_BUDGET")
    if club["club_key"] not in _ALLOWED_KEYS:
        raise ValueError("OFFICIAL_NBA_POST_TEAM_NOT_PILOT")
    if observed_at_utc is not None and (
        type(observed_at_utc) is not int or observed_at_utc<=0):
        raise ValueError("OFFICIAL_NBA_POST_OBSERVATION_CLOCK")
    parser=EmbeddedScripts()
    parser.feed(index_html.decode("utf-8","replace"))
    out=[]
    seen=set()
    nodes=0
    truncated=False
    for kind,raw_json in parser.scripts:
        if kind!="NEXT_DATA":continue
        try:doc=json.loads(raw_json)
        except (ValueError,TypeError,RecursionError):continue
        stack=[(doc,0)]
        while stack:
            entry,depth=stack.pop()
            nodes+=1
            if nodes>=MAX_NODES:
                truncated=True;break
            if depth>=MAX_DEPTH:
                truncated=True;continue
            if type(entry) is dict:
                if len(entry)>256:
                    truncated=True;continue
                permalink=entry.get("permalink")
                slug=entry.get("slug")
                status=entry.get("status")
                native_id=entry.get("id")
                if (isinstance(permalink,str) and isinstance(slug,str) and
                    _SLUG.fullmatch(slug) and status=="publish" and
                    type(native_id) in (int,str) and
                    isinstance(native_id,(int,str)) and
                    1<=len(str(native_id))<=32):
                    url=_same_team_article(permalink,club)
                    if url is not None and url not in seen:
                        seen.add(url)
                        raw_date,raw_stamp,clock,sort_clock=_source_clock(
                            entry,observed_at_utc=observed_at_utc)
                        headline=entry.get("name")
                        if not isinstance(headline,str) or not headline.strip():
                            headline=entry.get("title")
                        if not isinstance(headline,str) or not headline.strip():
                            headline=slug
                        headline=" ".join(headline.split())[:MAX_LABEL_CHARS]
                        out.append(dict(
                            url=url,label=headline,
                            discovered_from="OFFICIAL_NBA_EMBEDDED_PUBLISHED_POST",
                            source_post_id=str(native_id),source_raw_date=raw_date,
                            source_raw_timestamp=raw_stamp,
                            source_clock_status=clock,
                            published_utc=None,fixture_id=None,
                            player_status_verified=False,model_input=False,
                            status="CANDIDATE_LINK_ONLY_NOT_ARTICLE_FETCHED",
                            _sort_clock=sort_clock))
                for value in entry.values():
                    if type(value) in (list,dict):stack.append((value,depth+1))
            elif type(entry) is list:
                if len(entry)>2048:
                    truncated=True;continue
                stack.extend((value,depth+1) for value in entry)
        if truncated:break
    # If a post collection is truncated, refuse instead of silently claiming
    # that the subset is the latest articles.
    if truncated:
        return []
    out.sort(key=lambda p:(p["_sort_clock"] is not None,
                           p["_sort_clock"] or -1,p["url"]),reverse=True)
    result=[]
    for candidate in out[:MAX_CANDIDATES]:
        candidate.pop("_sort_clock",None)
        result.append(candidate)
    return result

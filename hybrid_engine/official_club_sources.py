"""Six official club news sources: safe, opt-in evidence probe, NOT a lineup feed.

No scheduler, no generic crawler, no bypass of robots/403/429, no model writes.
News indexes are not evidence that a player is active or absent. A date-only
article never becomes a pre-tipoff fact without an independently verified clock.
"""
from datetime import datetime, timezone
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener
from urllib.robotparser import RobotFileParser
from email.utils import parsedate_to_datetime

FORMAT = "OFFICIAL_CLUB_NEWS_PILOT_OBSERVATION_V1"
USER_AGENT = "ZeynalClubResearch/0.1"
MAX_BODY = 512 * 1024
MAX_ROBOTS = 128 * 1024
MAX_CLUBS = 6
TIMEOUT_SECONDS = 5
PILOT_MANIFEST = Path(__file__).with_name("official_club_sources.json")


def _pin(value):
    return hashlib.sha256(value).hexdigest()


def _digest(value):
    return _pin(json.dumps(value,sort_keys=True,ensure_ascii=False,
                           separators=(",",":"),allow_nan=False).encode("utf-8"))


def _bounded_https(url, expected_host=None):
    if not isinstance(url,str) or len(url)>1024:
        raise ValueError("OFFICIAL_SOURCE_URL_INVALID")
    p=urlsplit(url)
    if (p.scheme!="https" or not p.hostname or p.username is not None or
            p.password is not None or p.port is not None or
            p.query or p.fragment or not re.fullmatch(r"[a-z0-9.-]+",p.hostname) or
            "//" in p.path or "\\" in p.path or ".." in p.path):
        raise ValueError("OFFICIAL_SOURCE_URL_INVALID")
    if expected_host is not None and p.hostname!=expected_host:
        raise ValueError("OFFICIAL_SOURCE_HOST_CONFLICT")
    return p


def registry():
    payload=json.loads(PILOT_MANIFEST.read_text(encoding="utf-8"))
    if (payload.get("format")!="OFFICIAL_CLUB_NEWS_PILOT_V1" or
            payload.get("season")!="2026/2027" or
            type(payload.get("clubs")) is not list or
            len(payload["clubs"])!=MAX_CLUBS):
        raise ValueError("OFFICIAL_CLUB_MANIFEST_INVALID")
    keys=set();counts={"NBA":0,"EUROLEAGUE":0,"EUROCUP":0}
    for item in payload["clubs"]:
        if (type(item) is not dict or
                not {"club_key","league","name","native_team_id","host","path",
                     "source_url","site_evidence_url","example_url"}<=set(item)):
            raise ValueError("OFFICIAL_CLUB_ENTRY_REQUIRED")
        key=item["club_key"]
        if (not isinstance(key,str) or not re.fullmatch(r"[a-z0-9_]{4,80}",key) or
                key in keys or item["league"] not in counts or
                not isinstance(item["name"],str) or not item["name"].strip()):
            raise ValueError("OFFICIAL_CLUB_IDENTITY_CONFLICT")
        keys.add(key);counts[item["league"]]+=1
        p=_bounded_https(item["source_url"],item["host"])
        if not p.path==item["path"]:
            raise ValueError("OFFICIAL_CLUB_SOURCE_PATH_CONFLICT")
        _bounded_https(item["site_evidence_url"])
        example=item["example_url"]
        if example is not None:
            ep=_bounded_https(example)
            # Example links can use a www. alias of the same canonical domain,
            # but only as references: not fetched by this pilot.
            if ep.hostname.removeprefix("www.")!=p.hostname.removeprefix("www."):
                raise ValueError("OFFICIAL_CLUB_EXAMPLE_HOST_CONFLICT")
        if item["league"]=="NBA":
            if not isinstance(item["native_team_id"],str) or not re.fullmatch(r"16106127[0-9]{2}",item["native_team_id"]):
                raise ValueError("NBA_TEAM_ID_REQUIRED")
        elif item["native_team_id"] is not None:
            raise ValueError("EUROPE_NATIVE_TEAM_ID_NOT_BOUND")
    if counts!={"NBA":2,"EUROLEAGUE":2,"EUROCUP":2}:
        raise ValueError("OFFICIAL_PILOT_TWO_PER_LEAGUE_REQUIRED")
    return tuple(payload["clubs"])


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        return None


class SourceHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title=[];self.heading=[];self.publication_candidates=[]
        self.in_title=False;self.in_heading=False

    def handle_starttag(self,tag,attrs):
        d=dict(attrs)
        if tag=="title":self.in_title=True
        if tag=="h1":self.in_heading=True
        if tag=="meta":
            name=(d.get("property") or d.get("name") or "").casefold()
            if name in ("article:published_time","datepublished","article:published",
                        "pubdate","publishdate","date","dc.date.issued"):
                self.publication_candidates.append(d.get("content",""))
        if tag=="time" and d.get("datetime"):
            self.publication_candidates.append(d["datetime"])

    def handle_endtag(self,tag):
        if tag=="title":self.in_title=False
        if tag=="h1":self.in_heading=False

    def handle_data(self,data):
        if self.in_title and sum(map(len,self.title))<240:self.title.append(data[:240])
        if self.in_heading and sum(map(len,self.heading))<240:self.heading.append(data[:240])


def _utc_timestamp(value):
    if not isinstance(value,str) or len(value)>80:return None
    try:
        d=datetime.fromisoformat(value.strip().replace("Z","+00:00"))
    except ValueError:
        try:d=parsedate_to_datetime(value.strip())
        except (ValueError,TypeError,IndexError):return None
    if d.tzinfo is None:return None
    return int(d.astimezone(timezone.utc).timestamp())


def parse_metadata(body, *, observed_at_utc):
    try:document=body.decode("utf-8","replace")
    except (TypeError,AttributeError):raise ValueError("CLUB_HTML_BYTES_REQUIRED")
    parser=SourceHTML()
    parser.feed(document)
    labels=[re.sub(r"\s+"," ",s).strip() for s in (" ".join(parser.heading),
                                                   " ".join(parser.title))]
    heading=next((s for s in labels if s),None)
    dates=sorted({_utc_timestamp(x) for x in parser.publication_candidates
                  if _utc_timestamp(x) is not None})
    if len(dates)>1:
        timing="CONFLICTING_PAGE_PUBLICATION_CLOCKS";published=None
    elif len(dates)==1:
        published=dates[0]
        timing=("PUBLICATION_AFTER_OBSERVATION" if published>observed_at_utc else
                "PRECISE_PAGE_PUBLICATION_TIME")
    else:
        published=None;timing="NO_VERIFIED_PUBLICATION_TIME"
    return dict(page_title=heading,publication_time_status=timing,
                published_utc=published,article_candidates_extracted=False,
                lineup_verified=False,injury_verified=False,player_ids_verified=False)


def allowed_by_robots(robots_body,url):
    if not isinstance(robots_body,str) or len(robots_body)>MAX_ROBOTS:
        raise ValueError("ROBOTS_POLICY_INVALID_OR_OVERSIZE")
    rp=RobotFileParser()
    rp.parse(robots_body.splitlines())
    return bool(rp.can_fetch(USER_AGENT,url))


def _request(url, *, limit, expected_mime):
    """No redirects, bounded memory and per-request deadline."""
    _bounded_https(url)
    req=Request(url,headers={"User-Agent":USER_AGENT,
                              "Accept":expected_mime})
    try:
        with build_opener(NoRedirect).open(req,timeout=TIMEOUT_SECONDS) as response:
            status=response.status
            content_type=response.headers.get_content_type()
            raw=response.read(limit+1)
            if len(raw)>limit:
                return dict(status="SOURCE_SIZE_LIMIT",http_status=status)
            if status!=200 or content_type not in expected_mime.split(","):
                return dict(status="SOURCE_HTTP_OR_MIME_REFUSED",http_status=status)
            return dict(status="DOCUMENT_RECEIVED",body=raw,http_status=status,
                        observed_at_utc=int(datetime.now(timezone.utc).timestamp()))
    except HTTPError as exc:
        return dict(status=("SOURCE_RATE_LIMITED" if exc.code==429 else
                            "SOURCE_ACCESS_REFUSED" if exc.code in (401,403) else
                            "SOURCE_REDIRECT_REFUSED" if exc.code in (301,302,303,307,308) else
                            "SOURCE_HTTP_ERROR"),http_status=exc.code)
    except (URLError,TimeoutError,OSError):
        return dict(status="SOURCE_NETWORK_ERROR")


def probe(club, *, requester=_request):
    """At most two same-origin requests: robots.txt, then ONE fixed source URL."""
    url=club["source_url"];p=_bounded_https(url,club["host"])
    if p.path!=club["path"]:raise ValueError("CLUB_SOURCE_UNLISTED_PATH")
    base=dict(format=FORMAT,club_key=club["club_key"],league=club["league"],
              season="2026/2027",source_url=url,source_host=p.hostname,
              native_team_id=club["native_team_id"],fixture_id=None,
              forecast_changed=False,production_changed=False,
              model_input=False,market_data=False,
              native_player_claims_verified=False)
    robots_url="https://"+p.hostname+"/robots.txt"
    robots=requester(robots_url,limit=MAX_ROBOTS,expected_mime="text/plain")
    if robots.get("status")!="DOCUMENT_RECEIVED":
        if robots.get("http_status") not in (404,410):
            return dict(base,status="ROBOTS_UNAVAILABLE_OR_REFUSED",
                        robots_http_status=robots.get("http_status"))
    elif not allowed_by_robots(robots["body"].decode("utf-8","replace"),url):
        return dict(base,status="ROBOTS_DISALLOW")
    page=requester(url,limit=MAX_BODY,expected_mime="text/html")
    if page.get("status")!="DOCUMENT_RECEIVED":
        return dict(base,status=page.get("status","SOURCE_UNAVAILABLE"),
                    source_http_status=page.get("http_status"))
    raw=page["body"]
    if not isinstance(raw,bytes) or len(raw)>MAX_BODY:
        raise ValueError("CLUB_SOURCE_BYTES_INVALID")
    observed=page["observed_at_utc"]
    if not isinstance(observed,int) or observed<=0:
        raise ValueError("CLUB_SOURCE_CLOCK_INVALID")
    metadata=parse_metadata(raw,observed_at_utc=observed)
    # Index/listing pages have no single article publication clock even when
    # their HTML includes a <time> for one or more article teaser links.
    metadata["published_utc"]=None
    metadata["publication_time_status"]="NEWS_INDEX_ARTICLE_TIME_NOT_VERIFIED"
    return dict(base,status="PUBLIC_NEWS_PAGE_OBSERVED_NOT_PLAYER_VERIFIED",
                source_page_kind="NEWS_INDEX",source_http_status=200,
                observed_at_utc=observed,body_sha256=_pin(raw),
                document_bytes=len(raw),**metadata)


def append_receipt(root,receipt):
    """Opt-in isolated, metadata-only, append-only receipt; never save HTML."""
    root=Path(root).expanduser().absolute()
    allowed=(Path.home()/"zeynal-test-isolated"/"data"/"club-pilot-evidence").absolute()
    if (root!=allowed or root.is_symlink() or
            any(p.is_symlink() for p in (root.parent,root.parent.parent,root.parent.parent.parent))):
        raise ValueError("ISOLATED_CLUB_EVIDENCE_DIRECTORY_REQUIRED")
    if receipt.get("format")!=FORMAT:
        raise ValueError("CLUB_RECEIPT_FORMAT_REQUIRED")
    root.mkdir(parents=True,exist_ok=True)
    sha=_digest(receipt)
    envelope=dict(payload=receipt,sha256=sha)
    path=root/("club-"+sha+".json")
    body=json.dumps(envelope,ensure_ascii=False,sort_keys=True,
                    allow_nan=False).encode("utf-8")
    if len(body)>8192:raise ValueError("CLUB_RECEIPT_SIZE_LIMIT")
    if path.is_symlink():raise ValueError("CLUB_RECEIPT_SYMLINK_REFUSED")
    try:
        with path.open("xb") as out:out.write(body)
    except FileExistsError:
        if path.is_symlink() or path.read_bytes()!=body:
            raise ValueError("CLUB_RECEIPT_IMMUTABILITY_CONFLICT")
    return path

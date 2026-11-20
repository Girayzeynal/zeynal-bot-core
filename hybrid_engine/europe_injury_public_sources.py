"""Bounded, robots-gated EuroLeague public-source INDEX discovery only.

Official league news and native season roster are separate existing adapters.
These three editorial sources and two exact-match club news indexes are
observational candidates, never claims of fixture-specific player availability.
No login, paid feed, RotoWire, X scraping, medical inference, score changes,
or access-control bypass. HTTP/network failures are explicit.
"""
import hashlib
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlsplit,urljoin
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup
import requests

VERSION="PUBLIC_EUROPE_NEWS_CANDIDATE_HUB_V1"
SITE_URLS=(
    ("BASKETBALL_SPHERE","https://basketballsphere.com/en/injuries/euroleague/"),
    ("EUROHOOPS","https://www.eurohoops.net/en/euroleague/"),
    ("BASKETLOGY","https://basketlogy.com/euroleague-sakatlik-raporu/"),
)
UA="ZeynalBasketballSourceAudit/1.0"
MAX_BYTES=256*1024
MAX_ROBOTS=32768
MAX_FETCH_SECONDS=2.0
COOLDOWN=900
TIME_BUDGET=3.8
MAX_CLUB_SITES=2
_NAME=re.compile(r"[^a-z0-9]+")


def name_key(value):
    if not isinstance(value,str):
        return ""
    norm=unicodedata.normalize("NFKD",value).casefold()
    return _NAME.sub("","".join(c for c in norm if not unicodedata.combining(c)))


# Explicitly reviewed sponsor/official-display aliases only. Never infer a
# club from a city substring or an arbitrary fuzzy-name similarity score.
KNOWN_ALIASES={
    "panathinaikosaktorathens":"euroleague_panathinaikos_athens",
    "panathinaikosaktor":"euroleague_panathinaikos_athens",
    "fenerbahcebeko":"euroleague_fenerbahce_istanbul",
    "fenerbahcebekoistanbul":"euroleague_fenerbahce_istanbul",
    "anadoluefes":"euroleague_anadolu_efes_istanbul",
    "anadoluefesistanbul":"euroleague_anadolu_efes_istanbul",
    "olympiacospiraeus":"euroleague_olympiacos",
    "partizanmozzartbet":"euroleague_partizan_belgrade",
    "partizanmozzartbetbelgrade":"euroleague_partizan_belgrade",
    "zalgiriskaunas":"euroleague_zalgiris",
    "crvenazvezdameridianbet":"euroleague_crvena_zvezda_belgrade",
    "maccabirapydtelaviv":"euroleague_maccabi_tel_aviv",
    "realmadrid":"euroleague_real_madrid",
}


def sources_for(ctx):
    """Relevant clubs by canonical identity and explicit sponsor aliases.

    The 82-entry directory is the team registry, NOT an injury source.
    EuroLeague additionally reviews three editorial indexes; EuroCup gets
    its exact two official club indexes, never EuroLeague-specific articles.
    """
    league=ctx.get("league") if isinstance(ctx,dict) else None
    if league not in ("EUROLEAGUE","EUROCUP"):
        return []
    rows=([dict(name=name,url=url,kind="SECONDARY_EDITORIAL")
           for name,url in SITE_URLS] if league=="EUROLEAGUE" else [])
    from hybrid_engine.official_all_82_club_batch import load_all_82
    clubs=[c for c in load_all_82() if c["league"]==league]
    by_name={name_key(c["official_team_name"]):c for c in clubs}
    by_key={c["club_key"]:c for c in clubs}
    selected=set()
    for side in ("home","away"):
        name=name_key(ctx.get(side,{}).get("official_name"))
        club=by_name.get(name)
        if club is None and league=="EUROLEAGUE":
            key=KNOWN_ALIASES.get(name)
            club=by_key.get(key) if key else None
        if club is not None:
            selected.add(club["club_key"])
    rows.extend(dict(name=c["club_key"],url=c["official_news_entry_url"],
                     kind="OFFICIAL_CLUB_INDEX") for c in clubs
                if c["club_key"] in selected)
    return rows


def _safe_url(value):
    u=urlsplit(value)
    return (u.scheme=="https" and bool(u.hostname) and u.username is None and
            u.password is None and u.port is None and not u.query and not u.fragment and
            u.hostname not in ("localhost","127.0.0.1","0.0.0.0") and
            all(c.isascii() and (c.isalnum() or c in "-.") for c in u.hostname))


def request(url,*,mime="text/html",limit=MAX_BYTES):
    """Small fixed HTTPS request: no redirects, HTML-only, no exception leaks."""
    if not _safe_url(url):
        return dict(status="URL_REFUSED")
    try:
        began=time.monotonic()
        with requests.get(url,headers={"User-Agent":UA,"Accept":mime},
                          timeout=(0.5,0.8),allow_redirects=False,stream=True) as r:
            if r.status_code!=200:
                return dict(status=("SOURCE_RATE_LIMITED" if r.status_code==429 else
                                    "SOURCE_HTTP_NOT_200"),http_status=r.status_code)
            reported=r.headers.get("Content-Type","").split(";",1)[0].strip().lower()
            if reported!=mime:
                return dict(status="SOURCE_UNEXPECTED_MIME",mime=reported[:50])
            parts=[];total=0
            for buf in r.iter_content(chunk_size=8192):
                if time.monotonic()-began>MAX_FETCH_SECONDS:
                    return dict(status="SOURCE_DEADLINE")
                total+=len(buf)
                if total>limit:return dict(status="SOURCE_OVERSIZE")
                parts.append(buf)
        return dict(status="RECEIVED",body=b"".join(parts))
    except requests.RequestException:
        return dict(status="SOURCE_UNREACHABLE")


def _title(body):
    soup=BeautifulSoup(body[:MAX_BYTES],"html.parser")
    title=soup.title.get_text(" ",strip=True) if soup.title else ""
    return re.sub(r"\s+"," ",title)[:160]


def _page_candidates(body,source_url):
    """Unverified *public index* hints only; not player/fixture identities.

    Whitelist table statuses, drop conflicting duplicates and retain short
    metadata only. Article links are same HTTPS host and never followed here.
    """
    soup=BeautifulSoup(body[:MAX_BYTES],"html.parser")
    statuses={"out":"OUT_SITE_REPORTED","doubtful":"DOUBTFUL_SITE_REPORTED",
              "day to day":"DAY_TO_DAY_SITE_REPORTED","cleared":"CLEARED_SITE_REPORTED",
              "questionable":"QUESTIONABLE_SITE_REPORTED"}
    found={};conflicts=set()
    for table in soup.find_all("table")[:6]:
        header=table.find("tr")
        if header is None:continue
        headings=[name_key(x.get_text(" ",strip=True)) for x in header.find_all(["th","td"])]
        if not all(k in headings for k in ("player","team","status")):continue
        ix=[headings.index(k) for k in ("player","team","status")]
        for tr in table.find_all("tr")[1:81]:
            cells=tr.find_all(["th","td"])
            if len(cells)<=max(ix):continue
            player,team,status=[cells[i].get_text(" ",strip=True) for i in ix]
            key=(name_key(player),name_key(team))
            if not all(key) or len(player)>85 or len(team)>90:continue
            mapped=statuses.get(status.casefold().strip())
            if mapped is None:continue
            value=dict(player_text=player[:85],team_text=team[:90],
                       source_reported_status=mapped,
                       official_player_id=None,fixture_id=None,
                       source_publication_verified=False,
                       match_availability_verified=False,model_input=False)
            if key in found and found[key]["source_reported_status"]!=mapped:
                conflicts.add(key)
            found[key]=value
    rows=[v for k,v in found.items() if k not in conflicts][:12]
    root=urlsplit(source_url)
    links=[];seen=set()
    for a in soup.find_all("a",href=True):
        label=a.get_text(" ",strip=True)
        if not any(word in name_key(label) for word in ("injur","sakat","absenc","sidelin")):
            continue
        href=urljoin(source_url,a["href"])
        parsed=urlsplit(href)
        if (parsed.scheme!="https" or parsed.hostname!=root.hostname or
            parsed.query or parsed.fragment or not parsed.path.startswith("/")):
            continue
        if href not in seen and href!=source_url:
            seen.add(href)
            links.append(dict(url=href,title=re.sub(r"\s+"," ",label)[:100],
                              article_read=False,publication_time_verified=False))
        if len(links)>=4:break
    return rows,links


def probe(spec,*,requester=request,now=None,read_article=False):
    """Robots must be readable and allow the index URL BEFORE fetching."""
    timestamp=int(time.time()) if now is None else int(now)
    name=spec.get("name");url=spec.get("url")
    result=dict(source=name,url=url,kind=spec.get("kind"),status="NOT_ATTEMPTED",
                observed_at_utc=timestamp,document_sha256=None,title=None,
                player_status_verified=False,fixture_verified=False,
                source_publication_clock_verified=False,model_input=False)
    if not isinstance(url,str) or not _safe_url(url):
        return dict(result,status="SOURCE_URL_REFUSED")
    parsed=urlsplit(url)
    robots_url="https://"+parsed.hostname+"/robots.txt"
    policy=requester(robots_url,mime="text/plain",limit=MAX_ROBOTS)
    if policy.get("status")!="RECEIVED" or not isinstance(policy.get("body"),bytes):
        return dict(result,status="SOURCE_ROBOTS_UNAVAILABLE",
                    robots_status=policy.get("status"))
    try:
        robot=RobotFileParser()
        robot.parse(policy["body"].decode("utf-8","replace").splitlines())
        if not robot.can_fetch(UA,url):
            return dict(result,status="SOURCE_ROBOTS_DISALLOW")
    except (ValueError,TypeError,UnicodeError):
        return dict(result,status="SOURCE_ROBOTS_INVALID")
    response=requester(url,mime="text/html",limit=MAX_BYTES)
    if response.get("status")!="RECEIVED":
        return dict(result,status=response.get("status","SOURCE_UNREACHABLE"),
                    http_status=response.get("http_status"))
    body=response.get("body")
    if type(body) is not bytes or len(body)>MAX_BYTES:
        return dict(result,status="SOURCE_BODY_INVALID")
    candidates,links=_page_candidates(body,url)
    articles=[]
    if read_article and links:
        # An index link is NOT an article. Fetch one bounded article separately
        # under that article's own robots policy; never follow a redirect.
        from hybrid_engine.europe_injury_article_source import observe_article
        articles=[observe_article(spec,links[0],requester=requester,now=timestamp)]
    return dict(result,status="SOURCE_INDEX_OBSERVED_CANDIDATES_ONLY",
                title=_title(body),document_sha256=hashlib.sha256(body).hexdigest(),
                published_at_utc=None,source_publication_clock_verified=False,
                unverified_player_candidates=candidates,
                unverified_injury_article_links=links,
                inspected_articles=articles,
                candidate_count=len(candidates)+sum(
                    len(a.get("unverified_player_candidates",[])) for a in articles))


class PublicEuroInjuryNewsHub:
    """One bounded look-up shared across callbacks; no persistent source text."""
    def __init__(self,*,clock=time.time,requester=request,enabled=False):
        self.clock=clock
        self.requester=requester
        self.enabled=enabled is True
        self._lock=threading.Lock()
        self._cache={}
        self._valid_until=0
        self._last=[]
    def public_status(self):
        # No network, and no provider secrets.
        with self._lock:
            return dict(enabled=self.enabled,source_names=[x[0] for x in SITE_URLS],
                        last_statuses=[dict(source=x.get("source"),status=x.get("status"),
                                            http_status=x.get("http_status"))
                                       for x in self._last],cached_until_utc=self._valid_until,
                        model_input=False,fixture_player_status_verified=False)
    def review(self,ctx):
        if not self.enabled:
            return dict(status="PUBLIC_NEWS_HUB_DISABLED",sources=[],
                        player_status_verified=False,model_input=False)
        if not isinstance(ctx,dict) or ctx.get("league") not in ("EUROLEAGUE","EUROCUP"):
            return dict(status="UNSUPPORTED_LEAGUE",sources=[],
                        player_status_verified=False,model_input=False)
        when=int(self.clock())
        if type(ctx.get("fixture_start_utc")) is not int or when>=ctx["fixture_start_utc"]:
            return dict(status="POST_TIPOFF_NO_NEW_NEWS",sources=[],
                        player_status_verified=False,model_input=False)
        with self._lock:
            key=(ctx.get("fixture_id"),tuple(ctx.get(x,{}).get("official_name") for x in ("home","away")))
            if key in self._cache and when<self._valid_until:
                return dict(self._cache[key])
            specs=sources_for(ctx)
            rows=[]
            # The three editorial sources and at most two official club indexes
            # run concurrently under a strict callback budget. Each worker makes
            # at most a robots and an index request (no redirects).
            with ThreadPoolExecutor(max_workers=5) as pool:
                futures=[pool.submit(probe,x,requester=self.requester,now=when,read_article=True) for x in specs]
                for future,spec in zip(futures,specs):
                    try:
                        rows.append(future.result(timeout=TIME_BUDGET))
                    except Exception:
                        rows.append(dict(source=spec["name"],url=spec["url"],
                                         kind=spec["kind"],status="SOURCE_TIMEOUT_OR_INVALID",
                                         player_status_verified=False,model_input=False))
            report=dict(status="PUBLIC_NEWS_SOURCES_REVIEWED_CANDIDATES_ONLY",
                        sources=rows,observed_at_utc=when,
                        player_status_verified=False,verified_player_records=[],
                        lineup_verified=False,rotation_minutes_verified=False,
                        model_input=False,original_forecast_modified=False)
            self._last=rows
            self._cache={key:report}
            self._valid_until=min(when+COOLDOWN,ctx["fixture_start_utc"])
            return dict(report)


def render(report):
    lines=["KAMUYA AÇIK KADRO / SAKATLIK HABER KAYNAKLARI (GÖZLEM)"]
    for r in report.get("sources",[]):
        line=(r["source"]+" / "+r["status"]+
              (" HTTP "+str(r["http_status"]) if r.get("http_status") else ""))
        lines.append(line)
        if r.get("title"):
            lines.append("Sayfa başlığı: "+r["title"])
        # Only short, explicitly UNVERIFIED secondary player hints. Never
        # attribute these to the requested fixture or infer healthy status.
        for candidate in r.get("unverified_player_candidates",[])[:2]:
            lines.append("GENEL LİG ADAYI / MAÇ DOĞRULANMADI: "+
                         candidate["player_text"]+" · "+candidate["team_text"]+
                         " · "+candidate["source_reported_status"])
        for link in r.get("unverified_injury_article_links",[])[:2]:
            lines.append("Haber bağlantı adayı: "+link["url"])
        for article in r.get("inspected_articles",[]):
            lines.append("Makale erişimi: "+article["status"]+
                         ((" · "+str(article["http_status"])) if article.get("http_status") else ""))
            if article.get("source_published_at_utc") is not None:
                lines.append("Kaynak yayın UTC: "+str(article["source_published_at_utc"]))
            else:
                lines.append("Makale yayın saati doğrulanmadı.")
            for candidate in article.get("unverified_player_candidates",[])[:4]:
                lines.append("HABER METNİNDE OYNAMAYACAK ADAYI / MAÇ DOĞRULANMADI: "+
                             candidate["player_name_text"]+" · "+candidate["source_reported_status"])
    lines.extend(["EuroLeague resmî kaynağı ve resmî sezon kimlik adaptörü ayrıca çalışır.",
                  "X/kulüp sosyal medya API'si: YETKİLİ ERİŞİM YOK, OTOMATİK SORGULANMIYOR.",
                  "Kaynak sayfası bulunması oyuncunun maçta OUT/AVAILABLE olduğunu kanıtlamaz.",
                  "Yayın anı ve maça özel oyuncu eşleştirmesi doğrulanmadan skor değişmez."])
    return "\n".join(lines)

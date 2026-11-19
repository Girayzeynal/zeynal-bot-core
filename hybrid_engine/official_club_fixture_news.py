"""Two official club news entry probes for a European fixture's roster button.

Reads the already-registered all-82 website/news directory. Operates only
on the TWO teams in the fixture, never 82 unrelated sites per callback.
One robots policy + one official news index per club, no redirects, strict
timeout and bounded HTML, no PDF or historical forecast mutation.
Official club news is NOT an independently verified injury/roster claim.
"""
from html.parser import HTMLParser
import html
import time
from urllib.parse import urljoin,urlsplit

from core.league_identity import normalize_name
from hybrid_engine.official_all_82_club_batch import load_all_82
from hybrid_engine.official_club_sources import (
    _request,allowed_by_robots,MAX_BODY,MAX_ROBOTS,parse_metadata)

EXPLICIT_SPONSOR_ALIASES={
    ("EUROLEAGUE","Armani Olimpia Milan"):"euroleague_ea7_emporio_armani_milan",
    ("EUROLEAGUE","Armani Olimpia Milano"):"euroleague_ea7_emporio_armani_milan",
    ("EUROLEAGUE","EA7 Emporio Armani Milan"):"euroleague_ea7_emporio_armani_milan",
    ("EUROLEAGUE","Fenerbahce Tarfin Istanbul"):"euroleague_fenerbahce_istanbul",
    ("EUROLEAGUE","Fenerbahçe Tarfin Istanbul"):"euroleague_fenerbahce_istanbul",
    ("EUROLEAGUE","Fenerbahçe Beko Istanbul"):"euroleague_fenerbahce_istanbul",
    ("EUROLEAGUE","Panathinaikos AKTOR Athens"):"euroleague_panathinaikos_athens",
    ("EUROLEAGUE","Zalgiris Kaunas"):"euroleague_zalgiris",
    ("EUROLEAGUE","Žalgiris Kaunas"):"euroleague_zalgiris",
}
MAX_LINKS=3

class _Headlines(HTMLParser):
    def __init__(self,base,host):
        super().__init__(convert_charrefs=True)
        self.base=base
        self.host=host
        self.href=None
        self.parts=[]
        self.links=[]
        self.hidden=0
    def handle_starttag(self,tag,attrs):
        if tag in ("script","style","noscript","svg"):
            self.hidden+=1
        if tag=="a" and self.hidden==0:
            data=dict(attrs)
            link=data.get("href")
            if type(link) is not str or len(link)>1024:return
            full=urljoin(self.base,link)
            u=urlsplit(full)
            if u.scheme!="https" or u.hostname!=self.host or u.query or u.fragment:
                return
            if u.path.rstrip("/")==urlsplit(self.base).path.rstrip("/"):
                return
            self.href=full
            self.parts=[]
    def handle_data(self,data):
        if self.href and self.hidden==0:
            self.parts.append(data[:180])
    def handle_endtag(self,tag):
        if tag=="a" and self.href:
            title=" ".join(" ".join(self.parts).split())[:120]
            if title and len(title)>=8 and self.href not in [x["url"] for x in self.links]:
                self.links.append(dict(title=title,url=self.href))
            self.href=None
            self.parts=[]
        if tag in ("script","style","noscript","svg") and self.hidden>0:
            self.hidden-=1

def _resolve(league,name,rows):
    by_key={x["club_key"]:x for x in rows}
    exact=[r for r in rows if r["league"]==league and
           normalize_name(r["official_team_name"])==normalize_name(name)]
    if len(exact)==1:return exact[0]
    if exact:return None
    key=EXPLICIT_SPONSOR_ALIASES.get((league,name))
    if key and key in by_key and by_key[key]["league"]==league:
        return by_key[key]
    return None

def read_fixture_club_news(ctx,*,requester=_request,clock=time.time,allow_no_fixture=False):
    """Return source index evidence only, not player medical availability."""
    if ctx.get("league") not in ("EUROLEAGUE","EUROCUP"):
        raise ValueError("OFFICIAL_FIXTURE_NEWS_LEAGUE_REQUIRED")
    start=ctx.get("fixture_start_utc")
    now=int(clock())
    if type(start) is not int or start<=0:
        if not allow_no_fixture or start is not None:
            raise ValueError("OFFICIAL_FIXTURE_NEWS_TIPOFF_REQUIRED")
    if start is not None and now>=start:
        return dict(status="POST_TIPOFF_NO_NEW_SOURCE_POLL",
            rows=[],requests=0,roster_verified=False,injury_verified=False,
            model_input=False,archives_modified=False)
    rows=load_all_82()
    out=[];requests=0
    for side in ("home","away"):
        team=ctx.get(side)
        if type(team) is not dict or type(team.get("official_name")) is not str:
            raise ValueError("OFFICIAL_FIXTURE_NEWS_TEAM_NAME_REQUIRED")
        item=_resolve(ctx["league"],team["official_name"],rows)
        if not item:
            out.append(dict(side=side,team=team["official_name"],
                            status="CLUB_OFFICIAL_IDENTITY_NOT_EXACTLY_RESOLVED"))
            continue
        news=item["official_news_entry_url"]
        host=urlsplit(news).hostname
        entry=dict(side=side,team=team["official_name"],
            club_key=item["club_key"],official_site_url=item["official_site_url"],
            news_url=news,news_type=item["news_entry_kind"],
            status="NOT_ATTEMPTED",headlines=[],
            injury_verified=False,player_identity_verified=False)
        out.append(entry)
        policy=requester("https://"+host+"/robots.txt",limit=MAX_ROBOTS,
                         expected_mime="text/plain")
        requests+=1
        if (type(policy) is not dict or
            policy.get("status")!="DOCUMENT_RECEIVED" or
            type(policy.get("body")) is not bytes):
            entry["status"]="ROBOTS_NOT_AVAILABLE_NEWS_NOT_FETCHED"
            entry["robots_http_status"]=policy.get("http_status") if isinstance(policy,dict) else None
            continue
        if not allowed_by_robots(policy["body"].decode("utf-8","replace"),news):
            entry["status"]="ROBOTS_DISALLOW_NEWS_NOT_FETCHED"
            continue
        if start is not None and int(clock())>=start:
            entry["status"]="TIPOFF_REACHED_NEWS_NOT_FETCHED"
            continue
        doc=requester(news,limit=MAX_BODY,expected_mime="text/html")
        requests+=1
        if type(doc) is not dict or doc.get("status")!="DOCUMENT_RECEIVED":
            entry["status"]="OFFICIAL_NEWS_HTTP_OR_MIME_UNAVAILABLE"
            entry["http_status"]=doc.get("http_status") if isinstance(doc,dict) else None
            continue
        raw=doc.get("body")
        observed=doc.get("observed_at_utc")
        if (type(raw) is not bytes or not 0<len(raw)<=MAX_BODY or
            type(observed) is not int or not 0<observed<=int(clock()) or
            (start is not None and observed>=start)):
            entry["status"]="OFFICIAL_NEWS_SOURCE_CLOCK_OR_BODY_UNVERIFIED"
            continue
        page=parse_metadata(raw,observed_at_utc=observed)
        headers=_Headlines(news,host)
        headers.feed(raw.decode("utf-8","replace"))
        entry.update(status="OFFICIAL_NEWS_INDEX_OBSERVED_ONLY",
                     observed_at_utc=observed,
                     index_title=page.get("page_title") or "",
                     headlines=headers.links[:MAX_LINKS])
    return dict(status=("TEAM_ONLY_OFFICIAL_SOURCE_REVIEW_NOT_FIXTURE_VERIFIED"
                        if start is None else
                        "FIXTURE_OFFICIAL_CLUB_NEWS_INDEX_REVIEW_V1"),
        rows=out,requests=requests,clubs_expected=2,
        injury_verified=False,roster_verified=False,
        verified_player_count=0,model_input=False,
        original_forecast_modified=False,archives_modified=False)

def render_fixture_news(review):
    lines=["<b>RESMÎ KULÜP HABER KAYNAKLARI</b>",
           "Bunlar haber sayfası gözlemleridir; doğrulanmış oyuncu OUT veya dakika etkisi değildir."]
    if review["status"]=="POST_TIPOFF_NO_NEW_SOURCE_POLL":
        return "\n".join(lines+["Maç başlangıcı geçti; tarihsel haber yeni tahmin girdisi sayılmadı."])
    if review["status"]=="TEAM_ONLY_OFFICIAL_SOURCE_REVIEW_NOT_FIXTURE_VERIFIED":
        lines.append("Maç kimliği ve oyuncu uygunluğu doğrulanmadı; bu yalnız takım haber girişidir.")
    for row in review["rows"]:
        lines.append("")
        lines.append(html.escape(row["team"])+" · "+html.escape(row["status"]))
        if row.get("official_site_url"):
            lines.append("Kulüp sitesi: "+html.escape(row["official_site_url"]))
            lines.append("Resmî haber: "+html.escape(row["news_url"]))
        if row.get("observed_at_utc"):
            lines.append("İlk olmayan güncel gözlem UTC: "+str(row["observed_at_utc"]))
        for headline in row.get("headlines",[]):
            lines.append("• "+html.escape(headline["title"])+" — "+html.escape(headline["url"]))
    lines.append("\nBu kontrolün sonucu mevcut tahmini veya güven yüzdesini değiştirmez.")
    return "\n".join(lines)

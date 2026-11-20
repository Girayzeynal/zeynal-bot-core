"""Opt-in, read-only HoopsAPI market observation for isolated Telegram only.

Requires a user's own free API key; NO calls or secret logging by default.
Strict same-fixture UTC+ordered-team match, no invented prices or model impact.
Free plan is 10 total API calls/day; local ceiling 8 calls/day leaves headroom.
"""
from datetime import datetime,timezone
import html
import json
import math
import os
import re
import threading
import time
import unicodedata
from urllib.error import HTTPError,URLError
from urllib.parse import quote
from urllib.request import build_opener,Request,HTTPRedirectHandler

BASE="https://hoopsapi.com/api/v1"
COMPETITION={"EUROLEAGUE":"Europe - Euroleague"}
PERIODS=("ft","h1","h2","q1","q2","q3","q4")
MARKETS=("moneyline","spread","total","team_total_home","team_total_away")
LIMIT=8
MAX_BYTES=512*1024
ALIASES={"partizanmozzartbet":"partizan","partizanmozzartbetbelgrade":"partizan",
         "partizan":"partizan","besiktasfuzulistanbul":"besiktas",
         "besiktasistanbul":"besiktas","besiktasjk":"besiktas",
         "besiktas":"besiktas"}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        return None


def default_request(url,key):
    if not isinstance(url,str) or not (
        url==BASE+"/games?competition=Europe%20-%20Euroleague" or
        re.fullmatch(re.escape(BASE)+r"/games/[1-9][0-9]{0,12}",url)):
        return {"status":"URL_REFUSED"}
    if not isinstance(key,str) or not 12<=len(key)<=512 or any(ord(c)<33 for c in key):
        return {"status":"KEY_INVALID"}
    request=Request(url,headers={"Authorization":"Bearer "+key,"Accept":"application/json",
                                 "User-Agent":"ZEYNAL-Private-Market-Observation/1"})
    try:
        with build_opener(NoRedirect()).open(request,timeout=3) as response:
            if response.status!=200 or response.headers.get_content_type()!="application/json":
                return {"status":"UNEXPECTED_RESPONSE"}
            raw=response.read(MAX_BYTES+1)
            if len(raw)>MAX_BYTES:return {"status":"RESPONSE_TOO_LARGE"}
            if key.encode() in raw:return {"status":"SECRET_ECHO_REFUSED"}
            document=json.loads(raw)
            return {"status":"RECEIVED","document":document,
                    "observed_at_utc":int(time.time())}
    except HTTPError as exc:
        code=exc.code
        exc.close()
        return {"status":("LIMIT_REACHED" if code==429 else
                          "ACCESS_DENIED" if code in (401,403) else "HTTP_ERROR"),
                "http_status":code}
    except (URLError,OSError,ValueError,TypeError,json.JSONDecodeError):
        return {"status":"SOURCE_UNAVAILABLE"}


def namekey(value):
    if not isinstance(value,str):return ""
    value=unicodedata.normalize("NFKD",value).casefold()
    value="".join(c for c in value if not unicodedata.combining(c))
    key="".join(c for c in value if c.isalnum())
    return ALIASES.get(key,key)


def iso_utc(value):
    if not isinstance(value,str):raise ValueError("MARKET_TIMESTAMP_REQUIRED")
    dt=datetime.fromisoformat(value.replace("Z","+00:00"))
    if dt.tzinfo is None:raise ValueError("MARKET_UTC_REQUIRED")
    return int(dt.timestamp())


def bound_game(g,ctx):
    try:
        return (g["competition"].casefold()==COMPETITION[ctx["league"]].casefold()
                and iso_utc(g["start_time"])==ctx["fixture_start_utc"]
                and namekey(g["home"])==namekey(ctx["home"]["official_name"])
                and namekey(g["away"])==namekey(ctx["away"]["official_name"]))
    except (KeyError,ValueError,TypeError,AttributeError):
        return False


def valid_pair(value,market):
    if not isinstance(value,dict):return None
    kinds=("home","away") if market in ("moneyline","spread") else ("over","under")
    a,b=value.get(kinds[0]),value.get(kinds[1])
    if any(type(x) not in (float,int) or not math.isfinite(x) or not 1<x<=1000 for x in (a,b)):
        return None
    line=value.get("line")
    if market=="moneyline":
        line=0.
    elif type(line) not in (int,float) or not math.isfinite(line) or abs(line)>500:
        return None
    return {"line":float(line),"prices":{kinds[0]:float(a),kinds[1]:float(b)}}


def parse_lines(g,*,now):
    periods=g.get("periods");alternates=g.get("lines",{})
    providers=g.get("providers",{})
    if not isinstance(periods,dict) or not isinstance(alternates,dict) or not isinstance(providers,dict):
        raise ValueError("ODDS_MARKET_SCHEMA")
    rows=[];seen=set();missing_clock=0;stale=0;bounded=False
    for period in PERIODS:
        main=periods.get(period,{})
        extras=alternates.get(period,{})
        if not isinstance(main,dict) or not isinstance(extras,dict):continue
        for bookmaker in sorted(set(main)|set(extras))[:12]:
            if not re.fullmatch(r"[a-z0-9_-]{2,40}",bookmaker):continue
            info=providers.get(bookmaker,{})
            if not isinstance(info,dict):continue
            stamp=info.get("captured_at")
            try:captured=iso_utc(stamp)
            except (ValueError,TypeError):
                missing_clock+=1;continue
            if captured>now+60 or now-captured>1800:
                stale+=1;continue
            for source,altern in ((main.get(bookmaker,{}),False),(extras.get(bookmaker,{}),True)):
                if not isinstance(source,dict):continue
                for market in MARKETS:
                    entries=source.get(market,[])
                    if not isinstance(entries,list):entries=[entries]
                    for item in entries[:80]:
                        quote_row=valid_pair(item,market)
                        if quote_row is None:continue
                        k=(period,bookmaker,market,quote_row["line"])
                        if k in seen:continue
                        seen.add(k)
                        rows.append(dict(period=period,bookmaker=bookmaker,market=market,
                                         **quote_row,captured_at_utc=captured,alternate=altern))
                        if len(rows)>=320:
                            bounded=True
                            break
                    if bounded:break
                if bounded:break
            if bounded:break
        if bounded:break
    return {"rows":rows,"bounded":bounded,"missing_clock":missing_clock,"stale":stale}


class HoopsFreeMarket:
    def __init__(self,*,requester=default_request,clock=time.time):
        self.requester=requester
        self.clock=clock
        self.lock=threading.Lock()
        self.calls={}
        self.cache={}
        self.cooldown=0

    def _get(self,url,key,ttl):
        now=int(self.clock())
        today=now//86400
        with self.lock:
            cached=self.cache.get(url)
            if cached and now-cached[0]<=ttl:return cached[1]
            if now<self.cooldown:return {"status":"SOURCE_COOLDOWN"}
            used=self.calls.get(today,0)
            if used>=LIMIT:return {"status":"LOCAL_FREE_DAILY_BUDGET"}
            self.calls={today:used+1}
            try:result=self.requester(url,key)
            except Exception:result={"status":"SOURCE_UNAVAILABLE"}
            if result.get("status")=="RECEIVED":
                if len(self.cache)>=10:self.cache.pop(next(iter(self.cache)))
                self.cache[url]=(now,result)
            else:self.cooldown=now+(3600 if result.get("status")=="LIMIT_REACHED" else 120)
            return result

    def review(self,ctx):
        now=int(self.clock())
        if os.getenv("ZEYNAL_HOOPSAPI_ENABLED")!="1":
            return {"status":"OPT_IN_DISABLED","quotes":[],"model_input":False}
        key=os.getenv("ZEYNAL_HOOPSAPI_KEY","").strip()
        if not key:return {"status":"FREE_API_KEY_NOT_CONFIGURED","quotes":[],"model_input":False}
        if ctx.get("league") not in COMPETITION:
            return {"status":"LEAGUE_NOT_SUPPORTED","quotes":[],"model_input":False}
        if type(ctx.get("fixture_start_utc")) is not int:
            return {"status":"FIXTURE_UTC_REQUIRED","quotes":[],"model_input":False}
        if now>=ctx["fixture_start_utc"]:
            return {"status":"POST_TIPOFF_REFERENCE_ONLY_NO_LIVE_QUERY","quotes":[],"model_input":False}
        index=self._get(BASE+"/games?competition=Europe%20-%20Euroleague",key,ttl=600)
        if index.get("status")!="RECEIVED":
            return {"status":"LIST_"+index.get("status","INVALID"),"quotes":[],"model_input":False}
        doc=index.get("document")
        if not isinstance(doc,dict) or not isinstance(doc.get("games"),list) or len(doc["games"])>300:
            return {"status":"LIST_SCHEMA_REJECTED","quotes":[],"model_input":False}
        matches=[g for g in doc["games"] if isinstance(g,dict) and bound_game(g,ctx)]
        if len(matches)!=1:
            return {"status":"FIXTURE_NOT_UNIQUELY_MATCHED","candidate_count":len(matches),
                    "quotes":[],"model_input":False}
        game_id=matches[0].get("game_id")
        if type(game_id) is not int or not 0<game_id<10**13:
            return {"status":"GAME_ID_INVALID","quotes":[],"model_input":False}
        detail=self._get(BASE+"/games/"+str(game_id),key,ttl=600)
        if detail.get("status")!="RECEIVED":
            return {"status":"DETAIL_"+detail.get("status","INVALID"),"quotes":[],"model_input":False}
        game=detail.get("document")
        if (not isinstance(game,dict) or game.get("game_id")!=game_id or
            not bound_game(game,ctx)):
            return {"status":"DETAIL_IDENTITY_MISMATCH","quotes":[],"model_input":False}
        try:prices=parse_lines(game,now=now)
        except ValueError:
            return {"status":"QUOTE_SCHEMA_REJECTED","quotes":[],"model_input":False}
        return {"status":"CURRENT_REFERENCE_ONLY_NOT_SETTLEMENT_VERIFIED",
                "source":"HoopsAPI","game_id":game_id,"observed_at_utc":now,
                "quotes":prices["rows"],"bounded":prices["bounded"],
                "stale_books":prices["stale"],"missing_clock":prices["missing_clock"],
                "captured_before_tipoff":now<ctx["fixture_start_utc"],
                "model_input":False,"forecasts_recomputed":False,"original_prediction_modified":False}


def render(report):
    lines=["<b>ÜCRETSİZ PİYASA REFERANSI | HoopsAPI</b>",
           "Durum: "+html.escape(report["status"])]
    if report.get("status")!="CURRENT_REFERENCE_ONLY_NOT_SETTLEMENT_VERIFIED":
        lines.append("Nesine/İddaa fiyatı değildir; mevcut skor ve eski tahmin değişmedi.")
        return "\n".join(lines)
    rows=report["quotes"]
    names={"ft":"Maç (UZATMA DAHİL)","h1":"İlk yarı","h2":"İkinci yarı",
           "q1":"1. çeyrek","q2":"2. çeyrek","q3":"3. çeyrek","q4":"4. çeyrek"}
    translations={"moneyline":"Maç/çeyrek sonucu","spread":"Ev handikabı",
                  "total":"Toplam sayı","team_total_home":"Ev takım toplamı",
                  "team_total_away":"Dep takım toplamı"}
    lines.append("Sadece kaynağın sunduğu çizgiler: "+str(len(rows)))
    if report.get("bounded"):lines.append("UYARI: 320 kayıt bütçesi doldu; bütün alternatif baremler gösterilmedi.")
    lines.append("Ödeme/uzatma ve model kalibrasyonu doğrulanmadı; yön veya avantaj üretilmedi.")
    for row in rows[:24]:
        l=("%.1f"%row["line"])
        p=row["prices"]
        keys=list(p)
        lines.append(html.escape(names[row["period"]]+" · "+row["bookmaker"]+" · "+
                    translations[row["market"]]+" "+l+" · "+
                    keys[0]+" "+("%.2f"%p[keys[0]])+" / "+
                    keys[1]+" "+("%.2f"%p[keys[1]])))
    if len(rows)>24:lines.append("... "+str(len(rows)-24)+" ek çizgi için sayfalı görünüm gerekli.")
    return "\n".join(lines)

"""Official EuroLeague/EuroCup team season registration lookup (NOT injury status).

One bounded native request per exact competition/season/club. This intentionally
does not infer starters, availability, minutes, or numeric point adjustments.
Never backdates a source observation into an earlier frozen prediction.
"""
import hashlib
import json
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler

HOST="https://api-live.euroleague.net"
MAX_BYTES=256*1024
_TIMEOUT=4.0
_CODE=re.compile(r"^[A-Z0-9]{2,5}$")
_YEAR=re.compile(r"^20[0-9]{2}$")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        return None


def endpoint(league,season,club):
    comp={"EUROLEAGUE":"E","EUROCUP":"U"}.get(league)
    if comp is None or type(season) is not str or not _YEAR.fullmatch(season[:4]) or season!=f"{season[:4]}/{int(season[:4])+1}" or type(club) is not str or not _CODE.fullmatch(club):
        raise ValueError("NATIVE_ROSTER_EXACT_LEAGUE_SEASON_CLUB_REQUIRED")
    return f"{HOST}/v2/competitions/{comp}/seasons/{comp}{season[:4]}/clubs/{club}/people"


def fetch_native(url):
    """Transport is fixed-URL and bounded; no redirect, no HTML/error parsing."""
    if not (url.startswith(HOST+"/v2/competitions/") and
            re.fullmatch(r"https://api-live\.euroleague\.net/v2/competitions/[EU]/seasons/[EU]20[0-9]{2}/clubs/[A-Z0-9]{2,5}/people",url)):
        raise ValueError("NATIVE_ROSTER_URL_NOT_ALLOWLISTED")
    req=Request(url,headers={"Accept":"application/json","User-Agent":"ZeynalBasketballRosterAudit/1.0"})
    try:
        with build_opener(_NoRedirect).open(req,timeout=_TIMEOUT) as response:
            if response.status!=200 or response.headers.get_content_type()!="application/json":
                return {"status":"UNSUPPORTED_RESPONSE","http_status":response.status}
            body=response.read(MAX_BYTES+1)
            if len(body)>MAX_BYTES:return {"status":"OVERSIZE_RESPONSE"}
            return {"status":"RECEIVED","body":body,"observed_at_utc":int(time.time())}
    except HTTPError as exc:
        return {"status":"SOURCE_HTTP_ERROR","http_status":exc.code}
    except (TimeoutError,URLError,OSError):
        return {"status":"SOURCE_UNREACHABLE"}


def parse_native(receipt,league,season,club,*,now=None):
    """Admit registered named players only; missing player codes remain missing."""
    now=int(time.time()) if now is None else now
    url=endpoint(league,season,club)
    if receipt.get("status")!="RECEIVED":
        return {"status":receipt.get("status","NO_SOURCE"),"source_url":url,
                "http_status":receipt.get("http_status"),"registered_players":[],
                "player_status_verified":False,"model_input":False}
    observed=receipt.get("observed_at_utc")
    body=receipt.get("body")
    if type(observed) is not int or not 0<observed<=now or now-observed>600 or type(body) is not bytes or len(body)>MAX_BYTES:
        raise ValueError("NATIVE_ROSTER_SOURCE_CLOCK_OR_SIZE")
    try:raw=json.loads(body)
    except (ValueError,UnicodeError) as exc:raise ValueError("NATIVE_ROSTER_JSON_UNVERIFIED") from exc
    if not isinstance(raw,list) or len(raw)>50:
        raise ValueError("NATIVE_ROSTER_CLUB_PAYLOAD_SHAPE")
    season_code=("E" if league=="EUROLEAGUE" else "U")+season[:4]
    players=[]
    ids=set()
    for record in raw:
        if not isinstance(record,dict):raise ValueError("NATIVE_ROSTER_PLAYER_SHAPE")
        if record.get("type")!="J":continue
        person=record.get("person");club_ref=record.get("club");season_ref=record.get("season")
        if not all(isinstance(x,dict) for x in (person,club_ref,season_ref)) or club_ref.get("code")!=club or season_ref.get("code")!=season_code:
            raise ValueError("NATIVE_ROSTER_IDENTITY_CONFLICT")
        name=person.get("name");code=person.get("code")
        if not isinstance(name,str) or not 1<=len(name.strip())<=110 or (code is not None and (not isinstance(code,str) or not 1<=len(code)<=32)):
            raise ValueError("NATIVE_ROSTER_PLAYER_NAME_OR_ID")
        if code is not None:
            if code in ids:raise ValueError("NATIVE_ROSTER_DUPLICATE_PLAYER_CODE")
            ids.add(code)
        players.append({"player_id":code,"name":name.strip(),"team_id":club,
                        "registered_for_season":True,
                        "status":"REGISTRATION_ONLY_NOT_MATCH_AVAILABILITY"})
    if not players:
        return {"status":"NO_USABLE_REGISTERED_PLAYERS","source_url":url,
                "registered_players":[],"player_status_verified":False,"model_input":False}
    return {"status":"OFFICIAL_SEASON_REGISTRATION_OBSERVED",
            "source_url":url,"body_sha256":hashlib.sha256(body).hexdigest(),
            "observed_at_utc":observed,"registered_players":players,
            "named_players":len(players),"mapped_player_ids":len(ids),
            "player_status_verified":False,"minutes_verified":False,
            "lineup_verified":False,"model_input":False}


def pair(ctx,*,getter=fetch_native,clock=time.time):
    """Never issues a query unless IDs are already exact official club codes."""
    league=ctx.get("league");season=ctx.get("season")
    if league not in ("EUROLEAGUE","EUROCUP"):
        raise ValueError("NATIVE_ROSTER_COMPETITION")
    rows={}
    for side in ("home","away"):
        code=ctx[side].get("provider_id")
        try:url=endpoint(league,season,code)
        except (TypeError,ValueError):
            rows[side]={"status":"UNVERIFIED_NATIVE_CLUB_CODE",
                        "registered_players":[],"model_input":False}
            continue
        try:
            receipt=getter(url)
            rows[side]=parse_native(receipt,league,season,code,now=int(clock()))
        except (ValueError,KeyError,TypeError):
            rows[side]={"status":"SOURCE_IDENTITY_OR_SCHEMA_REFUSED",
                        "source_url":url,"registered_players":[],"model_input":False}
    return {"format":"ZEYNAL_OFFICIAL_EUROPE_PLAYER_DIRECTORY_V1",
            "fixture_id":ctx.get("fixture_id"),"observed_at_utc":int(clock()),
            "teams":rows,"model_input":False,"injury_status_verified":False,
            "source_scope":"SEASON_REGISTRATION_NOT_MATCH_AVAILABILITY"}


def render_public(report):
    rows=["RESMÎ EUROLEAGUE OYUNCU KİMLİĞİ KONTROLÜ (SAKATLIK RAPORU DEĞİL)"]
    for side in ("home","away"):
        r=report["teams"][side]
        rows.append(side.upper()+": "+r["status"])
        if r.get("status")=="OFFICIAL_SEASON_REGISTRATION_OBSERVED":
            rows.append("Kayıtlı oyuncu: "+str(r["named_players"])+
                        " | kimliği eşleşebilir oyuncu: "+str(r["mapped_player_ids"]))
            rows.append("Kaynak: "+r["source_url"])
            rows.append("SHA-256: "+r["body_sha256"][:16])
            for player in r["registered_players"][:24]:
                rows.append("• "+player["name"]+" · "+(player["player_id"] or "RESMÎ ID YOK"))
    rows.extend(["Kayıtlı oyuncu sakatlık/ilk beş/dakika kanıtı değildir.",
                 "Oyuncu durumu ve sayısal skor etkisi doğrulanmadı; ilk tahmin değiştirilmedi."])
    return "\n".join(rows)

async def telegram_command(update,context):
    """Same read-only real-source command in isolated and Fly bots."""
    import asyncio
    args=context.args or []
    if len(args)!=4:
        await update.effective_message.reply_text(
            "Kullanım: /sourceplayers EUROLEAGUE 2026/2027 ZAL PAN\n"
            "Bu komut oyuncu sezon kayıtlarını kontrol eder, sakatlık ve skor hesabı değildir.")
        return
    league,season,home,away=args
    ctx={"league":league.upper(),"season":season,
         "fixture_id":None,"home":{"provider_id":home.upper()},
         "away":{"provider_id":away.upper()}}
    try:
        for side in ("home","away"):
            endpoint(ctx["league"],ctx["season"],ctx[side]["provider_id"])
        if ctx["home"]["provider_id"]==ctx["away"]["provider_id"]:
            raise ValueError("Same club")
        result=await asyncio.wait_for(asyncio.to_thread(pair,ctx),timeout=13)
        report=render_public(result)
    except (KeyError,TypeError,ValueError,asyncio.TimeoutError):
        report="Resmî takım/lig/sezon eşleşmesi doğrulanamadı. Örnek: /sourceplayers EUROLEAGUE 2026/2027 ZAL PAN"
    await update.effective_message.reply_text(report[:3500],parse_mode=None)


def command_handler():
    from telegram.ext import CommandHandler
    return CommandHandler("sourceplayers",telegram_command)


def _cli():
    import argparse
    p=argparse.ArgumentParser(description="Live official season roster smoke: never an injury report")
    p.add_argument("--league",default="EUROLEAGUE")
    p.add_argument("--season",default="2026/2027")
    p.add_argument("--home",default="ZAL")
    p.add_argument("--away",default="PAN")
    p.add_argument("--require-live",action="store_true")
    a=p.parse_args()
    ctx={"league":a.league,"season":a.season,"fixture_id":None,
         "home":{"provider_id":a.home},"away":{"provider_id":a.away}}
    result=pair(ctx)
    print(render_public(result))
    both=all(result["teams"][side]["status"]=="OFFICIAL_SEASON_REGISTRATION_OBSERVED"
             for side in ("home","away"))
    return 0 if both or not a.require_live else 2


if __name__=="__main__":
    raise SystemExit(_cli())

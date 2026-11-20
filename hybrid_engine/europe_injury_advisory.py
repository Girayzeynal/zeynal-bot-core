"""Opt-in current EuroLeague injuries feed, *not* match availability or model input.

RotoWire's public API documentation exposes current injured players with
InjuryStatus and Team.Code, but does not expose a fixture-scoped preforecast
publication clock. Only exact native player/team matches are shown; never
convert these current observations into historical forecast inputs.

This module cannot wager, fit, mutate scores, or write an archive.
"""
import hashlib
import json
import re
import time
import threading
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, build_opener, HTTPRedirectHandler

SOURCE="https://api.rotowire.com/Basketball/EURO/Injuries.php"
MAX_BYTES=256*1024
MAX_PLAYERS=300
TIMEOUT=2.0
STATUSES={"OUT":"OUT_REPORTED","GTD":"GAME_TIME_DECISION_REPORTED",
          "QUESTIONABLE":"QUESTIONABLE_REPORTED","DOUBTFUL":"DOUBTFUL_REPORTED"}
KEY=re.compile(r"^[A-Za-z0-9._-]{8,256}$")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch(*, api_key=None, enabled=False, opener=None, clock=time.time):
    """One bounded authorized request, disabled unless explicitly enabled.

    Never return/log the credential-bearing URL, headers or response body.
    """
    if enabled is not True or not api_key:
        return dict(status="INJURY_PROVIDER_NOT_CONFIGURED",source=SOURCE)
    if type(api_key) is not str or not KEY.fullmatch(api_key):
        return dict(status="INJURY_PROVIDER_KEY_INVALID",source=SOURCE)
    url=SOURCE+"?format=json&key="+quote(api_key,safe="")
    request=Request(url,headers={"Accept":"application/json",
                                  "User-Agent":"ZeynalInjuryAudit/1.0"})
    transport=opener if opener is not None else build_opener(NoRedirect).open
    try:
        with transport(request,timeout=TIMEOUT) as response:
            if response.status!=200 or response.headers.get_content_type()!="application/json":
                return dict(status="INJURY_PROVIDER_UNSUPPORTED_RESPONSE",source=SOURCE,
                            http_status=response.status)
            body=response.read(MAX_BYTES+1)
            if len(body)>MAX_BYTES:
                return dict(status="INJURY_PROVIDER_OVERSIZE",source=SOURCE)
        return dict(status="RECEIVED",source=SOURCE,observed_at_utc=int(clock()),
                    body_sha256=hashlib.sha256(body).hexdigest(),body=body)
    except HTTPError as exc:
        return dict(status="INJURY_PROVIDER_HTTP_ERROR",http_status=exc.code,source=SOURCE)
    except (URLError,OSError,TimeoutError):
        return dict(status="INJURY_PROVIDER_UNREACHABLE",source=SOURCE)


class AdvisoryClient:
    """Single bounded, quota-conscious client shared across fixture buttons.

    A key does not enable anything unless the deployment explicitly opts in.
    One successful request is reused for 5 minutes; a 429 is also cooled down
    for 5 minutes rather than repeated across multiple fixtures.
    """
    def __init__(self, api_key, *, enabled=False, getter=fetch, clock=time.time):
        if enabled is not True or type(api_key) is not str or not KEY.fullmatch(api_key):
            raise ValueError("EXPLICIT_AUTHORIZED_INJURY_SOURCE_REQUIRED")
        self._key=api_key
        self._getter=getter
        self.clock=clock
        self.lock=threading.Lock()
        self._cached=None
        self._valid_until=0

    def __call__(self):
        with self.lock:
            now=int(self.clock())
            if self._cached is not None and now<self._valid_until:
                return dict(self._cached)
            receipt=self._getter(api_key=self._key,enabled=True,clock=self.clock)
            if type(receipt) is not dict or type(receipt.get("status")) is not str:
                receipt=dict(status="INJURY_PROVIDER_RESPONSE_REFUSED",source=SOURCE)
            status=receipt["status"]
            delay=300 if status=="RECEIVED" or receipt.get("http_status")==429 else 60
            self._cached=dict(receipt)
            self._valid_until=now+delay
            return dict(self._cached)


def name_key(value):
    if type(value) is not str:
        return None
    words="".join(c if c.isalnum() or c.isspace() else " "
                  for c in unicodedata.normalize("NFKD",value).casefold()
                  if not unicodedata.combining(c))
    chunks=words.split()
    return tuple(sorted(chunks)) if len(chunks)>=2 else None


def bind(receipt, *, ctx, native_report, now):
    """Join by exact official club code and unique normalized player name.

    Never assume a third-party current injury status is a game-specific OUT.
    The source has no asserted historical publish time, so its rows are
    ineligible for the frozen original, regardless of source status.
    """
    result=dict(status="NO_ADMITTED_CURRENT_PLAYER_ROWS",source=SOURCE,
                observed_at_utc=None,player_rows=[],unmatched=0,
                injury_status_verified_for_fixture=False,
                original_prediction_eligible=False,model_input=False,
                forecast_changed=False)
    if type(ctx) is not dict or ctx.get("league")!="EUROLEAGUE":
        return dict(result,status="EUROLEAGUE_ONLY_INJURY_FEED")
    if type(receipt) is not dict or type(native_report) is not dict:
        return dict(result,status="PLAYER_SOURCE_OR_OFFICIAL_DIRECTORY_UNAVAILABLE")
    if receipt.get("status")!="RECEIVED":
        return dict(result,status=receipt.get("status","INJURY_PROVIDER_UNAVAILABLE"),
                    http_status=receipt.get("http_status"))
    if receipt.get("source")!=SOURCE:
        return dict(result,status="INJURY_PROVIDER_SOURCE_REFUSED")
    observed=receipt.get("observed_at_utc")
    if type(now) is not int or type(observed) is not int or not 0<observed<=now or now-observed>300:
        return dict(result,status="INJURY_PROVIDER_CAPTURE_CLOCK_REFUSED")
    start=ctx.get("fixture_start_utc")
    if type(start) is not int or observed>=start:
        return dict(result,status="POST_TIPOFF_INJURY_SOURCE_NOT_PREMATCH")
    body=receipt.get("body")
    pin=receipt.get("body_sha256")
    if (type(body) is not bytes or len(body)>MAX_BYTES or
        type(pin) is not str or hashlib.sha256(body).hexdigest()!=pin):
        return dict(result,status="INJURY_PROVIDER_BODY_PIN_REFUSED")
    try: document=json.loads(body)
    except (UnicodeError,ValueError):
        return dict(result,status="INJURY_PROVIDER_JSON_REFUSED")
    players=document.get("Players") if type(document) is dict else None
    if type(players) is not list or len(players)>MAX_PLAYERS:
        return dict(result,status="INJURY_PROVIDER_SCHEMA_REFUSED")
    lookup={}
    for side in ("home","away"):
        target=ctx.get(side)
        team=native_report.get("teams",{}).get(side)
        if (type(target) is not dict or type(team) is not dict or
            team.get("status")!="OFFICIAL_SEASON_REGISTRATION_OBSERVED"):
            continue
        team_code=target.get("provider_id")
        for p in team.get("registered_players",[]):
            if type(p) is not dict or p.get("team_id")!=team_code or not p.get("player_id"):
                continue
            key=name_key(p.get("name"))
            if key is not None:
                lookup.setdefault((team_code,key),[]).append(p["player_id"])
    rows=[];seen=set();unmatched=0
    for item in players:
        if type(item) is not dict:
            unmatched+=1;continue
        team=item.get("Team")
        team_code=team.get("Code") if type(team) is dict else None
        source_status=item.get("InjuryStatus")
        first=item.get("FirstName");last=item.get("LastName")
        if (type(team_code) is not str or type(first) is not str or type(last) is not str or
            type(source_status) is not str):
            unmatched+=1;continue
        status=STATUSES.get(source_status.upper())
        matched=lookup.get((team_code,name_key(first+" "+last)),[])
        if status is None or len(matched)!=1:
            unmatched+=1;continue
        identity=(team_code,matched[0])
        if identity in seen:
            unmatched+=1
            rows=[x for x in rows if (x["team_id"],x["player_id"])!=identity]
            continue
        seen.add(identity)
        rows.append(dict(team_id=team_code,player_id=matched[0],
                         name=first.strip()+" "+last.strip(),
                         source_reported_status=status,
                         match_availability_confirmed=False))
    rows.sort(key=lambda x:(x["team_id"],x["player_id"]))
    return dict(result,status="CURRENT_THIRD_PARTY_INJURY_ADVISORY_ONLY",
                observed_at_utc=observed,body_sha256=pin,player_rows=rows,
                unmatched=unmatched)


def render(report):
    lines=["GÜNCEL İKİNCİL OYUNCU DURUMU KAYNAĞI (MAÇA ÖZEL RESMÎ KADRO DEĞİL)",
           "Kaynak: RotoWire EuroLeague Injuries API",
           "Durum: "+report["status"]]
    if report.get("http_status") is not None:
        lines.append("HTTP: "+str(report["http_status"]))
    if report.get("observed_at_utc") is not None:
        lines.append("Kaynak yakalama UTC: "+str(report["observed_at_utc"]))
    for row in report["player_rows"][:20]:
        lines.append("• "+row["team_id"]+" / "+row["name"]+
                     " / "+row["player_id"]+" / "+row["source_reported_status"])
    lines.extend(["Yalnız resmî sezon oyuncu kimliğiyle birebir eşleşen haber adayları gösterilir.",
                  "Bildirilmeyen oyuncu sağlıklı kabul edilmez.",
                  "Maç özelinde uygunluk, ilk beş, dakika ve sayısal skor etkisi DOĞRULANMADI.",
                  "Mevcut kayıtlı tahmin değişmedi."])
    return "\n".join(lines)

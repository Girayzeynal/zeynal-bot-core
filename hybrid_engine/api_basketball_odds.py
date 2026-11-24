"""API-Basketball prematch backup: raw native labels only.

Official /odds response example does not include a price-publication timestamp.
Do not transform ingestion time into a price timestamp, or use these prices
as current The Odds API observations. No decision or forecast admission.
"""
import html
import math
import re
from urllib.parse import urlsplit,parse_qs
from core.team_identity import digest

MAX_ROWS=96
BASE='v1.basketball.api-sports.io'

def _receipt(r,path,now):
    u=urlsplit(r['source_url'])
    if (r.get('status')!='DOCUMENT_RECEIVED' or r.get('provider')!='API_BASKETBALL'
        or r.get('http_status')!=200 or u.scheme!='https' or u.netloc!=BASE or u.path!=path
        or digest(r['document'])!=r.get('document_sha256')
        or type(r.get('observed_at_utc')) is not int or type(r.get('ingested_at_utc')) is not int
        or not 0<r['observed_at_utc']<=r['ingested_at_utc']<=now
        or not 0<=now-r['observed_at_utc']<=120):
        raise ValueError('API_BASKETBALL_NATIVE_RECEIPT_SCOPE')
    return parse_qs(u.query)

def _text(v,limit):
    return isinstance(v,str) and 0<len(v.strip())<=limit and len(v)<=limit and all(ord(c)>=32 for c in v)

def inspect_receipt(fixture,price,snapshot,*,league_id,season,game_id,now):
    from hybrid_engine.provider_bridge import matches
    if type(now) is not int or now>=snapshot['fixture_start_utc']:
        raise ValueError('BACKUP_POST_TIPOFF_REFUSED')
    fquery=_receipt(fixture,'/games',now)
    if fquery.get('league')!=[str(league_id)] or fquery.get('season')!=[season]:
        raise ValueError('BACKUP_FIXTURE_REQUEST_SCOPE')
    fd=fixture['document']
    if not isinstance(fd,dict) or fd.get('errors'):raise ValueError('BACKUP_FIXTURE_ERROR')
    games=[g for g in fd['response'] if matches(g,snapshot,basketball=True)]
    if (len(games)!=1 or games[0].get('id')!=game_id or games[0]['league'].get('id')!=league_id
        or str(games[0]['league'].get('season'))!=season or games[0]['status'].get('short')!='NS'):
        raise ValueError('BACKUP_FIXTURE_IDENTITY')
    query=_receipt(price,'/odds',now)
    if query!={'game':[str(game_id)]} or fixture['observed_at_utc']>price['observed_at_utc']:
        raise ValueError('BACKUP_PRICE_REQUEST_SCOPE')
    doc=price['document']
    if not isinstance(doc,dict):raise ValueError('BACKUP_PRICE_SCHEMA')
    common=dict(provider='API_BASKETBALL',fixture_id=snapshot['fixture_id'],provider_fixture_id=game_id,
        fixture_receipt_sha256=digest(fixture),receipt_sha256=digest(price),
        captured_at_utc=price['observed_at_utc'],available_at_utc=price['ingested_at_utc'],
        publisher_price_time_verified=False,current_prices_verified=False,
        settlement_verified=False,model_input=False,rows=[])
    if doc.get('errors'):
        return dict(common,status='BACKUP_PROVIDER_REPORTED_ERROR')
    items=doc.get('response')
    if not isinstance(items,list):raise ValueError('BACKUP_PRICE_SCHEMA')
    if not items:return dict(common,status='BACKUP_NO_PRICE_ROWS')
    if len(items)!=1:raise ValueError('BACKUP_AMBIGUOUS_RESPONSE')
    event=items[0]
    if (event['game']['id']!=game_id or event['league']['id']!=league_id
        or str(event['league']['season'])!=season):
        raise ValueError('BACKUP_PRICE_IDENTITY')
    groups={};conflicts=set()
    for book in event['bookmakers'][:32]:
        if type(book.get('id')) is not int or not _text(book.get('name'),120):continue
        for bet in book.get('bets',[])[:64]:
            if type(bet.get('id')) is not int or not _text(bet.get('name'),120):continue
            for v in bet.get('values',[])[:128]:
                if not _text(v.get('value'),120):continue
                raw=v.get('odd')
                if not isinstance(raw,str) or not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?',raw):continue
                odd=float(raw)
                if not math.isfinite(odd) or not 1<odd<=1001:continue
                key=(book['id'],bet['id'],v['value'])
                row=dict(bookmaker_id=book['id'],bookmaker_name=book['name'],
                    native_bet_id=bet['id'],native_bet_name=bet['name'],native_value=v['value'],decimal_price=odd)
                if key in groups and groups[key]!=row:conflicts.add(key)
                else:groups[key]=row
    valid=[r for k,r in groups.items() if k not in conflicts]
    return dict(common,status='BACKUP_NATIVE_LABELS_OBSERVED_TIME_UNVERIFIED' if valid else 'BACKUP_NO_SUPPORTED_PRICE_ROWS',
        rows=valid[:MAX_ROWS],native_rows_before_limit=len(valid),conflicts=len(conflicts))

def render(report):
    lines=['<b>API-BASKETBALL YEDEK KAYNAK — HAM FİYAT GÖZLEMİ</b>',html.escape(report['status'])]
    for r in report.get('rows',[])[:12]:
        lines.append(html.escape(r['bookmaker_name']+' · '+r['native_bet_name']+' · '+r['native_value']+
                                 ' · '+str(r['decimal_price'])))
    lines.append('Fiyat yayın zamanı ve ödeme kapsamı doğrulanmadı; güncel piyasa veya model yönü sayılmaz.')
    return '\n'.join(lines)

"""Native NBA player-price observations, never player forecasts or settlement advice."""
import html
import math
import re
from urllib.parse import parse_qs,urlsplit
from core.team_identity import digest
from hybrid_engine.provider_identity import verify_detail

MARKETS=('player_points','player_rebounds','player_assists','player_threes',
         'player_points_rebounds_assists','player_points_rebounds','player_points_assists',
         'player_rebounds_assists')
LABELS=dict(zip(MARKETS,('Sayı','Ribaund','Asist','Üçlük','Sayı+ribaund+asist',
                         'Sayı+ribaund','Sayı+asist','Ribaund+asist')))
MAX_ROWS=96

def parse(discovery,receipt,snapshot):
    if snapshot.get('league')!='NBA':raise ValueError('PLAYER_PROP_LEAGUE_NOT_ATTESTED')
    from hybrid_engine.provider_bridge import utc
    binding=verify_detail(discovery,receipt,snapshot)
    requested=parse_qs(urlsplit(receipt['source_url']).query).get('markets',[])
    if len(requested)!=1 or not set(requested[0].split(','))<=set(MARKETS):
        raise ValueError('PLAYER_PROP_REQUEST_SCOPE')
    allowed=set(requested[0].split(','))
    groups={};conflicts=set();rejected=0;returned=set()
    books=receipt['document'].get('bookmakers',[])
    if not isinstance(books,list):raise ValueError('PLAYER_PROP_BOOKMAKER_COLLECTION_SCHEMA')
    for book in books[:12]:
        if not isinstance(book,dict) or not isinstance(book.get('key'),str) or not isinstance(book.get('title'),str):
            rejected+=1;continue
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',book['key']) or not 0<len(book['title'])<=120:
            rejected+=1;continue
        markets=book.get('markets',[])
        if not isinstance(markets,list):rejected+=1;continue
        for market in markets[:32]:
            if not isinstance(market,dict) or market.get('key') not in allowed:continue
            stat=market['key'];returned.add(stat)
            try:
                ts=utc(market.get('last_update') or book.get('last_update'))
                if not 0<=receipt['observed_at_utc']-ts<=300:raise ValueError('STALE')
                market_pin=digest(dict(bookmaker_id=book['key'],market=market))
                for o in market.get('outcomes',[])[:512]:
                    try:
                        player=o['description'];point=o['point'];price=o['price']
                        if (not isinstance(player,str) or not player.strip() or len(player)>120
                            or any(ord(c)<32 for c in player)
                            or type(point) not in (int,float) or not math.isfinite(point) or not 0<=point<=300
                            or type(price) not in (int,float) or not math.isfinite(price) or not 1<price<=1001):
                            raise ValueError('INVALID_PLAYER_PRICE')
                        side={'Under':'under','Over':'over'}[o['name']]
                        key=(book['key'],stat,player,float(point))
                        row=groups.setdefault(key,dict(bookmaker_id=book['key'],bookmaker_name=book['title'],
                            market=stat,provider_player_label=player,line=float(point),prices={},
                            published_at_utc=ts,player_identity_verified=False,
                            native_market_sha256=market_pin))
                        if side in row['prices'] or row['published_at_utc']!=ts or row['native_market_sha256']!=market_pin:
                            conflicts.add(key);continue
                        row['prices'][side]=float(price)
                    except (KeyError,ValueError,TypeError):rejected+=1
            except (KeyError,ValueError,TypeError):rejected+=1
    complete=[r for k,r in groups.items() if k not in conflicts and set(r['prices'])=={'under','over'}]
    # Keep diversity of stats before repeating a market; bounded report.
    rows=[]
    for stat in MARKETS:
        row=next((r for r in complete if r['market']==stat),None)
        if row is not None:rows.append(row)
    rows=(rows+[r for r in complete if r not in rows])[:MAX_ROWS]
    payload=dict(status='PLAYER_PRICE_LABELS_OBSERVED_IDENTITY_UNVERIFIED' if rows else 'NO_FRESH_PAIRED_PLAYER_PRICES',
        fixture_id=snapshot['fixture_id'],league='NBA',event_clock_binding=binding,
        receipt_sha256=digest(receipt),document_sha256=receipt['document_sha256'],
        captured_at_utc=receipt['observed_at_utc'],available_at_utc=receipt['ingested_at_utc'],
        requested_markets=sorted(allowed),returned_markets=sorted(returned),
        paired_rows_before_limit=len(complete),rows=rows,rejected_outcomes=rejected,
        conflicting_rows=len(conflicts),model_input=False,player_identity_verified=False,
        availability_verified=False,settlement_verified=False,confidence_index=None)
    return payload

def render(report):
    lines=['<b>OYUNCU PİYASA GÖZLEMLERİ — KİMLİK / ÖDEME DOĞRULAMASI BEKLİYOR</b>',
           html.escape(report['status']), 'Fiyat çifti: '+str(len(report.get('rows',[])))]
    for row in report.get('rows',[])[:12]:
        lines.append(html.escape(row['provider_player_label']+' · '+LABELS[row['market']]+' · '+str(row['line'])+
            ' · '+row['bookmaker_name']+' · ALT '+str(row['prices']['under'])+' / ÜST '+str(row['prices']['over'])))
    if len(report.get('rows',[]))>12:lines.append('Diğer ham fiyatlar kaynak kaydında; özet 12 satır.')
    lines.append('Sağlayıcı oyuncu etiketi resmî kimlik veya katılım kanıtı değildir. Olasılık, yön, edge ve skor etkisi hesaplanmadı.')
    return '\n'.join(lines)

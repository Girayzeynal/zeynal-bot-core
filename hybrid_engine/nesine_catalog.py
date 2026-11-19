"""Anonymous official Nesine fixture audit, never invent prices or book rules.

The observed native catalog currently carries empty market arrays. Catalog
access is not price coverage. No account endpoint, credential or bet submission.
"""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import threading
import time
from zoneinfo import ZoneInfo

import requests
from core.team_identity import digest
from hybrid_engine.data import local_path
from hybrid_engine.boxes import publish_json
from hybrid_engine.provider_bridge import name,team_side

URL='https://cdnbulten.nesine.com/v2/Bulten/GetPreBulten?sportId=2&nsnIds=-1'
LEAGUES={'NBA':'NBA','EuroLeague':'EUROLEAGUE','EuroCup':'EUROCUP'}
NBA_NAMES=dict(zip(('Atlanta','Boston','Brooklyn','Charlotte','Chicago','Cleveland','Dallas','Denver','Detroit',
    'Golden State','Houston','Indiana','LA Clippers','LA Lakers','Memphis','Miami','Milwaukee','Minnesota',
    'New Orleans','New York','Oklahoma City','Orlando','Philadelphia','Phoenix','Portland','Sacramento',
    'San Antonio','Toronto','Utah','Washington'),('Atlanta Hawks','Boston Celtics','Brooklyn Nets','Charlotte Hornets',
    'Chicago Bulls','Cleveland Cavaliers','Dallas Mavericks','Denver Nuggets','Detroit Pistons','Golden State Warriors',
    'Houston Rockets','Indiana Pacers','LA Clippers','Los Angeles Lakers','Memphis Grizzlies','Miami Heat','Milwaukee Bucks',
    'Minnesota Timberwolves','New Orleans Pelicans','New York Knicks','Oklahoma City Thunder','Orlando Magic',
    'Philadelphia 76ers','Phoenix Suns','Portland Trail Blazers','Sacramento Kings','San Antonio Spurs','Toronto Raptors',
    'Utah Jazz','Washington Wizards')))


def fetch():
    observed=int(time.time())
    try:
        with requests.get(URL,timeout=5,stream=True) as response:
            if response.status_code!=200:return dict(status='SOURCE_HTTP_ERROR',http_status=response.status_code,source_url=URL)
            raw=bytearray()
            for chunk in response.iter_content(65536):
                raw.extend(chunk)
                if len(raw)>1024*1024:raise ValueError('NESINE_CATALOG_SIZE_LIMIT')
                if int(time.time())-observed>5:raise TimeoutError('NESINE_CATALOG_TIME_LIMIT')
        document=json.loads(raw)
        return dict(status='DOCUMENT_RECEIVED',provider='NESINE',http_status=200,source_url=URL,
            document=document,document_sha256=digest(document),body_sha256=hashlib.sha256(raw).hexdigest(),
            observed_at_utc=observed,ingested_at_utc=int(time.time()))
    except (requests.RequestException,ValueError,TimeoutError):return dict(status='SOURCE_UNAVAILABLE',source_url=URL)


def inspect(receipt,snapshot,*,now):
    if (receipt.get('status')!='DOCUMENT_RECEIVED' or receipt.get('http_status')!=200 or receipt.get('source_url')!=URL or
            receipt.get('provider')!='NESINE' or digest(receipt['document'])!=receipt['document_sha256'] or
            any(type(receipt.get(k)) is not int for k in ('observed_at_utc','ingested_at_utc')) or
            not 0<receipt['observed_at_utc']<=receipt['ingested_at_utc']<=now or now-receipt['observed_at_utc']>300):
        raise ValueError('NESINE_NATIVE_CATALOG_PIN_OR_CLOCK')
    d=receipt['document']
    if d.get('sc')!=200:raise ValueError('NESINE_CATALOG_PROVIDER_ERROR')
    sg=d['d']['sg'];events=sg['EAW'];leagues={r['LID']:LEAGUES.get(r['N']) for r in sg['LA']}
    if not isinstance(events,list) or len(events)>1000:raise ValueError('NESINE_EVENT_BUDGET')
    matches=[];same_clock=[]
    for row in events:
        event=row['E']
        if leagues.get(event['LC'])!=snapshot['league']:continue
        at=event['ESD']
        if type(at) is not int or at%1000 or event['ED']!=at:continue
        stamp=at//1000;local=datetime.fromtimestamp(stamp,ZoneInfo('Europe/Istanbul'))
        if local.strftime('%d.%m.%Y')!=event['D'] or local.strftime('%H:%M')!=event['T']:
            raise ValueError('NESINE_NATIVE_CLOCK_CONFLICT')
        if stamp!=snapshot['fixture_start_utc']:continue
        item=dict(provider_fixture_id=str(event['C']),home=event['HN'],away=event['AN'],start_utc=stamp,
            native_market_count=len(row['MA']))
        same_clock.append(item)
        h,a=event['HN'],event['AN']
        if snapshot['league']=='NBA':h=NBA_NAMES.get(h,h);a=NBA_NAMES.get(a,a)
        if team_side(h,snapshot)=='home' and team_side(a,snapshot)=='away':matches.append(item)
    return dict(status='FIXTURE_MATCHED_PRICES_NOT_ADMITTED' if len(matches)==1 else 'EXACT_FIXTURE_MATCH_REQUIRED',
        platform='Nesine',source_url=URL,document_sha256=receipt['document_sha256'],
        observed_at_utc=receipt['observed_at_utc'],matched=matches[0] if len(matches)==1 else None,
        same_clock_candidates=same_clock[:4],prices_admitted=False,rules_verified=False,
        fixture_season_authority='ORIGINAL_OFFICIAL_FIXTURE_NOT_NESINE_SEASON_CATALOG',
        note='Katalog erişimi oran/ödeme kuralı doğrulaması değildir; başka platform Nesine olarak etiketlenmez.')


class NesineCatalog:
    def __init__(self,directory,getter=fetch):
        self.root=local_path(directory);self.getter=getter;self.cached=None;self.lock=threading.Lock()

    def review(self,snapshot):
        now=int(time.time())
        if now>=snapshot['fixture_start_utc']:return dict(platform='Nesine',status='POST_TIPOFF_NO_QUERY',prices_admitted=False)
        if not self.lock.acquire(blocking=False):return dict(platform='Nesine',status='CATALOG_REVIEW_BUSY',prices_admitted=False)
        try:
            if self.cached is None or now-self.cached.get('observed_at_utc',0)>240:
                self.cached=self.getter()
                if 'observed_at_utc' not in self.cached:self.cached=dict(self.cached,observed_at_utc=now)
            receipt=self.cached
            if receipt.get('status')!='DOCUMENT_RECEIVED':return dict(platform='Nesine',status=receipt.get('status','SOURCE_UNAVAILABLE'),http_status=receipt.get('http_status'),prices_admitted=False)
            result=inspect(receipt,snapshot,now=int(time.time()))
            files=list(self.root.glob('source-*.json')) if self.root.is_dir() else []
            if len(files)>=256 or sum(p.stat().st_size for p in files)>32*1024*1024:
                result['persistence']='LOCAL_BUDGET_REACHED_NO_DELETION';return result
            from hybrid_engine.current_assessment import native_asset
            self.root.mkdir(parents=True,exist_ok=True);asset=native_asset(receipt)
            publish_json(self.root/('source-'+digest(asset)+'.json'),asset)
            result['source_asset_sha256']=digest(asset);return result
        finally:self.lock.release()

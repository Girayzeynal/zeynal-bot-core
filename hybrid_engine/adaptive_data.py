"""Native receipt references + separately collected past boxes; no clock rewrites."""
from copy import deepcopy
from collections import Counter
import json
import re
import time

from core.team_identity import digest
from historical_research import historical_rows
from hybrid_engine.availability import effective_box_time
from hybrid_engine.boxes import collect_boxes,normalize_box,publish_json,url_for
from hybrid_engine.data import STRICT,available_at,local_path,regulation
from hybrid_engine.europe_models import catalog
from season_archive_inventory import archive_catalog

LEAGUES={'NBA':'NBA','EUROLEAGUE':'EuroLeague','EUROCUP':'EuroCup'}


def native_catalog(receipt,league,year):
    if league!='NBA':return catalog(receipt,league,year,max_age=None)
    if (receipt.get('provider')!='ESPN' or receipt.get('status')!='DOCUMENT_RECEIVED' or receipt.get('http_status')!=200 or
            digest(receipt['document'])!=receipt.get('document_sha256') or
            any(type(receipt.get(k)) is not int for k in ('observed_at_utc','ingested_at_utc')) or
            not 0<receipt['observed_at_utc']<=receipt['ingested_at_utc']<=int(time.time())):
        raise ValueError('ADAPTIVE_NATIVE_SOURCE_CLOCK_OR_PIN')
    url=receipt['source_url'];prefix='https://site.api.espn.com/apis/site/v2/sports/basketball/nba/'
    if url.startswith(prefix+'scoreboard?'):document=receipt['document']
    elif url.startswith(prefix+'summary?event='):
        header=deepcopy(receipt['document']['header']);game=header['competitions'][0]
        if url!=prefix+'summary?event='+header['id']:raise ValueError('ADAPTIVE_SUMMARY_NATIVE_ID')
        header['date']=game['date']
        for team in game['competitors']:
            for part in team.get('linescores',[]):
                if 'value' not in part:
                    text=part.get('displayValue')
                    if not isinstance(text,str) or not text.isascii() or not text.isdigit():raise ValueError('ADAPTIVE_NATIVE_PERIOD')
                    part['value']=int(text)
        document={'events':[header]}
    else:raise ValueError('ADAPTIVE_NATIVE_CATALOG_URL_REQUIRED')
    return archive_catalog(document,provider='ESPN',season_start_year=year,
        observed_at_utc=receipt['observed_at_utc'],ingested_at_utc=receipt['ingested_at_utc'],regular_season_filter=True)


class FeatureStore:
    def __init__(self,directory,allowed_roots,fetcher):
        self.root=local_path(directory);self.native=self.root/'native'
        self.roots=tuple(local_path(p) for p in allowed_roots)+(self.native,);self.fetcher=fetcher
        self.root.mkdir(parents=True,exist_ok=True);self.native.mkdir(exist_ok=True)
        self.boxes=self.root/'boxes';self.boxes.mkdir(exist_ok=True);self.retry={}

    def observe(self,receipt,league,year):
        c=native_catalog(receipt,league,year)
        files=list(self.native.glob('source-*.json'))
        if len(files)>=1024 or sum(p.stat().st_size for p in files)>256*1024*1024:raise ValueError('ADAPTIVE_NATIVE_STORE_BUDGET')
        # Repeated retrieval of identical final content does not duplicate large
        # documents or rewrite its first real local observation time.
        key=digest(dict(league=league,year=year,fixtures=digest(c['payload']['fixtures'])))
        path=self.native/('source-'+key+'.json')
        if not path.exists():publish_json(path,receipt)
        value=json.loads(path.read_text());self.ingest(path,digest(value),league,year)

    def read_source(self,reference):
        path=local_path(reference['path'])
        if not any(path.is_relative_to(root) for root in self.roots) or path.stat().st_size>16*1024*1024:
            raise ValueError('ADAPTIVE_SOURCE_PATH_OR_BUDGET')
        receipt=json.loads(path.read_text())
        if digest(receipt)!=reference['sha256']:raise ValueError('ADAPTIVE_SOURCE_REFERENCE_PIN')
        return receipt

    def ingest(self,path,pin,league,year):
        if league not in LEAGUES:raise ValueError('ADAPTIVE_LEAGUE_REQUIRED')
        ref=dict(path=str(local_path(path)),sha256=pin,league=league,year=year)
        receipt=self.read_source(ref);c=native_catalog(receipt,league,year)
        ref['fixtures_sha256']=digest(c['payload']['fixtures'])
        key=digest(dict(league=league,year=year,fixtures=ref['fixtures_sha256']))
        path=self.root/('feed-'+key+'.json')
        if path.exists():
            w=json.loads(path.read_text())
            if digest(w['payload'])!=w['sha256']:raise ValueError('ADAPTIVE_FEED_PIN')
            self.read_source(w['payload']);return
        files=list(self.root.glob('feed-*.json'))
        if len(files)>=2048:raise ValueError('ADAPTIVE_FEED_BUDGET')
        publish_json(path,dict(payload=ref,sha256=digest(ref)))

    def references(self,league,year):
        files=list(self.root.glob('feed-*.json'))
        if len(files)>2048:raise ValueError('ADAPTIVE_FEED_BUDGET')
        result=[]
        for f in files:
            if f.stat().st_size>4096:raise ValueError('ADAPTIVE_FEED_SIZE')
            w=json.loads(f.read_text());p=w['payload']
            key=digest(dict(league=p['league'],year=p['year'],fixtures=p['fixtures_sha256']))
            if digest(p)!=w['sha256'] or f.stem!='feed-'+key:raise ValueError('ADAPTIVE_FEED_PIN')
            if (p['league'],p['year'])==(league,year):result.append(p)
        return result

    def cohort(self,league,year,cutoff):
        # Replay one catalog at a time; retaining every full-season observation
        # would grow memory with the number of collection timestamps.
        latest={};identities={}
        for ref in self.references(league,year):
            receipt=self.read_source(ref)
            if receipt['ingested_at_utc']>cutoff:continue
            c=native_catalog(receipt,league,year)
            if digest(c['payload']['fixtures'])!=ref['fixtures_sha256']:raise ValueError('ADAPTIVE_FEED_NATIVE_CONTENT_PIN')
            for versions in historical_rows([(c,c['sha256'])]):
                eligible=[r for r in versions if r['fixture_start_utc']<available_at(r,STRICT)<=cutoff and regulation(r) is not None]
                if not eligible:continue
                r=max(eligible,key=lambda r:(available_at(r,STRICT),r['source_catalog_sha256']))
                identity=(r['fixture_start_utc'],r['home_team_id'],r['away_team_id'])
                for pid in r['provider_fixture_ids']:
                    if pid in identities and identities[pid]!=identity:raise ValueError('ADAPTIVE_NATIVE_HISTORY_IDENTITY_CHANGED')
                    identities[pid]=identity
                old=latest.get(r['fixture_id'])
                if old is None or (available_at(r,STRICT),r['source_catalog_sha256'])>(available_at(old,STRICT),old['source_catalog_sha256']):latest[r['fixture_id']]=r
                if len(latest)>5000:raise ValueError('ADAPTIVE_HISTORY_BUDGET')
        rows=[]
        for value in latest.values():
            row=deepcopy(value)
            cache=self.boxes/'box-receipts'/(digest(dict(provider=row['provider'],url=url_for(row)))+'.json')
            if cache.exists():
                if cache.stat().st_size>16*1024*1024:raise ValueError('ADAPTIVE_NATIVE_BOX_SIZE')
                receipt=json.loads(cache.read_text())
                if receipt['ingested_at_utc']<=cutoff:
                    box=normalize_box(row,receipt)
                    if effective_box_time(box)<=cutoff:row['box']=box;row['box_versions']=[box]
            rows.append([row])
        return rows

    def acquire_boxes(self,cohort,*,maximum=4):
        if type(maximum) is not int or not 1<=maximum<=8:raise ValueError('ADAPTIVE_BOX_BATCH_BUDGET')
        # Never request target/live/OT boxes as regulation tempo training facts.
        now=int(time.time());self.retry={k:v for k,v in self.retry.items() if v>now}
        rows=[v[0] for v in cohort if not v[0].get('box') and self.retry.get(v[0]['fixture_id'],0)<=now and v[0]['periods'] and
              all(len(v[0]['periods'][s])==4 for s in ('home','away'))]
        rows.sort(key=lambda r:(-r['fixture_start_utc'],r['fixture_id']))
        stored=list(self.boxes.rglob('*.json'))
        if len(stored)>4096 or sum(p.stat().st_size for p in stored)>256*1024*1024:
            raise ValueError('ADAPTIVE_BOX_ARCHIVE_BUDGET')
        if not rows:return dict(requested=0,verified=0,blocked=0,remaining=0)
        _,report=collect_boxes([[r] for r in rows[:maximum]],self.boxes,fetcher=self.fetcher,workers=1,interval=.1)
        for failure in report['failures']:self.retry[failure['fixture_id']]=int(time.time())+900
        while len(self.retry)>2048:self.retry.pop(next(iter(self.retry)))
        reasons=Counter(f['reason'] if re.fullmatch('[A-Z][A-Z0-9_]{1,99}',str(f.get('reason',''))) else
                        'NATIVE_BOX_VALIDATION_FAILED' for f in report['failures'])
        return dict(requested=min(len(rows),maximum),verified=len(report['games']),blocked=len(report['failures']),
                    remaining=max(0,len(rows)-maximum),failure_classes=dict(reasons))

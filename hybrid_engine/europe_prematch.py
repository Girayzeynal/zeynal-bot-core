"""Isolated European early capture around the unchanged, pinned inference engine.

No request-time fitting, Telegram broadcasts, NBA access or archive replacement.
"""
import argparse
import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
import fcntl
import json
import logging
import os
import tempfile
import time
from zoneinfo import ZoneInfo

from core.team_identity import digest
from core.league_identity import normalize_name
from hybrid_engine.boxes import publish_json
from hybrid_engine.data import Abstain,local_path
from hybrid_engine.europe_live import EuropeanService,EuropeanRegistry
from hybrid_engine.europe_five_minute import analyze as five_minute_analyze
from hybrid_engine.europe_models import catalog,season_url
from hybrid_engine.live_euroleague import names
from hybrid_engine.time_policy import PREMATCH_MINIMUM_LEAD_SECONDS

VERSION='EUROPE_AUTO_PREMATCH_V2'
MINIMUM_LEAD=PREMATCH_MINIMUM_LEAD_SECONDS
LOOKAHEAD=36*3600
LOG=logging.getLogger(__name__)
_AUTO_INFERENCE=ContextVar('europe_auto_inference',default=False)
MANUAL_LOCK_WAIT_SECONDS=12
AUTO_LOCK_WAIT_SECONDS=0.2


def open_lock(root,name):
    path=local_path(root/name)
    return os.open(path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)


@contextmanager
def publication_lock(root):
    fd=open_lock(root,'.prematch-publication.lock')
    try:
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc:raise Abstain('EUROPE_PREMATCH_PUBLICATION_BUSY') from exc
        yield
    finally:os.close(fd)


def safe_lead(payload):
    tip=payload['fixture']['start_ts_utc'];now=int(time.time())
    if (type(tip) is not int or type(payload['prediction_generated_at_utc']) is not int or
            not 0<payload['prediction_generated_at_utc']<=now<tip-MINIMUM_LEAD):
        raise Abstain('EUROPE_SAFE_PRETIPOFF_WINDOW_CLOSED')


def assert_unstarted(receipt,fixture):
    rows=[r for r in receipt['document']['data'] if r['identifier'] in fixture['provider_fixture_ids']]
    if len(rows)!=1:raise Abstain('EUROPE_SCHEDULED_STATUS_REQUIRED')
    row=rows[0]
    if (row.get('played') is not False or row.get('gameStatus')!='Confirmed' or
            row.get('confirmedDate') is not True or row.get('confirmedHour') is not True):
        raise Abstain('EUROPE_SCHEDULED_STATUS_REQUIRED')
    for side in ('local','road'):
        team=row[side];parts=team.get('partials')
        if type(team.get('score')) is not int or team['score']!=0:
            raise Abstain('EUROPE_NONZERO_LIVE_SCORE_REFUSED')
        if parts is not None and (not isinstance(parts,dict) or
                any(parts.get('partials'+str(i))!=0 for i in range(1,5)) or parts.get('extraPeriods')!={}):
            raise Abstain('EUROPE_NONZERO_LIVE_SCORE_REFUSED')


def publish_first_slot(path,value):
    """Return actual exclusive link creation; identical bytes are a replay."""
    path=local_path(path)
    body=(json.dumps(value,sort_keys=True,allow_nan=False)+'\n').encode()
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.europe-first-',delete=False) as f:
            temporary=f.name
            f.write(body);f.flush();os.fsync(f.fileno())
        try:os.link(temporary,path)
        except FileExistsError:return False
        fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
        return True
    finally:
        if temporary is not None:os.unlink(temporary)


class SinglePrematchRegistry(EuropeanRegistry):
    """One publication per fixture across versions and independent processes."""
    def __init__(self,*args,prior_registries=(),legacy_archive=None,**kwargs):
        super().__init__(*args,**kwargs);self.prior_registries=prior_registries;self.legacy_archive=legacy_archive

    def asset(self,prefix,payload):
        if prefix=='forecast':safe_lead(payload)
        ref=super().asset(prefix,payload)
        # Catch a boundary crossed while writing/fsyncing the unpublished asset.
        if prefix=='forecast':safe_lead(payload)
        return ref

    def record(self,payload):
        with publication_lock(self.root):
            saved=next((r for r in self.independent_records() if
                        r['payload']['fixture']['canonical_id']==payload['fixture']['canonical_id'] or
                        set(r['payload']['fixture']['provider_fixture_ids'])&set(payload['fixture']['provider_fixture_ids'])),None)
            if saved:return saved['payload'],False
            prior=[r['payload'] for registry in self.prior_registries for r in registry.independent_records()]
            if self.legacy_archive is not None:prior.extend(self.legacy_archive.records.values())
            if any(set(p['fixture']['provider_fixture_ids'])&set(payload['fixture']['provider_fixture_ids']) for p in prior):
                raise Abstain('EUROPE_PRIOR_ARCHIVE_REPLAY_REQUIRED')
            safe_lead(payload)
            for ref in payload['assets']:
                if ref['file'].startswith('source-'):
                    receipt=self.read_asset(ref)
                    bundle=catalog(receipt,self.league,payload['fixture']['season_start_year'])
                    if payload['fixture'] not in bundle['payload']['fixtures']:
                        raise Abstain('EUROPE_SOURCE_FIXTURE_CHANGED')
                    assert_unstarted(receipt,payload['fixture'])
            # Preserve the sealed shared ForwardRegistry implementation.
            # Only this European publisher needs an exclusive creation receipt.
            key=digest(dict(fixture=payload['fixture']['canonical_id'],version=payload['version']))
            slot=self.root/('first-'+key+'.json')
            p=dict(payload);now=int(time.time());tip=p['fixture']['start_ts_utc']
            if not 0<p['source_available_max_utc']<=p['prediction_generated_at_utc']<=now<tip:
                raise ValueError('FORWARD_PRETIPOFF_CLOCK')
            if p['actual'] is not None:raise ValueError('FORWARD_TARGET_LABEL_FORBIDDEN')
            p['snapshot_created_at_utc']=now
            for ref in p['assets']:self.read_asset(ref)
            ref=self.asset('forecast',p);published=int(time.time())
            safe_lead(p)
            publication=dict(forecast=ref,first_archived_at_utc=published,
                eligible_for_prospective_audit=published<tip,
                classification='PREMATCH' if published<tip else 'LATE_COMMIT_EXCLUDED')
            if not publish_first_slot(slot,dict(payload=publication,sha256=digest(publication))):
                old=self.publication(slot);return self.read_asset(old['forecast']),False
            return p,True


class AutomaticEuropeanService(EuropeanService):
    """Preserve europe_live.py/model pins; serialize its existing inference flow."""
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.manual_waiters=0
        self.registry=SinglePrematchRegistry(self.registry.root,self.league,
            prior_registries=(self.previous.registry,) if self.previous is not None else (),legacy_archive=self.archive)

    def existing(self,day,home,away):
        """Resolve replay aliases from the original pinned fixture, even offline.

        This is archived-pair lookup, not a new season membership catalog.
        Shared aliases or multiple archived matches never select the first row.
        """
        from providers.season_participants import _variants
        found=[];h=normalize_name(home);a=normalize_name(away)
        for item in self.registry.independent_records():
            p=item['payload'];g=p['fixture']
            if datetime.fromtimestamp(g['start_ts_utc'],ZoneInfo('Europe/Istanbul')).date().isoformat()!=day:continue
            self.pair(p)  # validates the original fixture/source hash and identity
            receipt=self.registry.read_asset(p['fixture_source'])
            rows=[v for v in receipt['document']['data'] if v['identifier'] in g['provider_fixture_ids']]
            if len(rows)!=1:continue
            keys=[]
            for side in ('local','road'):
                club=rows[0][side]['club']
                keys.append({normalize_name(v['name']) for v in _variants(club,p['source_available_max_utc'],include_city=True)})
            if h in keys[0]-keys[1] and a in keys[1]-keys[0]:found.append(item)
        if len(found)>1:raise ValueError('EUROPE_AMBIGUOUS_ARCHIVED_PAIR')
        return found[0] if found else None

    async def analyze(self,league,day,home,away):
        automatic=_AUTO_INFERENCE.get()
        if automatic and self.manual_waiters:
            return dict(status='ABSTAIN',reason='EUROPE_MANUAL_PRIORITY',
                        html='Otomatik hazırlama manuel analiz için ertelendi.')
        if not automatic:self.manual_waiters+=1
        try:
            return await self._locked_analyze(league,day,home,away,automatic=automatic)
        finally:
            if not automatic:self.manual_waiters-=1

    async def _locked_analyze(self,league,day,home,away,*,automatic):
        try:fd=open_lock(self.registry.root,'.prematch-inference.lock')
        except (ValueError,OSError):
            return dict(status='ABSTAIN',reason='EUROPE_PREMATCH_LOCK_UNAVAILABLE',
                        html='Maç öncesi arşiv kilidi açılamadı. Yeni tahmin oluşturulmadı; eski kayıtlar korundu.')
        try:
            until=time.monotonic()+(AUTO_LOCK_WAIT_SECONDS if automatic else MANUAL_LOCK_WAIT_SECONDS)
            replay_checked=False
            while True:
                if automatic and self.manual_waiters:
                    return dict(status='ABSTAIN',reason='EUROPE_MANUAL_PRIORITY',
                                html='Otomatik hazırlama manuel analiz için ertelendi.')
                try:
                    fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    # Read the existing archive once, not every 50 ms. Never
                    # queue repeated complete archive scans on the command lane.
                    if not automatic and not replay_checked:
                        replay_checked=True
                        old=await asyncio.to_thread(self.existing,day,home,away)
                        if old:return self.render(old)
                    if time.monotonic()>=until:
                        return dict(status='ABSTAIN',reason='EUROPE_PREMATCH_INFERENCE_BUSY',
                            html='EUROPE_PREMATCH_INFERENCE_BUSY — lig işlem kilidi dolu. '
                                 'Bu komutta yeni tahmin yok; eski kayıtlar korundu.')
                    await asyncio.sleep(.1)
            return await five_minute_analyze(self,league,day,home,away)
        finally:os.close(fd)


def candidates(service,now):
    """Current confirmed fixtures only; inference rechecks source/status itself."""
    local=datetime.fromtimestamp(now,ZoneInfo('Europe/Istanbul'));year=local.year-(local.month<7)
    receipt=service.fetcher('EUROLEAGUE_LIVE',season_url(service.league,year))
    bundle=catalog(receipt,service.league,year);pairs=names(receipt['document'])
    archived=[r['payload'] for r in service.registry.independent_records()]
    previous=getattr(service,'previous',None)
    if previous is not None:archived.extend(r['payload'] for r in previous.registry.independent_records())
    archive=getattr(service,'archive',None)
    if archive is not None:archived.extend(archive.records.values())
    saved={p['fixture']['canonical_id'] for p in archived}
    saved_ids={pid for p in archived for pid in p['fixture']['provider_fixture_ids']}
    selected=[];next_starts=[];skipped={}
    for g in sorted(bundle['payload']['fixtures'],key=lambda x:(x['start_ts_utc'],x['canonical_id'])):
        lead=g['start_ts_utc']-now
        reason=('ALREADY_ARCHIVED' if g['canonical_id'] in saved or set(g['provider_fixture_ids'])&saved_ids else 'COMPLETED' if g['completed'] else
                'STARTED' if lead<=0 else 'LAST_5_MINUTES' if lead<=MINIMUM_LEAD else
                'OUTSIDE_EARLY_WINDOW' if lead>LOOKAHEAD else None)
        if reason:
            skipped[reason]=skipped.get(reason,0)+1
            if reason=='OUTSIDE_EARLY_WINDOW':next_starts.append(g['start_ts_utc'])
            continue
        assert_unstarted(receipt,g)
        h,a=pairs[g['provider_fixture_ids'][0]]
        selected.append(dict(fixture_id=g['canonical_id'],provider_fixture_ids=g['provider_fixture_ids'],
            fixture_start_utc=g['start_ts_utc'],day=datetime.fromtimestamp(g['start_ts_utc'],ZoneInfo('Europe/Istanbul')).date().isoformat(),
            home=h,away=a,window='NEXT_36_HOURS'))
    return dict(selected=selected,skipped=skipped,source_sha256=digest(receipt),
        next_scan_utc=now+300 if selected else min(now+1800,min(next_starts)-LOOKAHEAD) if next_starts else now+1800)


class EuropeanPrematchScheduler:
    def __init__(self,services,directory,*,clock=time.time,maximum=4):
        if type(maximum) is not int or not 1<=maximum<=8:raise ValueError('EUROPE_AUTO_BOUNDED_MAXIMUM_REQUIRED')
        if not set(services)<=set(('EUROLEAGUE','EUROCUP')):raise ValueError('EUROPE_AUTO_LEAGUES_ONLY')
        self.services=services;self.root=local_path(directory);self.clock=clock;self.maximum=maximum
        self.next_scan={};self.retry_after={};self.running=False;self.last_report=None;self.sequence=0

    def publish(self,p):
        self.root.mkdir(parents=True,exist_ok=True);files=list(self.root.glob('auto-*.json'))
        body=json.dumps(p,allow_nan=False)
        if len(body.encode())>128*1024 or len(files)>=4096 or sum(f.stat().st_size for f in files)>64*1024*1024:
            raise ValueError('EUROPE_AUTO_JOURNAL_BUDGET')
        publish_json(self.root/('auto-'+digest(p)+'.json'),dict(payload=p,sha256=digest(p)))

    async def tick(self,*,force=False):
        if self.running:return dict(status='ABSTAIN',reason='EUROPE_AUTO_TICK_ALREADY_RUNNING')
        self.running=True;self.sequence+=1;now=int(self.clock());remaining=self.maximum
        self.retry_after={k:v for k,v in self.retry_after.items() if v>now}
        report=dict(format=VERSION,evaluated_at_utc=now,sequence=self.sequence,leagues={},
            minimum_lead_seconds=MINIMUM_LEAD,lookahead_seconds=LOOKAHEAD,
            maximum=self.maximum,forecast_training=False,production_changed=False,actual_telegram_delivery_verified=False)
        try:
            order=list(self.services)
            if order:order=order[(self.sequence-1)%len(order):]+order[:(self.sequence-1)%len(order)]
            for code in order:
                service=self.services[code]
                if not force and now<self.next_scan.get(code,0):continue
                try:
                    scan=await asyncio.to_thread(candidates,service,int(self.clock()))
                    self.next_scan[code]=max(int(self.clock())+60,scan['next_scan_utc'])
                    ready=[t for t in scan['selected'] if int(self.clock())>=self.retry_after.get((code,t['fixture_id']),0)]
                    rows=[];report['leagues'][code]=dict(source_sha256=scan['source_sha256'],skipped=scan['skipped'],
                        eligible=len(scan['selected']),retry_deferred=len(scan['selected'])-len(ready),results=rows)
                    for target in ready[:remaining]:
                        remaining-=1
                        if int(self.clock())>=target['fixture_start_utc']-MINIMUM_LEAD:
                            rows.append(dict(**target,status='ABSTAIN',reason='EUROPE_SAFE_PRETIPOFF_WINDOW_CLOSED',new_record=False));continue
                        if getattr(service,'manual_waiters',0)>0:
                            self.next_scan[code]=int(self.clock())+60
                            break
                        token=_AUTO_INFERENCE.set(True)
                        try:result=await asyncio.wait_for(service.analyze(code,target['day'],target['home'],target['away']),timeout=45)
                        except (ValueError,KeyError,TypeError,OSError,TimeoutError,asyncio.TimeoutError):
                            self.retry_after[(code,target['fixture_id'])]=int(self.clock())+300
                            rows.append(dict(**target,status='ABSTAIN',reason='EUROPE_AUTO_INFERENCE_OR_TIMEOUT',new_record=False,forecast_sha256=None));continue
                        finally:_AUTO_INFERENCE.reset(token)
                        reason=result.get('reason') or result.get('preflight',{}).get('reason')
                        if result['status']=='ABSTAIN' and reason is None:
                            # Existing service formats safe failure codes in its first line.
                            lines=result.get('html','').splitlines();line=lines[0] if lines else ''
                            code_text=line.removeprefix('Analiz durduruldu: ')
                            reason=code_text if code_text.startswith('EUROPE_') and code_text.replace('_','').isalnum() else 'VERIFIED_MODEL_HISTORY_OR_ARCHIVE_REQUIRED'
                        rows.append(dict(**target,status=result['status'],reason=reason,new_record=result.get('new_record',False),
                                         forecast_sha256=result.get('forecast_sha256')))
                        if result['status']=='ABSTAIN':self.retry_after[(code,target['fixture_id'])]=int(self.clock())+300
                    if len(ready)>len(rows):self.next_scan[code]=int(self.clock())+60
                    if not ready and scan['selected']:
                        self.next_scan[code]=min(self.next_scan[code],min(self.retry_after[(code,t['fixture_id'])] for t in scan['selected']))
                    while len(self.retry_after)>512:self.retry_after.pop(next(iter(self.retry_after)))
                except (ValueError,KeyError,TypeError,OSError,TimeoutError):
                    report['leagues'][code]=dict(status='ABSTAIN',reason='OFFICIAL_FIXTURE_MODEL_OR_ARCHIVE_UNAVAILABLE')
                    self.next_scan[code]=int(self.clock())+300
                    LOG.warning('European automatic prematch blocked: league=%s reason=OFFICIAL_FIXTURE_MODEL_OR_ARCHIVE_UNAVAILABLE',code)
            report['completed_at_utc']=int(self.clock())
            report['status']='PARTIAL_ABSTAIN' if any(v.get('status')=='ABSTAIN' or
                any(r['status']=='ABSTAIN' for r in v.get('results',[])) for v in report['leagues'].values()) else 'CHECKED'
            if any(v.get('results') or v.get('status')=='ABSTAIN' for v in report['leagues'].values()):
                try:await asyncio.to_thread(self.publish,report)
                except (ValueError,OSError):
                    report['journal_status']='ABSTAIN_JOURNAL_UNAVAILABLE'
                    report['status']='PARTIAL_ABSTAIN'
                    LOG.error('European automatic prematch journal unavailable; original prediction archives retained')
                for code,v in report['leagues'].items():
                    for r in v.get('results',[]):LOG.info('European automatic prematch: league=%s fixture=%s status=%s new=%s reason=%s',
                        code,r['fixture_id'],r['status'],r.get('new_record',False),r['reason'])
            self.last_report=report;return report
        finally:self.running=False

    async def run(self,app,*,interval=60):
        if type(interval) is not int or not 60<=interval<=300:raise ValueError('EUROPE_AUTO_POLL_INTERVAL_REQUIRED')
        while True:
            try:app.bot_data['last_europe_prematch_poll']=await self.tick()
            except asyncio.CancelledError:raise
            except Exception as exc:
                # Never include native exception text/URLs or credentials.
                LOG.error('European automatic prematch loop failed: %s',type(exc).__name__)
                app.bot_data['last_europe_prematch_poll']=dict(status='ABSTAIN',reason='EUROPE_AUTO_LOOP_ERROR')
            await asyncio.sleep(interval)


def status(directory):
    root=local_path(directory);files=list(root.glob('auto-*.json'))
    if len(files)>4096:raise ValueError('EUROPE_AUTO_JOURNAL_BUDGET')
    latest=None
    for f in files:
        if f.stat().st_size>128*1024:raise ValueError('EUROPE_AUTO_JOURNAL_SIZE')
        w=json.loads(f.read_text());p=w['payload']
        if digest(p)!=w['sha256'] or f.stem!='auto-'+w['sha256']:raise ValueError('EUROPE_AUTO_JOURNAL_PIN')
        if latest is None or (p['completed_at_utc'],p['sequence'],digest(p))>(latest['completed_at_utc'],latest['sequence'],digest(latest)):latest=p
    return dict(status='RECORDED_ATTEMPT_AVAILABLE' if latest else 'NO_RECORDED_ATTEMPTS',last_attempt=latest,
        query_read_only=True,forecast_created=False,production_changed=False,actual_telegram_delivery_verified=False)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--directory',required=True);args=p.parse_args()
    try:print(json.dumps(status(args.directory),ensure_ascii=False,sort_keys=True))
    except (ValueError,KeyError,TypeError,OSError):
        print(json.dumps(dict(status='ABSTAIN',reason='EUROPE_AUTO_JOURNAL_UNAVAILABLE_OR_UNVERIFIED')));raise SystemExit(2)

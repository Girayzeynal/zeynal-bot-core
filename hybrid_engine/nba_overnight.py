"""Isolated NBA overnight preparation and immediate registered research capture.

Freshness is measured at capture, not an instruction to stay awake until tipoff.
The original model, preregistered policy, forecasts and results remain immutable.
"""
import asyncio
from copy import deepcopy
from datetime import datetime,timedelta
import logging
import sqlite3
import time
from zoneinfo import ZoneInfo

from core.team_identity import digest
from hybrid_engine.data import local_path
from hybrid_engine.europe_prematch import EuropeanPrematchScheduler
from hybrid_engine.forward_nba_results import read_confirmed
from hybrid_engine.live_nba import LiveNBAHybridService
from hybrid_engine.time_policy import PREMATCH_MINIMUM_LEAD_SECONDS
from hybrid_engine.runtime_reports import REPORT_ERRORS

LOG=logging.getLogger(__name__)
LOOKAHEAD=36*3600
MINIMUM_LEAD=PREMATCH_MINIMUM_LEAD_SECONDS
RETRY_SECONDS=300
STAGE_ERRORS=REPORT_ERRORS+(asyncio.TimeoutError,)


def error_code(exc):
    # Exception text is untrusted even when it looks like an uppercase code.
    # Only native SQLite primary/extended numbers and fixed categories may leave this worker.
    if isinstance(exc,(asyncio.TimeoutError,TimeoutError)):return 'REPORT_TIMEOUT'
    if isinstance(exc,sqlite3.Error):
        extended=getattr(exc,'sqlite_errorcode',None)
        primary=extended & 0xff if type(extended) is int else None
        return {5:'SQLITE_BUSY',6:'SQLITE_LOCKED',9:'SQLITE_INTERRUPT',
                11:'SQLITE_INTEGRITY',26:'SQLITE_INTEGRITY',14:'SQLITE_ACCESS',
                3:'SQLITE_ACCESS',8:'SQLITE_ACCESS',23:'SQLITE_ACCESS',
                10:'SQLITE_IO',13:'SQLITE_FULL'}.get(primary,'SQLITE_OTHER')
    if isinstance(exc,OSError):return 'REPORT_FILE_ACCESS_OR_IO'
    if isinstance(exc,(ValueError,KeyError,TypeError)):return 'REPORT_VALIDATION_FAILED'
    return 'REPORT_RUNTIME_FAILURE'


def stage_failure(report,stage,exc):
    code=error_code(exc)
    report['stage_errors'].append(dict(stage=stage,error=code,error_type=type(exc).__name__))
    LOG.warning('NBA overnight stage=%s error=%s type=%s',stage,code,type(exc).__name__)
    return code


class PrematchDeadlineLedger:
    """Apply the final-five-minute boundary only to new NBA commits."""
    def __init__(self,ledger):self.original=ledger
    def __getattr__(self,name):return getattr(self.original,name)
    def commit(self,payload):
        p=deepcopy(payload);p['record_deadline_utc']=min(p.get('record_deadline_utc',p['fixture_start_utc']),p['fixture_start_utc']-MINIMUM_LEAD)
        return self.original.commit(p)


async def upcoming(loader,now):
    first=datetime.fromtimestamp(now,ZoneInfo('Europe/Istanbul')).date()
    last=datetime.fromtimestamp(now+LOOKAHEAD,ZoneInfo('Europe/Istanbul')).date()
    games={}
    for i in range((last-first).days+1):
        for row in await loader((first+timedelta(days=i)).isoformat()):
            if not isinstance(row.get('start'),datetime) or row['start'].tzinfo is None:
                raise ValueError('NBA_AUTO_AWARE_START_REQUIRED')
            start=int(row['start'].timestamp())
            if row.get('status')!='Başlamadı' or not now+MINIMUM_LEAD<start<=now+LOOKAHEAD:continue
            if not str(row['id']).isascii() or not str(row['id']).isdigit():raise ValueError('NBA_AUTO_NATIVE_EVENT_ID_REQUIRED')
            item=dict(provider_fixture_id=str(row['id']),start_utc=start,
                day=row['start'].astimezone(ZoneInfo('Europe/Istanbul')).date().isoformat(),home=row['home'],away=row['away'])
            if item['provider_fixture_id'] in games and games[item['provider_fixture_id']]!=item:
                raise ValueError('NBA_AUTO_CONFLICTING_FIXTURES')
            games[item['provider_fixture_id']]=item
    return sorted(games.values(),key=lambda r:(r['start_utc'],r['provider_fixture_id']))


class NBAOvernightScheduler:
    def __init__(self,service,loader,directory,protocol_directory,*,clock=time.time,maximum=2):
        if not isinstance(service,LiveNBAHybridService) or type(maximum) is not int or not 1<=maximum<=4:
            raise ValueError('NBA_AUTO_VERIFIED_SERVICE_AND_BOUNDED_MAXIMUM_REQUIRED')
        self.service=service;self.loader=loader;self.root=local_path(directory);self.protocol=local_path(protocol_directory)
        if not isinstance(service.ledger,PrematchDeadlineLedger):service.ledger=PrematchDeadlineLedger(service.ledger)
        self.clock=clock;self.maximum=maximum;self.running=False;self.last_report=None;self.next_scan=0;self.retry={}
        self.capture_retry_at=0;self.progress_retry_at=0
        # Reuse bounded append-only journal storage, not European scheduling.
        self.journal=EuropeanPrematchScheduler({},self.root,clock=clock)

    def capture(self):
        from hybrid_engine.challenger_forward import capture
        r=capture(self.service.ledger.path,self.service.assets,self.protocol,maximum=4)
        # The reused legacy function reports its original CLI entry location.
        # Annotate our real execution context without rewriting any forecast.
        r['legacy_entry_location']=r['inference_location']
        r['inference_location']='ISOLATED_BACKGROUND_WORKER_NOT_TELEGRAM_REQUEST'
        return r

    def progress(self):
        from hybrid_engine.challenger_forward import performance
        r=performance(self.service.ledger.path,self.protocol)
        return dict(status='REGISTERED_PROTOCOL_VALID',protocol_sha256=r['protocol_sha256'],
            settled=r['settled'],pending=r['pending'],groups=[dict(cohort=g['cohort'],
                matched=g['preregistered_primary_interval']['n'],day_clusters=g['preregistered_primary_interval']['day_clusters'],
                gate=g['primary_statistical_gate']) for g in r['groups']],
            automatic_promotion=False,production_changed=False)

    async def capture_checked(self,report):
        if int(self.clock())<self.capture_retry_at:
            return dict(status='ABSTAIN',reason='NBA_AUTO_CAPTURE_RETRY_COOLDOWN',retry_at_utc=self.capture_retry_at)
        try:
            result=await asyncio.to_thread(self.capture)
        except STAGE_ERRORS as exc:
            code=stage_failure(report,'RESEARCH_CAPTURE',exc)
            self.capture_retry_at=int(self.clock())+RETRY_SECONDS
            return dict(status='ABSTAIN',reason='EXISTING_VALID_PROTOCOL_OR_FRESH_INPUTS_REQUIRED',
                        error=code,retry_at_utc=self.capture_retry_at)
        self.capture_retry_at=0
        return result

    async def progress_checked(self,report):
        if int(self.clock())<self.progress_retry_at:
            return dict(status='ABSTAIN',reason='NBA_AUTO_PROGRESS_RETRY_COOLDOWN',retry_at_utc=self.progress_retry_at)
        try:
            result=await asyncio.to_thread(self.progress)
        except STAGE_ERRORS as exc:
            code=stage_failure(report,'RESEARCH_PROGRESS',exc)
            self.progress_retry_at=int(self.clock())+RETRY_SECONDS
            return dict(status='ABSTAIN',reason='REGISTERED_FORWARD_PROGRESS_UNAVAILABLE',
                        error=code,retry_at_utc=self.progress_retry_at)
        self.progress_retry_at=0
        return result

    async def tick(self,*,force=False):
        if self.running:return dict(status='ABSTAIN',reason='NBA_AUTO_ALREADY_RUNNING')
        self.running=True;now=int(self.clock());self.retry={k:v for k,v in self.retry.items() if v>now}
        report=dict(format='NBA_OVERNIGHT_PREMATCH_V1',evaluated_at_utc=now,completed_at_utc=now,
            sequence=int(time.time_ns()),lookahead_seconds=LOOKAHEAD,minimum_lead_seconds=MINIMUM_LEAD,
            predictions=[],acceptance=None,progress=None,stage_errors=[],production_changed=False,active_model_refit=False,
            offline_candidate_posterior_updates=True,
            calibration_fit=False,actual_telegram_delivery_verified=False)
        try:
            if force or now>=self.next_scan:
                stage='FIXTURE_DISCOVERY'
                try:
                    games=await upcoming(self.loader,now)
                    stage='ORIGINAL_ARCHIVE_READ'
                    old=await asyncio.to_thread(read_confirmed,self.service.ledger.path)
                    saved={str(pid) for r in old for pid in r['snapshot']['provider_fixture_ids']}
                    ready=[g for g in games if g['provider_fixture_id'] not in saved and now>=self.retry.get(g['provider_fixture_id'],0)]
                    report.update(eligible=len(ready),already_archived=sum(g['provider_fixture_id'] in saved for g in games))
                    self.next_scan=int(self.clock())+(60 if len(ready)>self.maximum else 600)
                    for g in ready[:self.maximum]:
                        pid=g['provider_fixture_id']
                        try:
                            if int(self.clock())>=g['start_utc']-MINIMUM_LEAD:raise ValueError('NBA_AUTO_SAFE_WINDOW_CLOSED')
                            result=await asyncio.wait_for(self.service.analyze('NBA',g['day'],g['home'],g['away']),timeout=100)
                            if result.get('status')!='ANALYSIS_OK':
                                self.retry[pid]=int(self.clock())+300
                                report['predictions'].append(dict(**g,status='ABSTAIN',reason='VERIFIED_FIXTURE_HISTORY_OR_MODEL_REQUIRED'));continue
                            p=result['snapshot']
                            if (p['provider_fixture_ids']!=[pid] or p['fixture_start_utc']!=g['start_utc'] or
                                    not p['created_at_utc']<g['start_utc']-MINIMUM_LEAD):
                                raise ValueError('NBA_AUTO_ARCHIVED_FIXTURE_OR_CUTOFF_CONFLICT')
                            report['predictions'].append(dict(**g,status='ARCHIVED' if result['new_record'] else 'REUSED',
                                snapshot_sha256=digest(p),prediction_generated_at_utc=p['prediction_generated_at_utc']))
                            # Before moving to another game, preserve the fresh
                            # original inputs under the existing experiment plan.
                            # Preserve a successful original even if the optional capture fails.
                            if int(self.clock())>=self.capture_retry_at:
                                report['acceptance']=await self.capture_checked(report)
                        except STAGE_ERRORS as exc:
                            self.retry[pid]=int(self.clock())+RETRY_SECONDS
                            code=stage_failure(report,'FIXTURE_ANALYSIS',exc)
                            report['predictions'].append(dict(**g,status='ABSTAIN',reason='NBA_AUTO_SOURCE_ARCHIVE_OR_TIMEOUT',error=code))
                    while len(self.retry)>512:self.retry.pop(next(iter(self.retry)))
                    if self.retry:self.next_scan=min(self.next_scan,min(self.retry.values()))
                except STAGE_ERRORS as exc:
                    report['discovery_status']='ABSTAIN_OFFICIAL_FIXTURE_OR_ARCHIVE_UNAVAILABLE'
                    report['discovery_error']=stage_failure(report,stage,exc)
                    self.next_scan=int(self.clock())+RETRY_SECONDS
            # Also process fresh manual publications: the user never stops the
            # bot to run a terminal capture command. Old inputs stay excluded.
            if report['acceptance'] is None:report['acceptance']=await self.capture_checked(report)
            report['progress']=await self.progress_checked(report)
            report['completed_at_utc']=int(self.clock())
            report['status']='PARTIAL_ABSTAIN' if (report.get('discovery_status') or
                any(r['status']=='ABSTAIN' for r in report['predictions']) or report['acceptance'].get('status')=='ABSTAIN' or
                any(r.get('status')=='BLOCKED' for r in report['acceptance'].get('results',[])) or
                report['progress']['status']=='ABSTAIN') else 'CHECKED'
            if report['predictions'] or report.get('discovery_status') or report['acceptance'].get('results'):
                try:await asyncio.to_thread(self.journal.publish,report)
                except STAGE_ERRORS as exc:
                    report['status']='PARTIAL_ABSTAIN';report['journal_status']='ABSTAIN_JOURNAL_UNAVAILABLE'
                    stage_failure(report,'JOURNAL_WRITE',exc)
            for r in report['predictions']:LOG.info('NBA overnight capture: event=%s status=%s',r['provider_fixture_id'],r['status'])
            self.last_report=report;return report
        finally:self.running=False

    async def run(self,app):
        while True:
            try:app.bot_data['last_nba_overnight_poll']=await self.tick()
            except asyncio.CancelledError:raise
            except Exception as exc:
                code=error_code(exc)
                LOG.error('NBA overnight loop failed: %s · %s',type(exc).__name__,code)
                self.last_report=dict(status='ABSTAIN',reason='NBA_AUTO_LOOP_ERROR',
                    stage_errors=[dict(stage='LOOP',error=code,error_type=type(exc).__name__)],
                    production_changed=False)
                app.bot_data['last_nba_overnight_poll']=self.last_report
            await asyncio.sleep(60)

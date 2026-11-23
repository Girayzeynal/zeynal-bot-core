"""Isolated NBA overnight preparation and immediate registered research capture.

Freshness is measured at capture, not an instruction to stay awake until tipoff.
The original model, preregistered policy, forecasts and results remain immutable.
"""
import asyncio
from copy import deepcopy
from datetime import datetime,timedelta
import logging
import time
from zoneinfo import ZoneInfo

from core.team_identity import digest
from hybrid_engine.data import local_path
from hybrid_engine.europe_prematch import EuropeanPrematchScheduler
from hybrid_engine.forward_nba_results import read_confirmed
from hybrid_engine.live_nba import LiveNBAHybridService
from hybrid_engine.time_policy import PREMATCH_MINIMUM_LEAD_SECONDS

LOG=logging.getLogger(__name__)
LOOKAHEAD=36*3600
MINIMUM_LEAD=PREMATCH_MINIMUM_LEAD_SECONDS


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

    async def tick(self,*,force=False):
        if self.running:return dict(status='ABSTAIN',reason='NBA_AUTO_ALREADY_RUNNING')
        self.running=True;now=int(self.clock());self.retry={k:v for k,v in self.retry.items() if v>now}
        report=dict(format='NBA_OVERNIGHT_PREMATCH_V1',evaluated_at_utc=now,completed_at_utc=now,
            sequence=int(time.time_ns()),lookahead_seconds=LOOKAHEAD,minimum_lead_seconds=MINIMUM_LEAD,
            predictions=[],acceptance=None,progress=None,production_changed=False,active_model_refit=False,
            offline_candidate_posterior_updates=True,
            calibration_fit=False,actual_telegram_delivery_verified=False)
        try:
            if force or now>=self.next_scan:
                try:
                    games=await upcoming(self.loader,now)
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
                            try:report['acceptance']=await asyncio.to_thread(self.capture)
                            except (ValueError,KeyError,TypeError,OSError,RuntimeError):
                                report['acceptance']=dict(status='ABSTAIN',reason='EXISTING_VALID_PROTOCOL_OR_FRESH_INPUTS_REQUIRED')
                        except (ValueError,KeyError,TypeError,OSError,RuntimeError,TimeoutError):
                            self.retry[pid]=int(self.clock())+300
                            report['predictions'].append(dict(**g,status='ABSTAIN',reason='NBA_AUTO_SOURCE_ARCHIVE_OR_TIMEOUT'))
                    while len(self.retry)>512:self.retry.pop(next(iter(self.retry)))
                except (ValueError,KeyError,TypeError,OSError,RuntimeError):
                    report['discovery_status']='ABSTAIN_OFFICIAL_FIXTURE_OR_ARCHIVE_UNAVAILABLE';self.next_scan=int(self.clock())+300
            # Also process fresh manual publications: the user never stops the
            # bot to run a terminal capture command. Old inputs stay excluded.
            if report['acceptance'] is None:
                try:report['acceptance']=await asyncio.to_thread(self.capture)
                except (ValueError,KeyError,TypeError,OSError,RuntimeError):
                    report['acceptance']=dict(status='ABSTAIN',reason='EXISTING_VALID_PROTOCOL_OR_FRESH_INPUTS_REQUIRED')
            try:report['progress']=await asyncio.to_thread(self.progress)
            except (ValueError,KeyError,TypeError,OSError,RuntimeError):
                report['progress']=dict(status='ABSTAIN',reason='REGISTERED_FORWARD_PROGRESS_UNAVAILABLE')
            report['completed_at_utc']=int(self.clock())
            report['status']='PARTIAL_ABSTAIN' if (report.get('discovery_status') or
                any(r['status']=='ABSTAIN' for r in report['predictions']) or report['acceptance'].get('status')=='ABSTAIN' or
                any(r.get('status')=='BLOCKED' for r in report['acceptance'].get('results',[])) or
                report['progress']['status']=='ABSTAIN') else 'CHECKED'
            if report['predictions'] or report.get('discovery_status') or report['acceptance'].get('results'):
                try:await asyncio.to_thread(self.journal.publish,report)
                except (ValueError,OSError):
                    report['status']='PARTIAL_ABSTAIN';report['journal_status']='ABSTAIN_JOURNAL_UNAVAILABLE'
                    LOG.error('NBA overnight journal unavailable; original records retained')
            for r in report['predictions']:LOG.info('NBA overnight capture: event=%s status=%s',r['provider_fixture_id'],r['status'])
            self.last_report=report;return report
        finally:self.running=False

    async def run(self,app):
        while True:
            try:app.bot_data['last_nba_overnight_poll']=await self.tick()
            except asyncio.CancelledError:raise
            except Exception as exc:
                LOG.error('NBA overnight loop failed: %s',type(exc).__name__)
                app.bot_data['last_nba_overnight_poll']=dict(status='ABSTAIN',reason='NBA_AUTO_LOOP_ERROR')
            await asyncio.sleep(60)

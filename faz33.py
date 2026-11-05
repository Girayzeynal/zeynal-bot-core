"""Manual development tick for prospective NBA cuts. Installs no production timer."""
import argparse
import asyncio
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
from statistics import mean,pstdev
import subprocess
import sqlite3
import tempfile
import time
from zoneinfo import ZoneInfo

from baseline.team_baseline_store import TeamBaselineStore,TeamBaseline
from faz13_engine import Faz13Engine,PrematchRequest
from faz22_engine import Faz22Engine
from faz23_engine import Faz23Engine
from faz24 import build_bundle
from faz25 import exclusive
from faz32 import read_store
from nba_season_2027 import parse_scheduled,require_regular,policy,ZONE
from period_feature_layer import materialize_period,export_observations
from prediction_inputs import digest
from providers.espn_adapter import ESPNAdapter,ESPN_BASE
from providers.espn_completed_event import parse_completed_nba_event
from providers.espn_pace_evidence import capture_pace_evidence
from prospective_cuts import CutLedger,HORIZONS,GRACE,due,inspect
from shadow_features import make_features
from shadow_ridge import predict


class ProviderUnavailable(RuntimeError):
    def __init__(self,status,retry_after_utc):
        super().__init__(status);self.status=status;self.retry_after_utc=retry_after_utc


def compact_schedule(event):
    c=event['competitions'][0]
    result=dict(id=event['id'],date=event['date'],season=deepcopy(event['season']),status=deepcopy(event['status']),
        competitions=[dict(id=c['id'],date=c.get('date',event['date']),status=deepcopy(c['status']),
            competitors=[dict(homeAway=r['homeAway'],team=dict(id=r['team']['id'])) for r in c['competitors']])])
    for raw,out in ((event,result),(c,result['competitions'][0])):
        for field in ('dateValid','timeValid','tbd'):
            if field in raw:out[field]=raw[field]
    return result


class Runner:
    def __init__(self,ledger,research_store,adapter,*,model_sha,artifact=None,timeout=20,verify_source=False):
        self.ledger=ledger;self.store=research_store;self.api=adapter;self.model_sha=model_sha
        self.artifact=artifact;self.timeout=timeout;self.directory={};self.directory_observation=None
        self.verify_source=verify_source

    def check_source(self):
        if not self.verify_source:return
        repo=Path(__file__).resolve().parent
        head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
        branch=subprocess.check_output(['git','branch','--show-current'],cwd=repo,text=True).strip()
        dirty=subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=repo,text=True)
        if head!=self.model_sha or branch!='feature/nba-command-20261104' or dirty:raise ValueError('SOURCE_VERSION_CHANGED_OR_DIRTY')

    async def fetch(self,url):
        try:raw=await asyncio.wait_for(self.api._get_json(url),timeout=self.timeout)
        except asyncio.TimeoutError:raise ProviderUnavailable('TIMEOUT',int(time.time())+60)
        except (OSError,ConnectionError):raise ProviderUnavailable('NETWORK_UNAVAILABLE',int(time.time())+60)
        now=int(time.time())
        if not isinstance(raw,dict):
            code=getattr(self.api,'last_http_status',None)
            status={403:'HTTP_403',429:'HTTP_429'}.get(code,'NETWORK_OR_PROVIDER_UNAVAILABLE')
            blocked=getattr(self.api,'_blocked_until',0)
            raise ProviderUnavailable(status,max(now+60,int(blocked)))
        return raw,dict(source_url=url,source_observed_utc=now,ingested_utc=now,source_response_sha256=digest(raw))

    async def discover(self):
        raw,stamp=await self.fetch(ESPN_BASE+'/teams')
        try:
            self.directory={r['team']['id']:dict(abbr=r['team']['abbreviation'],name=r['team']['displayName']) for r in raw['sports'][0]['leagues'][0]['teams']}
        except (KeyError,TypeError,IndexError):raise ValueError('INVALID_NBA_DIRECTORY')
        if set(self.directory)!=self.store.team_ids:raise ValueError('NBA_DIRECTORY_ID_SET_CHANGED')
        self.directory_observation=dict(stamp,teams=deepcopy(self.directory),sha256=digest(self.directory))
        today=datetime.fromtimestamp(time.time(),ZONE).date();fixtures={};rejected=[]
        for offset in range(3):
            day=(today+timedelta(days=offset)).strftime('%Y%m%d');raw,stamp=await self.fetch(ESPN_BASE+'/scoreboard?dates='+day)
            if not isinstance(raw.get('events'),list):raise ValueError('MALFORMED_SCOREBOARD')
            for event in raw['events']:
                try:
                    fixture=parse_scheduled(event,self.store.team_ids)
                    if fixture['start_ts_utc']<=int(time.time()):raise ValueError('ALREADY_STARTED')
                    k=fixture['provider_fixture_id']
                    snapshot=compact_schedule(event)
                    observation=dict(stamp,event=snapshot,sha256=digest(snapshot))
                    if k in fixtures and fixtures[k]['fixture']!=fixture:raise ValueError('CONFLICTING_FIXTURE_OBSERVATIONS')
                    for other in fixtures.values():
                        e=other['fixture']
                        if k!=e['provider_fixture_id'] and e['start_ts_utc']==fixture['start_ts_utc'] and set((e['home_team_id'],e['away_team_id'])).intersection((fixture['home_team_id'],fixture['away_team_id'])):
                            raise ValueError('SAME_TEAM_START_ALIAS')
                    fixtures[k]=dict(fixture=fixture,schedule=observation)
                except (ValueError,KeyError,TypeError) as exc:
                    rejected.append(dict(fixture_id=event.get('id'),status=str(exc)))
                    # Identity conflicts are batch-fatal: neither alias is safe.
                    if str(exc) in ('SAME_TEAM_START_ALIAS','CONFLICTING_FIXTURE_OBSERVATIONS'):raise
        return sorted(fixtures.values(),key=lambda r:(r['fixture']['start_ts_utc'],r['fixture']['provider_fixture_id'])),rejected

    async def recheck(self,fixture):
        raw,stamp=await self.fetch(ESPN_BASE+'/summary?event='+fixture['provider_fixture_id'])
        h=deepcopy(raw['header']);c=h['competitions'][0];h['date']=c['date']
        if 'status' not in h:h['status']=deepcopy(c['status'])
        if parse_scheduled(h,self.store.team_ids)!=fixture:raise ValueError('RESCHEDULED_OR_CHANGED_IDENTITY')
        h=compact_schedule(h)
        return dict(stamp,event=h,sha256=digest(h))

    async def refresh_history(self,fixture):
        seen=set();inserted=0
        for side in ('home','away'):
            raw,stamp=await self.fetch(ESPN_BASE+'/teams/'+fixture[side+'_team_id']+'/schedule?season=2027&seasontype=2')
            from nba_history_contract import completed_history
            games=completed_history(raw,stamp['source_observed_utc'],fixture[side+'_team_id'])
            for game in sorted(games,key=lambda e:e['start_ts_utc'],reverse=True)[:10]:
                k=game['provider_fixture_id']
                if k in seen:continue
                seen.add(k);began=int(time.time());summary,observed=await self.fetch(ESPN_BASE+'/summary?event='+k)
                from nba_research_store import validate_summary
                if validate_summary(summary,observed['source_observed_utc'],self.store.team_ids)['event']!=game:raise ValueError('HISTORY_SCOREBOARD_SUMMARY_CONFLICT')
                inserted+=int(self.store.ingest(summary,observed['source_observed_utc'],'NEW_DOWNLOAD',
                    dict(collection_started_utc=began,file_sha256=digest(summary),source_url=observed['source_url'],hash_encoding='canonical_json',team_schedule_source=stamp)))
        return inserted

    async def capture(self,item,horizon,*,refresh=True):
        self.check_source()
        fixture=item['fixture'];fid=fixture['provider_fixture_id']
        if self.ledger.has(fid,horizon):return dict(status='ALREADY_RECORDED',fixture_id=fid,horizon=horizon)
        if int(time.time())>=fixture['start_ts_utc']:raise ValueError('ALREADY_STARTED')
        if due(fixture,horizon,int(time.time()))!='DUE':raise ValueError(due(fixture,horizon,int(time.time())))
        initial=await self.recheck(fixture)
        if refresh:await self.refresh_history(fixture)
        # Imports completed in this second become usable at an actual later second.
        if refresh:await asyncio.sleep(1.01)
        rows=self.store.select(int(time.time()),'PROSPECTIVE',2027)
        rows=[r for r in rows if int(time.time())-45*86400<r['payload']['facts']['event']['start_ts_utc']<int(time.time())]
        records=[];sources=[]
        for r in rows:
            p=r['payload'];event=p['facts']['event'];require_regular(p['summary']['header'],event['start_ts_utc'])
            records.append(materialize_period(p['summary'],source_observed_utc=p['source_observed_utc'],source_evidence_sha256=r['sha256'],input_ref=dict(observation_id=r['observation_id'])))
            sources.append(dict(observation_id=r['observation_id'],payload_sha256=r['sha256'],summary_sha256=digest(p['summary']),source_observed_utc=p['source_observed_utc'],ingested_utc=p['ingested_utc']))
        records=export_observations(records)
        # Wait for the actual next clock second; never forge an earlier materialization.
        latest=max((r['payload']['usable_after_utc'] for r in records),default=0)
        if int(time.time())<=latest:await asyncio.sleep(max(0,latest+1-time.time())+.01)
        cutoff=int(time.time());features=make_features(records,fixture,cutoff)
        if due(fixture,horizon,cutoff)!='DUE':raise ValueError('CUT_EXPIRED_DURING_PREPARATION')
        team_keys={side:self.directory[fixture[side+'_team_id']]['abbr'] for side in ('home','away')}
        with tempfile.TemporaryDirectory() as directory:
            baselines=TeamBaselineStore(str(Path(directory)/'baselines'))
            for side,key in team_keys.items():
                team=fixture[side+'_team_id'];games=[]
                for r in rows:
                    p=r['payload'];event=p['facts']['event']
                    if team not in (event['home_team_id'],event['away_team_id']):continue
                    evidence=capture_pace_evidence(p['summary'],event,observed_at_utc=p['source_observed_utc'])
                    if evidence is None:continue
                    home=team==event['home_team_id'];own='home' if home else 'away';opp='away' if home else 'home'
                    games.append(dict(ts_utc=event['start_ts_utc'],pts_for=event['actual_'+own],pts_against=event['actual_'+opp],pace=evidence['pace'],home=home,game_id=event['provider_fixture_id'],source=evidence['method'],timestamp_precision='exact',pace_evidence=evidence))
                games=sorted(games,key=lambda r:r['ts_utc'])[-6:]
                if len(games)<6:raise ValueError('REFERENCE_MIN_6_VERIFIED_GAMES:'+side)
                for game in games:baselines.append_game('NBA',key,**game)
                baselines.put(TeamBaseline('NBA',key,len(games),mean(g['pts_for'] for g in games),mean(g['pts_against'] for g in games),mean(g['pace'] for g in games),pstdev(g['pts_for']+g['pts_against'] for g in games),int(time.time())))
            engine=Faz13Engine('','',baseline_store=baselines);engine.espn=None
            day=datetime.fromtimestamp(fixture['start_ts_utc'],ZoneInfo('Europe/Istanbul')).date().isoformat()
            first=await engine.run_prematch(PrematchRequest(0,'NBA',day,team_keys['home'],team_keys['away']))
            second=Faz22Engine().score_and_finalize(deepcopy(first));third=Faz23Engine(str(Path(directory)/'decisions.sqlite')).apply_decision(deepcopy(second))
            bundle=build_bundle([first,second,third],self.model_sha,multilayer_config={})
        shadow=dict(artifact=self.artifact,prediction=None,status='NO_MODEL_AVAILABLE')
        if self.artifact is not None:
            if features['payload']['status']!='READY':shadow['status']='FEATURES_UNAVAILABLE'
            else:
                try:shadow.update(status='PREDICTED_EXPERIMENTAL',prediction=predict(self.artifact,features))
                except ValueError as exc:shadow.update(status='MODEL_UNAVAILABLE_AT_CUTOFF',reason=str(exc))
        rechecked=await self.recheck(fixture)
        packet=dict(schema_version=1,usage=self.ledger.mode,fixture=fixture,horizon=horizon,scheduled_cutoff_utc=fixture['start_ts_utc']-HORIZONS[horizon],
            cutoff_utc=cutoff,created_utc=int(time.time()),model_sha=self.model_sha,season_policy_sha256=policy()['sha256'],team_ids=sorted(self.store.team_ids),team_keys=team_keys,
            directory=self.directory_observation,schedule=initial,precommit_schedule=rechecked,sources=sources,features=features,reference=dict(bundle=bundle,inputs=first.meta['input_snapshot']),shadow=shadow,
            reference_input_cutoff_utc=cutoff,reference_window_games=6,missing_data=['UNVERIFIED_INJURIES','UNVERIFIED_ROSTERS','UNVERIFIED_MARKET','UNVERIFIED_RECOVERY','UNCALIBRATED_PROBABILITIES','PACE_IS_BOX_SCORE_ESTIMATE'])
        self.check_source();inserted=self.ledger.insert(packet)
        return dict(status='RECORDED' if inserted else 'ALREADY_RECORDED',fixture_id=fid,horizon=horizon,cutoff_utc=cutoff,shadow_status=shadow['status'],features_status=features['payload']['status'])

    async def reconcile(self):
        with self.ledger.connect() as db:pending=db.execute('SELECT fixture_id,start_utc FROM faz33_fixtures WHERE start_utc<? AND fixture_id NOT IN (SELECT fixture_id FROM faz33_evaluations)',(int(time.time()),)).fetchall()
        results=[]
        for fid,start in pending[:10]:
            raw,stamp=await self.fetch(ESPN_BASE+'/summary?event='+fid)
            from providers.espn_result_evidence import parse_final_summary
            if parse_final_summary(raw,stamp['source_observed_utc']) is None:
                try:status=raw['header']['competitions'][0]['status']['type']
                except (KeyError,TypeError,IndexError):status={}
                code='INVALID_FINAL_DATA' if status.get('completed') is True else 'AWAITING_VERIFIED_FINAL' if status.get('state') in ('pre','in') else 'INVALID_RESULT_DATA'
                results.append(dict(fixture_id=fid,status=code));continue
            try:
                inserted=self.ledger.record_final(raw,stamp['source_observed_utc']);results.append(dict(fixture_id=fid,status='FINAL_RECORDED' if inserted else 'FINAL_ALREADY_RECORDED'))
            except ValueError as exc:
                self.ledger.log('INVALID_FINAL_PERIOD_OR_IDENTITY',fid,details=dict(error=str(exc)))
                results.append(dict(fixture_id=fid,status='INVALID_FINAL_PERIOD_OR_IDENTITY'))
        return results

    async def tick(self,*,dry_run=False,max_cuts=4):
        with exclusive(self.ledger.path) as acquired:
            if not acquired:return dict(status='BUSY',actions=[])
            return await self._tick_locked(dry_run=dry_run,max_cuts=max_cuts)

    async def _tick_locked(self,*,dry_run=False,max_cuts=4):
        # Private: caller must hold the same FAZ25/33 advisory lock.
        with self.ledger.connect() as db:attempts=db.execute('SELECT details FROM faz33_attempts WHERE status IN (\'HTTP_403\',\'HTTP_429\',\'TIMEOUT\',\'NETWORK_UNAVAILABLE\',\'NETWORK_OR_PROVIDER_UNAVAILABLE\') ORDER BY id DESC LIMIT 1').fetchone()
        if attempts and json.loads(attempts[0]).get('retry_after_utc',0)>int(time.time()):return dict(status='PROVIDER_COOLDOWN',actions=[])
        actions=[]
        try:
            self.check_source()
            if not dry_run:actions.extend(await self.reconcile())
            fixtures,rejected=await self.discover();plan=[]
            for item in fixtures:
                fixture=item['fixture']
                for horizon in HORIZONS:
                    status='ALREADY_RECORDED' if self.ledger.has(fixture['provider_fixture_id'],horizon) else due(fixture,horizon,int(time.time()))
                    plan.append(dict(fixture=fixture,horizon=horizon,status=status,scheduled_cutoff_utc=fixture['start_ts_utc']-HORIZONS[horizon]))
            if not dry_run:
                for entry in [r for r in plan if r['status']=='DUE'][:max_cuts]:
                    item=next(i for i in fixtures if i['fixture']==entry['fixture'])
                    try:actions.append(await self.capture(item,entry['horizon']))
                    except ProviderUnavailable:raise
                    except (ValueError,KeyError,TypeError,sqlite3.Error) as exc:
                        status=str(exc) if isinstance(exc,ValueError) else 'INVALID_DATA:'+type(exc).__name__
                        self.ledger.log(status,entry['fixture']['provider_fixture_id'],entry['horizon']);actions.append(dict(status=status,fixture_id=entry['fixture']['provider_fixture_id'],horizon=entry['horizon']))
            return dict(status='DRY_RUN' if dry_run else 'TICK_COMPLETE',actions=actions,plan=plan,fixtures_observations=fixtures,rejected_schedule=rejected,predictions_written=sum(x['status']=='RECORDED' for x in actions),observed_utc=int(time.time()))
        except ProviderUnavailable as exc:
            if not dry_run:self.ledger.log(exc.status,details=dict(retry_after_utc=exc.retry_after_utc))
            return dict(status=exc.status,retry_after_utc=exc.retry_after_utc,actions=actions)
        except (ValueError,KeyError,TypeError) as exc:
            if not dry_run:self.ledger.log('INVALID_SCHEDULE_OR_DATA',details=dict(error=str(exc)))
            return dict(status='INVALID_SCHEDULE_OR_DATA',error=str(exc),actions=actions)


async def development_ticks(runner,*,ticks=1,interval=60,dry_run=False):
    """Bounded opt-in local loop; no daemon, cron or cloud scheduler install."""
    if type(ticks) is not int or not 1<=ticks<=1440 or type(interval) is not int or not 60<=interval<=300:
        raise ValueError('bounded development loop requires 1..1440 ticks and 60..300 second interval')
    for i in range(ticks):
        began=time.monotonic();result=await runner.tick(dry_run=dry_run);yield result
        if result.get('error')=='SOURCE_VERSION_CHANGED_OR_DIRTY':break
        if i+1<ticks:await asyncio.sleep(max(0,interval-(time.monotonic()-began)))


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    q=sub.add_parser('tick');q.add_argument('database');q.add_argument('research_database');q.add_argument('--dry-run',action='store_true');q.add_argument('--shadow-model')
    q=sub.add_parser('watch');q.add_argument('database');q.add_argument('research_database');q.add_argument('--dry-run',action='store_true');q.add_argument('--shadow-model')
    q.add_argument('--ticks',type=int,default=1);q.add_argument('--interval',type=int,default=60)
    q=sub.add_parser('report');q.add_argument('database');q.add_argument('--horizon',choices=list(HORIZONS),default='T60M')
    args=p.parse_args()
    if args.command=='report':result=inspect(args.database,args.horizon);result.pop('examples',None)
    else:
        repo=Path(__file__).resolve().parent
        if subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=repo,text=True):raise ValueError('clean source commit required')
        sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
        async def run():
            api=ESPNAdapter()
            try:
                runner=Runner(CutLedger(args.database),read_store(args.research_database),api,model_sha=sha,artifact=json.loads(Path(args.shadow_model).read_text()) if args.shadow_model else None,verify_source=True)
                if args.command=='watch':
                    async for value in development_ticks(runner,ticks=args.ticks,interval=args.interval,dry_run=args.dry_run):print(json.dumps(value,sort_keys=True,allow_nan=False),flush=True)
                    return None
                return await runner.tick(dry_run=args.dry_run)
            finally:await api.aclose()
        result=asyncio.run(run())
    if result is not None:print(json.dumps(result,sort_keys=True,allow_nan=False))


if __name__=='__main__':main()

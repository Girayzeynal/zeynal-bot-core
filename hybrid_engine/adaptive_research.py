"""Independent V2 protocol, scheduled fits and preregistered future ablations."""
from collections import defaultdict
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time

from core.team_identity import digest
from hybrid_engine import adaptive_models
from hybrid_engine.boxes import publish_json
from hybrid_engine.data import Abstain,local_path
from hybrid_engine.europe_prematch import publication_lock,safe_lead
from hybrid_engine.forward_validation import ForwardRegistry
from hybrid_engine.intervals import prediction_intervals
from hybrid_engine.evaluation import point_metrics
from hybrid_engine.player_inputs import validate_witness
from hybrid_engine.player_minutes import MinutesArchive
from hybrid_engine.player_shadow import fit_pair,PreparedPlayerPair,eligible_rows
from hybrid_engine.statistics import paired_cluster_interval

FORMAT='SEPARATE_ADAPTIVE_RESEARCH_PROTOCOL_V2'
POLICY=dict(refresh_seconds=21600,minimum_training_games=30,minimum_box_games_per_target_team=6,
    minimum_player_training_games=100,minimum_future_games=100,minimum_day_clusters=20,minimum_primary_coverage=.8,
    maximum_target_team_box_age_seconds=14*86400,
    primary='PACE_EFFICIENCY',baseline='TEAM_ON_BOX_COHORT',primary_metric='team_mae',minimum_relative_improvement=.02,
    multiplicity=3,selection='ALL_ELIGIBLE_ORIGINALS_ADMITTED_BEFORE_RESULTS_NO_OUTCOME_SELECTION',
    fit_schedule='FIRST_SUCCESSFUL_FIT_PER_SIX_HOUR_UTC_SLOT_ACTUAL_CLOCK_NEVER_BACKDATED',
    capture='FIRST_SUCCESSFUL_NEW_V2_PREMATCH_AT_LEAST_15_MINUTES_BEFORE_TIPOFF',
    player_scope='OWN_TEAM_SCORING_ONLY_SEPARATE_FIRST_PLAYER_PAIR_NO_ADDITIVE_PACE_OFFSET',
    player_exposure_variation_required=True,
    calibration_fit=False,automatic_promotion=False,production_enabled=False)


def point_summary(rows):
    team=point_metrics([r['prediction'][s]-r['actual'][j] for r in rows for j,s in enumerate(('home','away'))])
    total=point_metrics([r['prediction']['total']-sum(r['actual']) for r in rows])
    return dict(n=len(rows),team_mae=team['mae'],team_rmse=team['rmse'],total_mae=total['mae'],total_rmse=total['rmse'])


def source_pins():
    root=Path(__file__).parent
    return {name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in
        ('adaptive_models.py','adaptive_data.py','adaptive_research.py','adaptive_worker.py','models.py','data.py',
         'boxes.py','possession.py','player_shadow.py','player_inputs.py','player_minutes.py','statistics.py','intervals.py')}


def read_wrapper(path,*,maximum=32*1024*1024):
    p=local_path(path)
    if p.stat().st_size>maximum:raise ValueError('ADAPTIVE_ARCHIVE_SIZE')
    w=json.loads(p.read_text())
    if digest(w['payload'])!=w['sha256']:raise ValueError('ADAPTIVE_ARCHIVE_PIN')
    return w


class Registry(ForwardRegistry):
    def asset(self,prefix,payload):
        if prefix=='forecast':safe_lead(payload)
        result=super().asset(prefix,payload)
        if prefix=='forecast':safe_lead(payload)
        return result

    def record(self,payload):
        with publication_lock(self.root):
            old=next((r for r in self.records() if r['payload']['fixture']['canonical_id']==payload['fixture']['canonical_id']
                      and r['payload']['version']==payload['version']),None)
            if old:return old['payload'],False
            safe_lead(payload)
            return super().record(payload)


class AdaptiveResearch:
    def __init__(self,directory,*,player_directory=None):
        self.root=local_path(directory);self.root.mkdir(parents=True,exist_ok=True)
        self.models=self.root/'models';self.models.mkdir(exist_ok=True)
        self.registry=Registry(self.root/'forecasts');self.player_registry=Registry(self.root/'player-forecasts')
        self.players=local_path(player_directory) if player_directory else None

    def plan(self,*,create=False):
        files=list(self.root.glob('plan-*.json'))
        if not files and create:
            with publication_lock(self.root):
                if not list(self.root.glob('plan-*.json')):
                    body=dict(format=FORMAT,registered_at_utc=int(time.time()),policy=POLICY,source_pins=source_pins(),
                        independent_of_existing_nba_challenger=True,production_enabled=False)
                    w=dict(payload=body,sha256=digest(body));publish_json(self.root/('plan-'+w['sha256']+'.json'),w)
            files=list(self.root.glob('plan-*.json'))
        if len(files)!=1:raise ValueError('ADAPTIVE_ONE_SEPARATE_REGISTERED_PLAN_REQUIRED')
        w=read_wrapper(files[0]);p=w['payload']
        if (files[0].stem!='plan-'+w['sha256'] or p['format']!=FORMAT or p['policy']!=POLICY or
                p['source_pins']!=source_pins() or not 0<p['registered_at_utc']<=int(time.time()) or p['production_enabled'] is not False):
            raise ValueError('ADAPTIVE_PLAN_CHANGED_REQUIRES_SEPARATE_VERSION')
        return w

    def admit(self,target,original_pin):
        plan=self.plan();now=int(time.time())
        if not now<target['fixture_start_utc']-900:raise Abstain('ADAPTIVE_NO_LATE_ADMISSION')
        key=digest(dict(protocol=plan['sha256'],fixture=target['fixture_id'],league=target['league']))
        path=self.root/('admit-'+key+'.json')
        with publication_lock(self.root):
            if path.exists():
                p=read_wrapper(path)['payload']
                if p['target']!=target or p['original_snapshot_sha256']!=original_pin:raise ValueError('ADAPTIVE_ADMISSION_IDENTITY_CHANGED')
                return p
            if len(list(self.root.glob('admit-*.json')))>=4096:raise ValueError('ADAPTIVE_ADMISSION_BUDGET')
            body=dict(target=target,protocol_sha256=plan['sha256'],original_snapshot_sha256=original_pin,admitted_at_utc=now)
            publish_json(path,dict(payload=body,sha256=digest(body)));return body

    def fit(self,cohort,league,season):
        plan=self.plan();now=int(time.time());slot=now//POLICY['refresh_seconds']
        key=digest(dict(league=league,season=season,slot=slot,protocol=plan['sha256']))
        path=self.models/('model-'+key+'.json')
        with publication_lock(self.models):
            if path.exists():
                w=read_wrapper(path)
                if (w['payload']['league'],w['payload']['season'],w['payload']['schedule_slot'])!=(league,season,slot):
                    raise ValueError('ADAPTIVE_SCHEDULE_MODEL_IDENTITY')
                return w,False
            files=list(self.models.glob('model-*.json'))
            if len(files)>=4096 or sum(f.stat().st_size for f in files)>256*1024*1024:
                raise Abstain('ADAPTIVE_MODEL_ARCHIVE_BUDGET')
            artifact=adaptive_models.prepare(cohort,cutoff_utc=now)
            p=artifact['payload'];p['protocol_sha256']=plan['sha256'];p['player_pair']=None
            p['player_readiness']=dict(status='BLOCKED_NO_PROSPECTIVE_PLAYER_INPUTS')
            if league=='NBA' and self.players is not None:
                folder=self.players/'minutes';pubs=MinutesArchive(folder).first() if folder.is_dir() else []
                try:
                    player_rows,exposures,_,excluded=eligible_rows(cohort,pubs,self.players,now)
                    samples=defaultdict(list)
                    teams=defaultdict(set)
                    for r in player_rows:
                        for side in ('home','away'):
                            teams[r[side+'_team_id']].update(v['player_id'] for v in exposures[r['fixture_id']][side])
                    for r in player_rows:
                        for side in ('home','away'):
                            values={v['player_id']:v['expected_minutes'] for v in exposures[r['fixture_id']][side]}
                            for pid in teams[r[side+'_team_id']]:samples[pid].append(values.get(pid,0.))
                    ranges={pid:[min(v),max(v)] for pid,v in samples.items()}
                    p['player_exposure_ranges']=ranges
                    if len(player_rows)>=100 and any(hi-lo>1e-6 for lo,hi in ranges.values()):
                        pair,audit=fit_pair(cohort,pubs,self.players,cutoff_utc=now,minimum_games=100)
                        p['player_pair']=pair;p['player_readiness']=audit
                    else:
                        p['player_readiness']=dict(status='INSUFFICIENT_PROSPECTIVE_PLAYER_INPUTS_OR_VARIATION',
                            eligible_games=len(player_rows),minimum_games=100,exclusions=excluded)
                except (ValueError,KeyError,TypeError,OSError):
                    p['player_readiness']=dict(status='BLOCKED_PLAYER_WITNESS_OR_FIT_VALIDATION')
            if (p['league'],p['season'])!=(league,season):raise ValueError('ADAPTIVE_FIT_COHORT_REQUIRED')
            p['prepared_at_utc']=int(time.time())  # Whole bundle, including the optional later player fit.
            artifact['sha256']=digest(p);publish_json(path,artifact);return read_wrapper(path),True

    def capture(self,target,original_pin,artifact,verify_fixture,*,frozen=None,player_only=False):
        plan=self.plan();admission=self.admit(target,original_pin)
        registry=self.player_registry if player_only else self.registry
        old=next((r for r in registry.records() if r['payload']['fixture']['canonical_id']==target['fixture_id'] and
                  r['payload']['version']==plan['sha256']),None)
        if old:return old['payload'],False
        if artifact['payload']['protocol_sha256']!=plan['sha256']:raise ValueError('ADAPTIVE_MODEL_PROTOCOL')
        now=int(time.time());forecasts,blocked,cut=adaptive_models.predict(artifact,target,cutoff_utc=now)
        if any(name not in forecasts for name in ('PACE_EFFICIENCY','TEAM_ON_BOX_COHORT')):
            raise Abstain('ADAPTIVE_PRIMARY_BOX_COVERAGE_REQUIRED')
        components={name:dict(status='FORECAST_CREATED',prediction=f.summary(),intervals=prediction_intervals(f)) for name,f in forecasts.items()}
        components.update({name:dict(status='ABSTAIN',reason=reason) for name,reason in blocked.items()})
        components['PLAYER_BAYES']=dict(status='ABSTAIN',reason='SEPARATE_PROSPECTIVE_PLAYER_PAIR_REQUIRED')
        pair=artifact['payload']['player_pair']
        player_refs=[];player_source_time=0
        if player_only and pair and self.players is not None:
            try:
                pubs=[p for p in MinutesArchive(self.players/'minutes').first() if p['projection']['payload']['fixture_id']==target['fixture_id']]
                if len(pubs)!=1:raise Abstain('ONE_FRESH_PROSPECTIVE_MINUTE_PUBLICATION_REQUIRED')
                validate_witness(pubs[0],self.players)
                if pubs[0]['projection']['payload']['original_snapshot_sha256']!=original_pin:
                    raise ValueError('ADAPTIVE_PLAYER_ORIGINAL_SNAPSHOT_LINK')
                if pubs[0]['first_archived_at_utc']>now:raise ValueError('ADAPTIVE_PLAYER_MINUTES_FUTURE')
                for side in ('home','away'):
                    for player in pubs[0]['projection']['payload'][side]:
                        bounds=artifact['payload'].get('player_exposure_ranges',{}).get(player['player_id'])
                        if bounds and bounds[1]-bounds[0]<1e-6 and abs(player['expected_minutes']-bounds[0])>1e-6:
                            raise Abstain('CONSTANT_PLAYER_EXPOSURE_CANNOT_IDENTIFY_CHANGED_MINUTES')
                out=PreparedPlayerPair(pair,trusted_sha256=pair['sha256']).predict(cut,pubs[0]['projection'])
                components={}
                for name in ('TEAM_BAYES','PLAYER_BAYES'):
                    name_out='PLAYER_TEAM_CONTROL' if name=='TEAM_BAYES' else name
                    f=out[name];components[name_out]=dict(status='FORECAST_CREATED',prediction=f.summary(),intervals=prediction_intervals(f))
                player_refs=[registry.asset('minutes',pubs[0]['projection']),registry.asset('minutes-publication',pubs[0])]
                player_source_time=max(pubs[0]['first_archived_at_utc'],pubs[0]['projection']['payload']['source_available_max_utc'])
            except (ValueError,KeyError,TypeError,OSError):
                raise Abstain('ADAPTIVE_VERIFIED_PLAYER_MODEL_OR_FRESH_MINUTES_REQUIRED') from None
        elif player_only:raise Abstain('ADAPTIVE_PROSPECTIVE_PLAYER_MODEL_NOT_READY')
        if frozen is not None:components['FROZEN_ORIGINAL']=frozen
        receipt=verify_fixture(target)  # Fresh native scheduled-status recheck AFTER inference.
        generated=int(time.time())
        if not admission['admitted_at_utc']>=plan['payload']['registered_at_utc']:raise ValueError('ADAPTIVE_ADMISSION_BEFORE_PLAN')
        refs=[registry.asset('model',artifact),registry.asset('feature-cut',asdict(cut)),
              registry.asset('source',receipt),registry.asset('admission',admission),*player_refs]
        body=dict(record_type='ADAPTIVE_V2_SEPARATE_RESEARCH_NOT_ACTIVE_MODEL',version=plan['sha256'],
            fixture=dict(canonical_id=target['fixture_id'],start_ts_utc=target['fixture_start_utc'],**target),actual=None,
            original_snapshot_sha256=original_pin,model_artifact_sha256=artifact['sha256'],
            source_available_max_utc=max(receipt['ingested_at_utc'],artifact['payload']['prepared_at_utc'],player_source_time),
            prediction_generated_at_utc=generated,assets=refs,components=components,
            primary_comparison=dict(candidate=POLICY['primary'],baseline=POLICY['baseline'],
                available_box_corpus_ids=artifact['payload']['box_training_ids'],
                scope='STRATEGY_COMPARISON_SHARED_CORPUS_DIFFERENT_PARAMETERIZATIONS'),
            ablations=[['TEAM_ON_BOX_COHORT','PACE_EFFICIENCY'],['EFFICIENCY_FIXED_PACE','PACE_EFFICIENCY'],
                       ['PLAYER_TEAM_CONTROL','PLAYER_BAYES']],
            original_ledger_changed=False,calibration_status='NOT_CALIBRATED',confidence_index=None,production_enabled=False)
        body['research_stage']='PLAYER_PAIR' if player_only else 'PACE_EFFICIENCY_PAIR'
        if player_only:
            body['primary_comparison']=dict(candidate='PLAYER_BAYES',baseline='PLAYER_TEAM_CONTROL',
                identical_training_ids=pair['payload']['candidate']['training_ids'],scope='EXPLORATORY_PLAYER_ABLATION_NOT_PRIMARY')
            body['ablations']=[['PLAYER_TEAM_CONTROL','PLAYER_BAYES']]
        return registry.record(body)

    def capture_player(self,target,original_pin,artifact,verify_fixture):
        return self.capture(target,original_pin,artifact,verify_fixture,player_only=True)

    def records(self):return self.registry.records()+self.player_registry.records()

    def performance(self,label_rows):
        plan=self.plan();now=int(time.time());labels={}
        for r in label_rows:
            key=(r['league'],r['fixture_id'],r['snapshot_sha256'])
            if r['actual'] is not None and r.get('label_available_utc',now)<=now:
                if key in labels and labels[key]['actual']!=r['actual']:raise ValueError('ADAPTIVE_NATIVE_LABEL_CONFLICT')
                labels[key]=r
        admissions=[];files=list(self.root.glob('admit-*.json'))
        if len(files)>4096:raise ValueError('ADAPTIVE_ADMISSION_BUDGET')
        for f in files:
            a=read_wrapper(f)['payload'];t=a['target']
            key=digest(dict(protocol=a['protocol_sha256'],fixture=t['fixture_id'],league=t['league']))
            if f.stem!='admit-'+key or not plan['payload']['registered_at_utc']<=a['admitted_at_utc']<t['fixture_start_utc']-900:
                raise ValueError('ADAPTIVE_ADMISSION_IDENTITY_OR_CLOCK')
            admissions.append(a)
        groups={};denominators=defaultdict(int);pending=0
        for a in admissions:
            t=a['target'];key=(t['league'],t['season'])
            if a['protocol_sha256']!=plan['sha256']:raise ValueError('ADAPTIVE_ADMISSION_PLAN')
            label=labels.get((t['league'].upper(),t['fixture_id'],a['original_snapshot_sha256']))
            if label is None:pending+=1
            else:denominators[key]+=1
        for entry in self.records():
            p=entry['payload'];g=p['fixture'];label=labels.get((g['league'].upper(),g['fixture_id'],p['original_snapshot_sha256']))
            if label is None:continue
            if (label['fixture_start_utc']!=g['start_ts_utc'] or label['label_available_utc']<=g['start_ts_utc'] or
                    entry['publication']['first_archived_at_utc']>=g['start_ts_utc']-900):raise ValueError('ADAPTIVE_LABEL_OR_PUBLICATION_CLOCK')
            bucket=groups.setdefault((g['league'],g['season']),defaultdict(list))
            for name,c in p['components'].items():
                if c['status']!='FORECAST_CREATED':continue
                q=c['prediction'];bucket[name].append(dict(fixture_id=g['fixture_id'],start_utc=g['start_ts_utc'],actual=label['actual'],
                    actual_quarters=list(map(list,zip(*[label['actual_periods'][s][:4] for s in ('home','away')]))),prediction=q))
        for key in denominators:groups.setdefault(key,defaultdict(list))
        result=[]
        for key,components in groups.items():
            primary=paired_cluster_interval(components[POLICY['baseline']],components[POLICY['primary']],family_size=3)
            effect=primary.get('metrics',{}).get('team_mae',{});interval=effect.get('interval');n=primary['n'];days=primary['day_clusters']
            coverage=n/denominators[key] if denominators[key] else 0.
            gate=(n>=100 and days>=20 and coverage>=.8 and interval is not None and interval[1]<0 and
                  effect['candidate']<=(1-.02)*effect['baseline'])
            ablations={}
            for b,c in [('FROZEN_ORIGINAL','UPDATED_TEAM'),('TEAM_ON_BOX_COHORT','EFFICIENCY_FIXED_PACE'),
                        ('EFFICIENCY_FIXED_PACE','PACE_EFFICIENCY'),('PLAYER_TEAM_CONTROL','PLAYER_BAYES')]:
                ablations[b+'__'+c]=paired_cluster_interval(components.get(b,[]),components.get(c,[]),family_size=26)
            result.append(dict(league=key[0],season=key[1],matched=n,day_clusters=days,settled_admissions=denominators[key],
                primary_coverage=coverage,primary=primary,ablations=ablations,
                component_point_metrics={name:point_summary(rows) for name,rows in components.items() if rows},
                gate='PASS_REQUIRES_SEPARATE_RELEASE_REVIEW' if gate else 'NOT_PROVEN',
                evaluation_unit='SCHEDULED_ADAPTIVE_POLICY_NOT_ONE_FIXED_PARAMETER_FIT'))
        return dict(protocol_sha256=plan['sha256'],groups=result,pending_admissions=pending,
            settled_admissions=sum(denominators.values()),calibration_status='NOT_CALIBRATED',confidence_index=None,
            automatic_promotion=False,production_enabled=False)

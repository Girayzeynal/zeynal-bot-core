"""Automatic *candidate* calibration on authenticated past originals only.

This does not change quality_monitor, existing calibration plans, point scores,
or live probability fields. Future publication and disjoint native labels are
required before a candidate can pass the separate acceptance gate.
"""
import time
import numpy as np

from core.team_identity import digest
from hybrid_engine.time_policy import PREMATCH_MINIMUM_LEAD_SECONDS
from hybrid_engine.data import Abstain
from hybrid_engine.evaluation import probability_metrics

POLICY=dict(evaluation_version='EXACT_COHORT_INDEPENDENT_FIXTURES_V2',minimum_fit=100,minimum_future=100,minimum_days=20,minimum_cell=30,
    bins=10,prior_per_class=1.,minimum_brier_gain=.01,bootstrap_iterations=10000,
    seed=20261118,automatic_promotion=False)


def _cell(prob):
    p=np.asarray(prob,dtype=float)
    if p.shape!=(3,) or not np.isfinite(p).all() or np.any(p<0) or not np.isclose(p.sum(),1):
        raise ValueError('SHADOW_PROBABILITY_SIMPLEX')
    return str(int(np.argmax(p)))+':'+str(min(9,int(max(p)*10)))


def fit(audit, *, model_digest,season):
    now=int(time.time());performance=audit.get('performance') or {};rows=[]
    if audit['observed_at_utc']>now:raise ValueError('SHADOW_AUDIT_FUTURE_CLOCK')
    native={(r['fixture_id'],r['model_digest']):r for r in audit['rows']}
    for r in performance.get('forecasts',[]):
        if r['model_digest']!=model_digest or r['season']!=season or r['league']!='NBA' or r['actual'] is None:continue
        n=native.get((r['fixture_id'],model_digest),{});source=n.get('source_audit') or {};trace=n.get('calibration_inputs') or {}
        if (n.get('findings') or not trace or source.get('status')!='VERIFIED_WITH_LIMITATIONS' or
            source.get('snapshot_sha256')!=r['snapshot_sha256']):continue
        if (not 0<trace['inputs_available_max_utc']<=r['prediction_generated_at_utc']<=r['first_archived_at_utc']<r['fixture_start_utc']<r['label_available_utc']<=now or
            trace['model_fit_cutoff_utc']>r['prediction_generated_at_utc'] or r['fixture_id'] in trace['model_training_ids']):
            raise ValueError('SHADOW_NATIVE_PREMATCH_AND_TRAINING_CLOCK')
        if r['winner'] is None:continue
        _cell(r['winner']);rows.append(r)
    # No extra independent observations from operational variants.
    first={}
    for r in sorted(rows,key=lambda r:(r['prediction_generated_at_utc'],r['snapshot_sha256'])):first.setdefault(r['fixture_id'],r)
    rows=list(first.values())
    if len(rows)<POLICY['minimum_fit']:raise Abstain('SHADOW_HUNDRED_NATIVE_SETTLED_ORIGINALS_REQUIRED')
    bins={}
    for r in rows:
        key=_cell(r['winner']);counts=bins.setdefault(key,np.ones(3));a=r['actual']
        counts[0 if a[0]>a[1] else 1 if a[0]==a[1] else 2]+=1
    body=dict(format='AUTOMATIC_NATIVE_WINNER_SHADOW_V2',model_digest=model_digest,season=season,league='NBA',
        policy=POLICY,fit_at_utc=now,training_ids=sorted(first),training_snapshot_sha256s=sorted(r['snapshot_sha256'] for r in rows),
        label_available_max_utc=max(r['label_available_utc'] for r in rows),
        bins={k:dict(n=int(v.sum()-3),probabilities=(v/v.sum()).tolist()) for k,v in bins.items()},
        originals_changed=False,production_enabled=False)
    return dict(payload=body,sha256=digest(body))


def apply(candidate, row, *, generated_at_utc):
    p=candidate['payload']
    if digest(p)!=candidate['sha256'] or p['policy']!=POLICY or p['production_enabled'] is not False:raise ValueError('SHADOW_CANDIDATE_PIN')
    if (row['league'],row['season'],row['model_digest'])!=('NBA',p['season'],p['model_digest']):raise Abstain('SHADOW_EXACT_FIT_SCOPE_REQUIRED')
    if (row['fixture_id'] in p['training_ids'] or not p['label_available_max_utc']<=p['fit_at_utc']<=generated_at_utc<row['fixture_start_utc']-PREMATCH_MINIMUM_LEAD_SECONDS or
        generated_at_utc>int(time.time())):raise Abstain('SHADOW_DISJOINT_FUTURE_PUBLICATION_REQUIRED')
    key=_cell(row['winner']);cell=p['bins'].get(key)
    if cell is None or cell['n']<POLICY['minimum_cell']:raise Abstain('SHADOW_PROBABILITY_CELL_INSUFFICIENT')
    return dict(raw=list(row['winner']),candidate=cell['probabilities'],candidate_sha256=candidate['sha256'],
        original_snapshot_sha256=row['snapshot_sha256'],model_digest=row['model_digest'],season=row['season'],
        fixture_id=row['fixture_id'],fixture_start_utc=row['fixture_start_utc'],prediction_generated_at_utc=generated_at_utc,
        training_ids=p['training_ids'],fit_at_utc=p['fit_at_utc'],confidence_index=None,status='SHADOW_NOT_RELEASED')


def evaluate(publications,labels, *, registered_at_utc):
    """Never pool fitted versions or count snapshot variants as extra matches."""
    groups={};seen=set();label_keys=set()
    for r in labels:
        if r['actual'] is None:continue
        key=(r.get('league'),r['fixture_id'],r['snapshot_sha256'],r['model_digest'],r['season'])
        if key in label_keys:raise ValueError('SHADOW_EXACT_NATIVE_LABEL_REQUIRED')
        label_keys.add(key)
    for item in publications:
        cohort=(item['season'],item['model_digest'])
        independent=(*cohort,item['fixture_id'])
        if independent in seen:raise ValueError('SHADOW_DUPLICATE_INDEPENDENT_FIXTURE_DUPLICATE_FUTURE_PUBLICATION')
        seen.add(independent);groups.setdefault(cohort,[]).append(item)
    if len(groups)<=1:return _evaluate_one(publications,labels,registered_at_utc=registered_at_utc)
    reports=[]
    for (season,md),rows in sorted(groups.items()):
        selected=[r for r in labels if (r['season'],r['model_digest'])==(season,md)]
        reports.append(dict(season=season,model_digest=md,**_evaluate_one(rows,selected,registered_at_utc=registered_at_utc)))
    return dict(status='ABSTAIN_SEPARATE_CALIBRATION_COHORTS_REQUIRED',
        n=None,unique_published_fixtures=len({p['fixture_id'] for p in publications}),
        matched_forecasts_across_cohorts=sum(g['n'] for g in reports),
        groups=reports,raw=None,candidate=None,paired_interval=None,
        automatic_promotion=False,production_enabled=False)


def _evaluate_one(publications,labels, *, registered_at_utc):
    now=int(time.time());matched=[];seen=set()
    if type(registered_at_utc) is not int or not 0<registered_at_utc<=now:raise ValueError('SHADOW_ACTUAL_REGISTERED_CLOCK_REQUIRED')
    for item in publications:
        key=(item['fixture_id'],item['original_snapshot_sha256'],item['model_digest'],item['season'])
        if key in seen:raise ValueError('SHADOW_DUPLICATE_FUTURE_PUBLICATION')
        seen.add(key)
        if not registered_at_utc<=item['fit_at_utc']<=item['prediction_generated_at_utc']<=now or item['prediction_generated_at_utc']>=item['fixture_start_utc']-PREMATCH_MINIMUM_LEAD_SECONDS:
            raise ValueError('SHADOW_REGISTERED_PREMATCH_PUBLICATION_REQUIRED')
        candidates=[r for r in labels if r.get('league')=='NBA' and (r['fixture_id'],r['snapshot_sha256'],r['model_digest'],r['season'])==key and r['actual'] is not None]
        if not candidates:continue
        if len(candidates)!=1:raise ValueError('SHADOW_EXACT_NATIVE_LABEL_REQUIRED')
        r=candidates[0]
        if r['fixture_start_utc']!=item['fixture_start_utc'] or not r['fixture_start_utc']<r['label_available_utc']<=now or r['fixture_id'] in item['training_ids']:
            raise ValueError('SHADOW_LABEL_IDENTITY_OR_AVAILABILITY')
        if (r.get('winner') is None or np.asarray(r['winner']).shape!=(3,) or
            not np.allclose(r['winner'],item['raw'],rtol=0,atol=1e-12)):
            raise ValueError('SHADOW_ORIGINAL_PROBABILITY_CONFLICT')
        a=r['actual']
        if len(a)!=2 or any(type(v) not in (int,float) or not np.isfinite(v) or v<0 for v in a):
            raise ValueError('SHADOW_FINITE_NATIVE_TEAM_SCORES_REQUIRED')
        y=0 if a[0]>a[1] else 1 if a[0]==a[1] else 2
        matched.append(dict(item=item,outcome=y,day=(r['fixture_start_utc']+10800)//86400))
    days=sorted({r['day'] for r in matched});out=dict(n=len(matched),days=len(days),status='ABSTAIN_INSUFFICIENT_FUTURE_EVIDENCE',
        raw=None,candidate=None,paired_interval=None,automatic_promotion=False,production_enabled=False)
    if not matched:return out
    raw=np.asarray([r['item']['raw'] for r in matched]);candidate=np.asarray([r['item']['candidate'] for r in matched]);y=np.asarray([r['outcome'] for r in matched])
    out.update(raw=probability_metrics(raw,y),candidate=probability_metrics(candidate,y))
    if len(matched)<100 or len(days)<20:return out
    truth=np.eye(3)[y]
    losses=np.column_stack((np.sum((candidate-truth)**2,axis=1)-np.sum((raw-truth)**2,axis=1),
        -np.log(np.clip(candidate[np.arange(len(y)),y],1e-15,1))+np.log(np.clip(raw[np.arange(len(y)),y],1e-15,1))))
    groups=[losses[[r['day']==d for r in matched]] for d in days];totals=np.asarray([g.sum(axis=0) for g in groups]);counts=np.asarray([len(g) for g in groups])
    rng=np.random.default_rng(POLICY['seed']);values=[]
    for _ in range(20):
        w=rng.multinomial(len(days),np.full(len(days),1/len(days)),size=500)
        values.append((w@totals)/(w@counts)[:,None])
    # Two loss endpoints, Bonferroni simultaneous 95% family coverage.
    bounds=np.quantile(np.concatenate(values),[.0125,.9875],axis=0)
    out['paired_interval']=dict(brier=bounds[:,0].tolist(),log_loss=bounds[:,1].tolist(),method='ISTANBUL_DAY_CLUSTER_BOOTSTRAP',iterations=10000)
    passed=losses[:,0].mean()<=-.01 and bounds[1,0]<0 and bounds[1,1]<=0
    out['status']='CANDIDATE_FOR_MANUAL_REVIEW' if passed else 'REJECTED_NO_VERIFIED_IMPROVEMENT'
    return out

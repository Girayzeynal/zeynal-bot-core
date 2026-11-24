"""League/season-specific empirical OT blocks, isolated from live betting.

Only completed native, time-available OT sequences enter the fit. The entire
historical OT sequence is sampled conditional on a regulation tie, preserving
paired scores and multiple-OT dependence. This is a research baseline, not an
opponent-adjusted/validated OT model or authority to admit a bookmaker rule.
No active forecast, experiment, score archive or decision integration changes.
"""
import time

import numpy as np
from core.team_identity import digest
from hybrid_engine.adaptive_models import checked_rows
from hybrid_engine.data import STRICT,Abstain,available_at
from hybrid_engine.time_policy import PREMATCH_MINIMUM_LEAD_SECONDS

VERSION='LEAGUE_NATIVE_COMPLETE_OVERTIME_BLOCK_RESEARCH_V1'
POLICY=dict(minimum_ot_games=6,maximum_overtimes=6,maximum_games=4096,
    maximum_parameter_age_seconds=24*3600,production_enabled=False)
DURATION={'NBA':48,'EUROLEAGUE':40,'EUROCUP':40}


def _blocks(row):
    q=row['periods'];h=q['home'];a=q['away']
    if (len(h)!=len(a) or not 4<=len(h)<=4+POLICY['maximum_overtimes'] or
            any(type(v) is not int or v<0 or v>100 for v in h+a) or
            row['final_scores']!=[sum(h),sum(a)]):
        raise ValueError('OVERTIME_NATIVE_PERIOD_FINAL_CONFLICT')
    if len(h)==4:return None
    if sum(h[:4])!=sum(a[:4]) or sum(h)==sum(a):
        raise ValueError('OVERTIME_REQUIRES_TIED_REGULATION_AND_COMPLETED_FINAL')
    if any(sum(h[:i])!=sum(a[:i]) for i in range(5,len(h))):
        raise ValueError('OVERTIME_CANNOT_CONTINUE_AFTER_NON_TIED_PERIOD')
    return [[h[i],a[i]] for i in range(4,len(h))]


def fit(cohort,*,cutoff_utc):
    if type(cutoff_utc) is not int or not 0<cutoff_utc<=int(time.time()):
        raise ValueError('OVERTIME_ACTUAL_PAST_CUTOFF_REQUIRED')
    if not isinstance(cohort,list) or len(cohort)>POLICY['maximum_games']:
        raise ValueError('OVERTIME_COHORT_BUDGET')
    eligible=[vs for vs in cohort if any(r['fixture_start_utc']<available_at(r,STRICT)<=cutoff_utc for r in vs)]
    if not eligible:raise Abstain('OVERTIME_INSUFFICIENT_NATIVE_PAST_GAMES')
    rows=checked_rows(eligible,cutoff_utc)
    league=rows[0]['league'].upper();season=rows[0]['season']
    if league not in DURATION:raise ValueError('OVERTIME_SUPPORTED_LEAGUE_REQUIRED')
    training=[]
    for row in rows:
        blocks=_blocks(row)
        if blocks is not None:
            training.append(dict(fixture_id=row['fixture_id'],fixture_start_utc=row['fixture_start_utc'],
                label_available_utc=available_at(row,STRICT),source_catalog_sha256=row['source_catalog_sha256'],
                steps=blocks))
    if len(training)<POLICY['minimum_ot_games']:raise Abstain('OVERTIME_SIX_NATIVE_OT_GAMES_REQUIRED')
    payload=dict(format=VERSION,policy=dict(POLICY),league=league,season=season,
        regulation_minutes=DURATION[league],overtime_minutes=5,cutoff_utc=cutoff_utc,
        training=training,training_ids=[r['fixture_id'] for r in rows],
        training_available_max=max(available_at(r,STRICT) for r in rows),
        conditional_training_games=len(training),calibration_status='NOT_CALIBRATED',
        opponent_adjusted=False,live_market_admission=False,production_enabled=False)
    return dict(payload=payload,sha256=digest(payload))


def simulate(wrapper,regulation_paths,target,*,asof_utc,seed=20261124,method='MC'):
    p=wrapper['payload'];now=int(time.time())
    if digest(p)!=wrapper['sha256'] or p['format']!=VERSION or p['policy']!=POLICY:
        raise ValueError('OVERTIME_MODEL_PIN')
    if (p['league']!=target['league'].upper() or p['season']!=target['season'] or
            target['fixture_id'] in p['training_ids']):
        raise ValueError('OVERTIME_TARGET_LEAGUE_SEASON_OR_TRAINING_OVERLAP')
    if (type(asof_utc) is not int or not p['training_available_max']<=p['cutoff_utc']<=asof_utc<=now or
            asof_utc-p['cutoff_utc']>POLICY['maximum_parameter_age_seconds'] or
            asof_utc>=target['fixture_start_utc']-PREMATCH_MINIMUM_LEAD_SECONDS):
        raise Abstain('OVERTIME_PARAMETER_AGE_OR_PREMATCH_WINDOW')
    paths=np.asarray(regulation_paths)
    if (paths.ndim!=3 or paths.shape[1:]!=(4,2) or not 1<=len(paths)<=32768 or
            not np.issubdtype(paths.dtype,np.integer) or np.any(paths<0) or np.any(paths>1000) or
            type(seed) is not int or seed<0):raise ValueError('OVERTIME_VALID_REGULATION_PATHS_REQUIRED')
    reg=paths.sum(axis=1);ties=np.flatnonzero(reg[:,0]==reg[:,1]);rng=np.random.default_rng(seed)
    if method=='MC':u=rng.random(len(ties))
    elif method=='RQMC_HALTON':
        # An independent conditional dimension, not the base-2 dimension
        # used by the regulation Gaussian sampler. No low-error claim.
        index=np.arange(1,len(ties)+1,dtype=np.int64);u=np.zeros(len(ties));factor=1.
        while np.any(index):
            factor/=23;u+=factor*(index%23);index//=23
        u=(u+rng.random())%1
    else:raise ValueError('OVERTIME_MC_OR_RQMC_REQUIRED')
    training=p['training'];steps=np.zeros((len(paths),POLICY['maximum_overtimes'],2),dtype=np.int32)
    for sample,k in zip(ties,np.minimum((u*len(training)).astype(int),len(training)-1)):
        blocks=np.asarray(training[int(k)]['steps'],dtype=np.int32)
        steps[sample,:len(blocks)]=blocks
    ot=steps.sum(axis=1)
    if np.any((reg+ot)[:,0]==(reg+ot)[:,1]):raise ValueError('OVERTIME_FINAL_PATHS_STILL_TIED')
    return dict(overtime_paths=ot,overtime_steps=steps,metadata=dict(format=VERSION,
        model_sha256=wrapper['sha256'],method=method,seed=seed,conditional_tie_paths=len(ties),
        regulation_samples_unchanged=True,conditional_training_games=len(training),
        opponent_adjusted=False,calibrated=False,live_market_admission=False,production_enabled=False))


def walk_forward(cohort,*,asof_utc):
    """Describe first eligible disjoint OT errors; never backdate source clocks."""
    from hybrid_engine.evaluation import point_metrics,probability_metrics
    rows=checked_rows(cohort,asof_utc);predictions=[];actuals=[];probs=[];labels=[];blocked={}
    for row in rows:
        steps=_blocks(row)
        if steps is None:continue
        try:model=fit(cohort,cutoff_utc=row['fixture_start_utc']-PREMATCH_MINIMUM_LEAD_SECONDS-1)
        except Abstain as exc:
            key=str(exc);blocked[key]=blocked.get(key,0)+1;continue
        training=[np.sum(r['steps'],axis=0) for r in model['payload']['training']]
        expected=np.mean(training,axis=0);actual=np.sum(steps,axis=0)
        home=float(np.mean([r[0]>r[1] for r in training]))
        predictions.append(expected);actuals.append(actual);probs.append([home,0.,1-home])
        labels.append(0 if actual[0]>actual[1] else 2)
    n=len(predictions)
    return dict(status='DESCRIPTIVE_DISJOINT_OT_RESEARCH_ONLY' if n else 'ABSTAIN_NO_TIME_VALID_OT_PAIRS',
        n=n,blocked=blocked,conditional_ot_team_scores=None if not n else point_metrics(np.asarray(predictions)-actuals),
        conditional_ot_winner=None if not n else probability_metrics(probs,labels),
        baseline_fair_ot_winner=None if not n else probability_metrics([[.5,0.,.5]]*n,labels),
        regulation_forecasts_changed=False,calibration_fit=False,automatic_promotion=False,
        live_market_admission=False,production_enabled=False)

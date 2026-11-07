"""Gated experimental ridge heads. No production coefficients are modified."""
from copy import deepcopy
import math
from statistics import stdev
from statistics import NormalDist
import time
import re
import numpy as np

from shadow_features import FEATURES,replay_features
from prospective_error_audit import period_final
from prediction_inputs import digest

MODEL='FAZ31_RIDGE_V1'
MIN_TRAIN,MIN_VALIDATION,MIN_TEST=60,20,20


def validate_example(example):
    f=replay_features(example['features']);label=example['label']
    if digest(label)!=example['label_sha256']:raise ValueError('label digest mismatch')
    p=period_final(label['summary'],label['observed_utc']);event=p['event'];target=f['target']
    if (f['status']!='READY' or f['available_utc']>f['cutoff_utc']
        or not f['cutoff_utc']<target['start_ts_utc']<label['observed_utc']<=int(time.time())
        or any(event[k]!=target[k] for k in ('provider_fixture_id','start_ts_utc','home_team_id','away_team_id'))):
        raise ValueError('training feature/label identity or availability mismatch')
    if min(p['regulation_home'],p['regulation_away'])<=0:raise ValueError('quarter share target unavailable')
    return f,p


def _fit(x,y,penalty):
    x=np.asarray(x,dtype=float);y=np.asarray(y,dtype=float)
    mean=x.mean(axis=0);scale=x.std(axis=0);scale[scale==0]=1
    z=np.column_stack([np.ones(len(x)),(x-mean)/scale])
    ridge=np.eye(z.shape[1])*penalty;ridge[0,0]=0
    coef=np.linalg.solve(z.T@z+ridge,z.T@y)
    return dict(mean=mean.tolist(),scale=scale.tolist(),coefficients=coef.tolist())


def _heads(head,x):
    return (np.r_[1,(np.asarray(x)-head['mean'])/head['scale']]@np.asarray(head['coefficients'])).tolist()


def _score(head,x):
    total,margin=_heads(head,x)[:2]
    total=max(0,total);margin=max(-total,min(total,margin))
    return (total+margin)/2,(total-margin)/2


def train(examples,source_version,split_boundaries=None,research=False):
    if not isinstance(source_version,str) or not re.fullmatch('[0-9a-f]{40}',source_version):raise ValueError('exact training source SHA required')
    examples=list(examples)
    if len(examples)<MIN_TRAIN+MIN_VALIDATION+MIN_TEST:
        return dict(status='NOT_TRAINED',reason='MIN_100_TIMESTAMPED_EXAMPLES',examples=len(examples),
                    required=dict(train=MIN_TRAIN,validation=MIN_VALIDATION,test=MIN_TEST))
    validator=validate_example
    if research:
        from historical_research import validate_research_example
        validator=validate_research_example
    validated=[(e,*validator(e)) for e in examples]
    validated.sort(key=lambda v:(v[1]['cutoff_utc'],v[1]['target']['provider_fixture_id']))
    ids=[v[1]['target']['provider_fixture_id'] for v in validated]
    if len(set(ids))!=len(ids):raise ValueError('duplicate training fixture')
    n=len(validated)
    if split_boundaries is None:a,b=int(n*.6),int(n*.8)
    else:
        a,b=split_boundaries
        if type(a) is not int or type(b) is not int or not 0<a<b<n:raise ValueError('invalid chronological boundaries')
    training,validation,test=validated[:a],validated[a:b],validated[b:]
    # Purge labels unavailable at the next period's first prediction. Ties in
    # prediction time cannot straddle split boundaries.
    validation_start=validation[0][1]['cutoff_utc'];test_start=test[0][1]['cutoff_utc']
    training=[v for v in training if v[1]['cutoff_utc']<validation_start and v[0]['label']['observed_utc']<validation_start]
    validation=[v for v in validation if v[1]['cutoff_utc']<test_start and v[0]['label']['observed_utc']<test_start]
    if any(len(group)<minimum for group,minimum in ((training,MIN_TRAIN),(validation,MIN_VALIDATION),(test,MIN_TEST))):
        return dict(status='NOT_TRAINED',reason='INSUFFICIENT_AFTER_CHRONOLOGICAL_PURGE',
                    split_counts=[len(training),len(validation),len(test)])
    def x(v):return [v[1]['values'][k] for k in FEATURES]
    def y(v):
        p=v[2];h,a=p['regulation_home'],p['regulation_away']
        return [h+a,h-a]+[q/h for q in p['periods']['home'][:4]]+[q/a for q in p['periods']['away'][:4]]
    candidates=[]
    for penalty in (1.,10.,100.):
        head=_fit([x(v) for v in training],[y(v) for v in training],penalty)
        errors=[]
        for v in validation:
            h,a=_score(head,x(v));ph,pa=v[2]['regulation_home'],v[2]['regulation_away']
            errors.append((abs(h-ph)+abs(a-pa))/2+.5*abs((h-a)-(ph-pa)))
        candidates.append((sum(errors)/len(errors),penalty,head))
    loss,penalty,head=min(candidates,key=lambda v:(v[0],v[1]))
    residuals=[]
    for v in validation:
        h,a=_score(head,x(v));residuals.append((v[2]['regulation_home']-v[2]['regulation_away'])-(h-a))
    sigma=stdev(residuals)
    def metrics(group):
        errors=[];margins=[];totals=[]
        for v in group:
            h,a=_score(head,x(v));ph,pa=v[2]['regulation_home'],v[2]['regulation_away']
            errors.extend([h-ph,a-pa]);margins.append((h-a)-(ph-pa));totals.append(h+a-ph-pa)
        return dict(games=len(group),score_mae=sum(abs(e) for e in errors)/len(errors),
                    score_rmse=math.sqrt(sum(e*e for e in errors)/len(errors)),
                    total_mae=sum(abs(e) for e in totals)/len(totals),total_rmse=math.sqrt(sum(e*e for e in totals)/len(totals)),
                    margin_mae=sum(abs(e) for e in margins)/len(margins),
                    margin_rmse=math.sqrt(sum(e*e for e in margins)/len(margins)))
    from shadow_probability import probability_metrics
    def probability_diagnostics(group):
        if sigma<=0:return probability_metrics([],[])
        probabilities=[];outcomes=[]
        for v in group:
            h,a=_score(head,x(v));normal=NormalDist(h-a,sigma)
            low=normal.cdf(-.5);high=normal.cdf(.5)
            probabilities.append(dict(home=1-high,away=low,tie=high-low))
            actual=v[2]['regulation_home']-v[2]['regulation_away']
            outcomes.append('home' if actual>0 else 'away' if actual<0 else 'tie')
        return probability_metrics(probabilities,outcomes)
    now=int(time.time())
    payload=dict(model_id=MODEL,source_version=source_version,scope='REGULATION_ONLY',trained_at_utc=now,usable_after_utc=now,
        head=head,penalty=penalty,selection='validation_score_MAE_plus_half_margin_MAE',
        validation_margin_residual_std=sigma,feature_names=list(FEATURES),
        dataset_coverage=dict(distinct_teams=len({v[1]['target'][side+'_team_id'] for v in validated for side in ('home','away')}),
            warning='counts are operational gates, not proof of statistical adequacy'),
        split_ids={name:[v[1]['target']['provider_fixture_id'] for v in group] for name,group in (('train',training),('validation',validation),('test',test))},
        last_training_label_utc=max(v[0]['label']['observed_utc'] for v in training),
        last_validation_label_utc=max(v[0]['label']['observed_utc'] for v in validation),
        validation_metrics=metrics(validation),untouched_test_metrics=metrics(test),
        validation_probability_diagnostics=probability_diagnostics(validation),untouched_test_probability_diagnostics=probability_diagnostics(test),
        dataset_digest=digest(examples),calibration_status='NOT_ESTABLISHED',usage='RETROSPECTIVE_RESEARCH_ONLY' if research else 'EXPERIMENTAL_OFFLINE_NOT_PROMOTED',research_only=research)
    return dict(status='TRAINED_EXPERIMENTAL',artifact=dict(payload=payload,sha256=digest(payload)))


def predict(artifact,features):
    p=artifact['payload'];f=replay_features(features)
    if p.get('research_only') is True:raise ValueError('research artifact cannot be used as a prospective model')
    if digest(p)!=artifact['sha256'] or p['model_id']!=MODEL:raise ValueError('invalid model artifact')
    cutoff=f['cutoff_utc']
    if (f['status']!='READY' or not 0<p['trained_at_utc']<=p['usable_after_utc']<cutoff<=int(time.time())
        or not p['last_training_label_utc']<=p['trained_at_utc'] or not p['last_validation_label_utc']<=p['trained_at_utc']):
        raise ValueError('trained artifact or features unavailable at cutoff')
    x=[f['values'][k] for k in FEATURES];home,away=_score(p['head'],x)
    home,away=round(home,2),round(away,2)
    raw=_heads(p['head'],x)[2:];quarters={};missing=[]
    for side,value,weights in (('home',home,raw[:4]),('away',away,raw[4:])):
        weights=[max(0,w) for w in weights]
        if sum(weights)<=0:
            quarters[side]=None;missing.append(side+':ZERO_LEARNED_QUARTER_MASS');continue
        shares=[w/sum(weights) for w in weights];cents=int(round(value*100))
        pieces=[int(cents*w) for w in shares]
        order=sorted(range(4),key=lambda i:cents*shares[i]-pieces[i],reverse=True)
        for i in order[:cents-sum(pieces)]:pieces[i]+=1
        quarters[side]=[v/100 for v in pieces]
    sigma=p['validation_margin_residual_std'];probability=None
    if math.isfinite(sigma) and sigma>0:
        normal=NormalDist(home-away,sigma)
        away_prob=normal.cdf(-.5);tie_prob=normal.cdf(.5)-away_prob
        probability=dict(home=1-normal.cdf(.5),away=away_prob,tie=tie_prob)
    else:missing.append('NONZERO_VALIDATION_MARGIN_VARIANCE')
    return dict(model_id=MODEL,scope='REGULATION_ONLY',feature_sha256=features['sha256'],
        artifact_sha256=artifact['sha256'],expected_home=home,expected_away=away,
        expected_total=round(home+away,2),expected_margin=round(home-away,2),quarters=quarters,
        probabilities=probability,probability_model='discretized_normal_margin_validation_residual_std',
        calibration_status='NOT_ESTABLISHED',missing=missing,
        coefficients_promoted=False)


def walk_forward(examples,source_version,research=False):
    examples=list(examples)
    if len(examples)<100:return dict(status='INSUFFICIENT_DATA',folds=[],models_promoted=False)
    ordered=sorted(examples,key=lambda e:(e['features']['payload']['cutoff_utc'],e['features']['payload']['target']['provider_fixture_id']))
    folds=[]
    for end in range(100,len(ordered)+1,20):
        result=train(ordered[:end],source_version,split_boundaries=(end-40,end-20),research=research)
        if result['status']!='TRAINED_EXPERIMENTAL':
            folds.append(dict(status=result['status'],reason=result['reason']));continue
        p=result['artifact']['payload']
        folds.append(dict(status='OFFLINE_HOLDOUT_ONLY',split_ids=p['split_ids'],
            coefficient_sha256=digest(p['head']),test_metrics=p['untouched_test_metrics'],
            test_probability_metrics=p['untouched_test_probability_diagnostics']))
    return dict(status='OFFLINE_WALK_FORWARD',folds=folds,models_promoted=False,
                production_coefficients_changed=False,real_prospective_accuracy=False)

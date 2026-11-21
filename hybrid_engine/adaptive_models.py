"""Separate scheduled research fits; active/pinned predictors are not changed.

Possessions are BOX ESTIMATES, not measured possession-boundary/PBP counts.
The fixed-pace ablation changes only the possession-count law.
"""
from copy import deepcopy
from dataclasses import replace
import time

import numpy as np

from core.team_identity import digest
from hybrid_engine.availability import effective_box_time
from hybrid_engine.boxes import checked_stats
from hybrid_engine.data import STRICT,Abstain,available_at,feature_cut,regulation
from hybrid_engine.distributions import Budget,Forecast,quarter_weights
from hybrid_engine.models import HierarchicalStrength
from hybrid_engine.player_shadow import _load_hierarchy
from hybrid_engine.possession import PossessionLaw,_aggregate,_quarter_rate

VERSION='SCHEDULED_TEAM_BOX_EFFICIENCY_V2'
REFRESH_SECONDS=6*3600
MINIMUM_TRAIN=30


def checked_rows(cohort,cutoff):
    if type(cutoff) is not int or not 0<cutoff<=int(time.time()):raise ValueError('ADAPTIVE_PAST_CUTOFF_REQUIRED')
    rows=[]
    for versions in cohort:
        eligible=[r for r in versions if r['fixture_start_utc']<available_at(r,STRICT)<=cutoff and regulation(r) is not None]
        if eligible:
            row=deepcopy(max(eligible,key=lambda r:(available_at(r,STRICT),r['source_catalog_sha256'])))
            if row.get('box') and effective_box_time(row['box'])>cutoff:
                row.pop('box',None);row.pop('box_versions',None)
            # Scoring-rate fits need team totals, not historical actual player
            # minutes. Keep native player witnesses in the independent input
            # archive; do not duplicate them into every scheduled model.
            if row.get('box'):row['box'].pop('players',None)
            row.pop('box_versions',None)
            rows.append(row)
    if len({r['fixture_id'] for r in rows})!=len(rows) or len({(r['league'],r['season']) for r in rows})!=1:
        raise ValueError('ADAPTIVE_UNIQUE_SINGLE_COHORT_REQUIRED')
    return sorted(rows,key=lambda r:(r['fixture_start_utc'],r['fixture_id']))


def box_rows(rows,cutoff):
    boxed=[]
    for row in rows:
        b=row.get('box')
        if not b or not b.get('regulation_eligible') or any(len(row['periods'][s])!=4 for s in ('home','away')):continue
        if effective_box_time(b)>cutoff:continue
        if any(b[k]!=row[k] for k in ('league','season','fixture_id','fixture_start_utc','home_team_id','away_team_id')):
            raise ValueError('ADAPTIVE_BOX_IDENTITY')
        for j,s in enumerate(('home','away')):
            stats=checked_stats(b['teams'][s])
            if stats!=b['teams'][s] or stats['points']!=regulation(row)[j]:raise ValueError('ADAPTIVE_BOX_ARITHMETIC')
        boxed.append(row)
    return boxed


def prepare(cohort,*,cutoff_utc):
    rows=checked_rows(cohort,cutoff_utc)
    if len(rows)<MINIMUM_TRAIN:raise Abstain('ADAPTIVE_THIRTY_NATIVE_TRAINING_GAMES_REQUIRED')
    boxed=box_rows(rows,cutoff_utc)
    if len(boxed)<MINIMUM_TRAIN:raise Abstain('ADAPTIVE_THIRTY_NATIVE_BOX_GAMES_REQUIRED')
    full=HierarchicalStrength().fit(rows,cutoff_utc=cutoff_utc,mode=STRICT)
    common=None
    if len(boxed)>=MINIMUM_TRAIN:common=HierarchicalStrength().fit(boxed,cutoff_utc=cutoff_utc,mode=STRICT)
    counts=[float(np.mean([r['box']['teams'][s]['possessions_estimate'] for s in ('home','away')])) for r in boxed]
    body=dict(format=VERSION,league=rows[0]['league'],season=rows[0]['season'],prepared_at_utc=int(time.time()),
        cutoff_utc=cutoff_utc,schedule_slot=cutoff_utc//REFRESH_SECONDS,refresh_seconds=REFRESH_SECONDS,
        team=full.artifact(),box_team=None if common is None else common.artifact(),training_rows=rows,
        training_ids=full.training_ids,box_training_ids=sorted(r['fixture_id'] for r in boxed),
        fixed_pace_mean=None if not counts else float(np.mean(counts)),fixed_pace_std=None if not counts else float(np.std(counts)),
        pace_definition='FGA_PLUS_0.44FTA_MINUS_ORB_PLUS_TOTAL_TOV_ESTIMATE_NOT_MEASURED_PBP',
        calibration_status='NOT_CALIBRATED',confidence_index=None,production_enabled=False)
    return dict(payload=body,sha256=digest(body))


def hierarchy(artifact):
    # The existing bounded decoder is NBA-scoped. Other leagues are explicitly
    # reconstructed from parameters fitted by the same unchanged class.
    if artifact['identity'][0]=='NBA':return _load_hierarchy(artifact)
    a=artifact;n=len(a['teams']);size=2+2*n
    if a['players'] or n>40 or a['mode']!=STRICT or a['identity'][0] not in ('EuroLeague','EuroCup'):
        raise ValueError('ADAPTIVE_TEAM_ARTIFACT_SCOPE')
    m=HierarchicalStrength();m.identity=tuple(a['identity']);m.mode=STRICT;m.cutoff=a['cutoff_utc']
    m.teams=a['teams'];m.players=[];m.team_index={t:i for i,t in enumerate(m.teams)};m.player_index={};m.duration=40
    m.coefficients=np.asarray(a['coefficients']);m.covariance=np.asarray(a['covariance'])
    if (m.coefficients.shape!=(size,) or m.covariance.shape!=(size,size) or not np.isfinite(m.covariance).all() or
            not np.isfinite(m.coefficients).all() or not np.allclose(m.covariance,m.covariance.T,rtol=0,atol=1e-8) or
            not 0<float(a['noise_variance'])<10000):
        raise ValueError('ADAPTIVE_TEAM_ARTIFACT_PARAMETERS')
    try:np.linalg.cholesky(m.covariance)
    except np.linalg.LinAlgError as exc:raise ValueError('ADAPTIVE_TEAM_ARTIFACT_NOT_POSITIVE') from exc
    m.noise_variance=a['noise_variance'];m.training_ids=a['training_ids'];m.artifact_digest=digest(a);m.fitted=True
    return m


def predict(wrapper,target,*,cutoff_utc):
    p=wrapper['payload']
    if digest(p)!=wrapper['sha256'] or p['format']!=VERSION or p['production_enabled'] is not False:
        raise ValueError('ADAPTIVE_MODEL_PIN')
    if not p['cutoff_utc']<=p['prepared_at_utc']<=cutoff_utc<=int(time.time())<target['fixture_start_utc']-900:
        raise Abstain('ADAPTIVE_MODEL_OR_PREMATCH_CLOCK')
    if target['fixture_id'] in p['training_ids'] or (target['league'],target['season'])!=(p['league'],p['season']):
        raise ValueError('ADAPTIVE_TARGET_TRAINING_OR_COHORT')
    cut=replace(feature_cut(([r] for r in p['training_rows']),target,mode=STRICT),cutoff_utc=cutoff_utc)
    forecasts={'UPDATED_TEAM':hierarchy(p['team']).predict(cut,method='RQMC_HALTON',bounded_workspace=True)}
    blocked={}
    if p['box_team'] is None:
        blocked.update({name:'ADAPTIVE_THIRTY_NATIVE_BOX_GAMES_REQUIRED' for name in
                        ('TEAM_ON_BOX_COHORT','EFFICIENCY_FIXED_PACE','PACE_EFFICIENCY')})
        return forecasts,blocked,cut
    boxed=box_rows(p['training_rows'],p['cutoff_utc'])
    common=replace(feature_cut(([r] for r in boxed),target,mode=STRICT),cutoff_utc=cutoff_utc)
    entries={s:common.features[s]['boxes'] for s in ('home','away')}
    if min(map(len,entries.values()))<6:raise Abstain('ADAPTIVE_SIX_BOX_GAMES_PER_TARGET_TEAM_REQUIRED')
    if any(cutoff_utc-max(r['fixture_start_utc'] for r,b,own,other in values)>14*86400 for values in entries.values()):
        raise Abstain('ADAPTIVE_TARGET_TEAM_BOX_HISTORY_STALE')
    forecasts['TEAM_ON_BOX_COHORT']=hierarchy(p['box_team']).predict(common,method='RQMC_HALTON',bounded_workspace=True)
    home=[(b,own,other) for r,b,own,other in entries['home']]
    away=[(b,own,other) for r,b,own,other in entries['away']]
    rates=[_aggregate(home+[(b,other,own) for b,own,other in away]),
           _aggregate(away+[(b,other,own) for b,own,other in home])]
    weights=quarter_weights(common);ratios=4*weights/weights.sum(axis=0)
    quarters=[[_quarter_rate(rate,ratios[q,s]) for s,rate in enumerate(rates)] for q in range(4)]
    unique={r['fixture_id']:float(np.mean([b['teams'][s]['possessions_estimate'] for s in ('home','away')]))
            for values in entries.values() for r,b,own,other in values}
    for name,mean,std in [('EFFICIENCY_FIXED_PACE',p['fixed_pace_mean'],p['fixed_pace_std']),
                          ('PACE_EFFICIENCY',float(np.mean(list(unique.values()))),float(np.std(list(unique.values()))))]:
        law=PossessionLaw(quarters,mean,std,Budget(seconds=5))
        rng=np.random.default_rng(20261118);samples=np.empty((10000,4,2),dtype=np.int32)
        for q in range(4):
            counts=rng.choice(len(law.count_pmf),size=10000,p=law.count_pmf)
            for s in range(2):samples[:,q,s]=rng.multinomial(counts,quarters[q][s].reward())@np.arange(4)
        forecasts[name]=Forecast(VERSION+'_'+name,law.means,samples=samples,law=law,metadata=dict(method='MC_WITH_ANALYTIC_LAW',scenarios=10000,seed=20261118,
            pace_mean=mean,pace_std=std,pace_definition=p['pace_definition'],measured_pbp=False,
            available_box_corpus_ids=p['box_training_ids'],effective_rate_game_ids=sorted(unique),
            same_efficiency_rates_across_pace_ablation=True,
            parameter_uncertainty_integrated=False,conditioning='FITTED_RATE_POINT_ESTIMATES',
            assumptions=['BOX_FT_FACTOR_0.44','TWO_FT_TRIPS_INFERRED_NO_AND_ONE_OR_THREE_FT',
                         'NO_FT_REBOUND','CONDITIONAL_TEAM_REWARD_INDEPENDENCE','INDEPENDENT_QUARTERS',
                         'RECENT_REGULATION_SCORE_PROFILE_TILT'],
            player_effect_fitted=False,calibration_status='NOT_CALIBRATED',confidence_index=None))
    return forecasts,blocked,common

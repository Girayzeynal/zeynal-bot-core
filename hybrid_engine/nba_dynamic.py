"""Versioned NBA-only recency/rate research. Active and V2 fits stay unchanged.

Box possessions are estimates. Measured PBP, travel and player coefficients are
not silently substituted. The strict all-feature request therefore abstains.
"""
from statistics import NormalDist
import time

import numpy as np

from core.team_identity import digest
from hybrid_engine.adaptive_models import checked_rows,box_rows
from hybrid_engine.data import STRICT,Abstain,available_at,regulation
from hybrid_engine.distributions import Forecast
from hybrid_engine.time_policy import PREMATCH_MINIMUM_LEAD_SECONDS

VERSION='NBA_RECENCY_OPPONENT_RATE_CORRELATED_RQMC_V3'
POLICY=dict(half_life_days=14.,minimum_games=30,minimum_team_games=6,maximum_team_age_days=14,
    maximum_history_games=3000,scenarios=10000,seed=20261118,coefficient_prior_sd=5.,
    covariance_shrinkage=.5,minimum_lead_seconds=PREMATCH_MINIMUM_LEAD_SECONDS,refresh_seconds=21600)


def _vector(teams,own,other,home):
    if own not in teams or other not in teams:raise Abstain('DYNAMIC_UNKNOWN_TARGET_TEAM')
    x=np.zeros(2+2*len(teams));x[0]=1;x[1]=float(home)
    x[2+teams.index(own)]=1;x[2+len(teams)+teams.index(other)]=1
    return x


def fit(cohort, *, cutoff_utc):
    rows=checked_rows(cohort,cutoff_utc)
    if len(rows)>POLICY['maximum_history_games']:raise Abstain('DYNAMIC_HISTORY_BUDGET')
    if not rows or any(r['league']!='NBA' for r in rows):raise ValueError('DYNAMIC_NBA_ONLY')
    rows=box_rows(rows,cutoff_utc)
    if len(rows)<POLICY['minimum_games']:raise Abstain('DYNAMIC_THIRTY_NATIVE_BOX_GAMES_REQUIRED')
    teams=sorted({r[s+'_team_id'] for r in rows for s in ('home','away')})
    if len(teams)>30:raise ValueError('DYNAMIC_NBA_TEAM_BUDGET')
    n=2+2*len(teams);x=[];y=[];weights=[];pace=[];quarters=[]
    for r in rows:
        q=np.asarray([r['periods'][s][:4] for s in ('home','away')]).T
        count=float(np.mean([r['box']['teams'][s]['possessions_estimate'] for s in ('home','away')]))
        if not 50<count<160:raise Abstain('DYNAMIC_BOX_PACE_OUT_OF_RANGE')
        w=2**(-(cutoff_utc-r['fixture_start_utc'])/(86400*POLICY['half_life_days']))
        weights.extend([w,w]);pace.append(count);quarters.append(q)
        for j,(s,o) in enumerate((('home','away'),('away','home'))):
            x.append(_vector(teams,r[s+'_team_id'],r[o+'_team_id'],s=='home'));y.append(100*regulation(r)[j]/count)
    x=np.asarray(x);y=np.asarray(y);w=np.asarray(weights)
    if w.sum()<5:raise Abstain('DYNAMIC_EFFECTIVE_RECENT_SAMPLE_TOO_SMALL')
    noise=max(4.,float(np.average((y-np.average(y,weights=w))**2,weights=w)))
    prior_sd=np.r_[30.,3.,np.full(n-2,POLICY['coefficient_prior_sd'])]
    precision=x.T@(w[:,None]*x)/noise+np.diag(1/prior_sd**2)
    prior=np.zeros(n);prior[0]=np.average(y,weights=w)
    cov=np.linalg.inv(precision);coef=np.linalg.solve(precision,x.T@(w*y)/noise+prior/prior_sd**2)
    gw=w[::2];quarter=np.asarray(quarters,dtype=float)
    profile=np.average(quarter,axis=0,weights=gw);profile/=profile.sum(axis=0)
    predicted=(x@coef).reshape(-1,2)*np.asarray(pace)[:,None]/100
    residual=(quarter-predicted[:,None,:]*profile[None,:,:]).reshape(-1,8)
    centered=residual-np.average(residual,axis=0,weights=gw)
    empirical=(centered.T@(gw[:,None]*centered))/gw.sum()
    shrink=POLICY['covariance_shrinkage']
    residual_cov=(1-shrink)*empirical+shrink*np.diag(np.diag(empirical))+np.eye(8)
    summaries=[dict(fixture_id=r['fixture_id'],start=r['fixture_start_utc'],
        available=available_at(r,STRICT),home=r['home_team_id'],away=r['away_team_id'],pace=p,
        quarters=rq.tolist(),source_sha256=r['source_catalog_sha256']) for r,p,rq in zip(rows,pace,quarter)]
    body=dict(format=VERSION,league='NBA',season=rows[0]['season'],cutoff_utc=cutoff_utc,
        prepared_at_utc=int(time.time()),policy=POLICY,teams=teams,coefficients=coef.tolist(),
        parameter_covariance=cov.tolist(),residual_covariance=residual_cov.tolist(),
        period_profile=profile.tolist(),training=summaries,training_ids=sorted(r['fixture_id'] for r in rows),
        training_available_max=max(available_at(r,STRICT) for r in rows),
        possessions='BOX_ESTIMATE_FGA_PLUS_0.44FTA_MINUS_ORB_PLUS_TOV',measured_pbp=False,
        player_effects=False,travel_effects=False,rest_effects=False,
        fallback='RECENCY_AND_OPPONENT_ADJUSTED_BOX_RATE_ONLY',
        unsupported=['MEASURED_PBP','VERIFIED_PLAYER_EFFECTS','VERIFIED_REST_TRAVEL_B2B'],
        calibration_status='NOT_CALIBRATED',production_enabled=False)
    return dict(payload=body,sha256=digest(body))


def _normals(n,method,seed):
    if method=='MC':return np.random.default_rng(seed).standard_normal((n,8))
    if method!='RQMC_HALTON_8D':raise ValueError('DYNAMIC_MC_OR_RQMC_REQUIRED')
    rng=np.random.default_rng(seed);out=np.zeros((n,8));normal=NormalDist()
    for j,base in enumerate((2,3,5,7,11,13,17,19)):
        index=np.arange(1,n+1,dtype=np.int64);factor=1.
        while np.any(index):
            factor/=base;out[:,j]+=factor*(index%base);index//=base
        out[:,j]=(out[:,j]+rng.random())%1
        out[:,j]=[normal.inv_cdf(float(v)) for v in np.clip(out[:,j],1e-12,1-1e-12)]
    return out


def predict(wrapper,target, *, cutoff_utc,method='RQMC_HALTON_8D',require_all_features=False):
    p=wrapper['payload'];now=int(time.time())
    if digest(p)!=wrapper['sha256'] or p['format']!=VERSION or p['policy']!=POLICY:raise ValueError('DYNAMIC_MODEL_PIN')
    if p['production_enabled'] is not False:raise ValueError('DYNAMIC_RESEARCH_ONLY')
    if require_all_features:raise Abstain('DYNAMIC_MEASURED_PBP_PLAYER_REST_TRAVEL_NOT_VERIFIED')
    if not 0<p['cutoff_utc']<=p['prepared_at_utc']<=cutoff_utc<=now<target['fixture_start_utc']-PREMATCH_MINIMUM_LEAD_SECONDS:
        raise Abstain('DYNAMIC_MODEL_OR_PREMATCH_CLOCK')
    if target['fixture_id'] in p['training_ids'] or (target['league'],target['season'])!=('NBA',p['season']):
        raise ValueError('DYNAMIC_TARGET_TRAINING_OR_COHORT')
    if p['training_available_max']>p['cutoff_utc']:raise ValueError('DYNAMIC_FUTURE_TRAINING_LABEL')
    return _simulate(wrapper,target,cutoff_utc,method)


def historical_replay(wrapper,target,*,origin_utc,method='RQMC_HALTON_8D'):
    """Use the same score equations with strictly as-of labels, on a replay clock."""
    p=wrapper['payload']
    if (digest(p)!=wrapper['sha256'] or p['format']!=VERSION or p['policy']!=POLICY or
            p['production_enabled'] is not False):
        raise ValueError('DYNAMIC_MODEL_PIN')
    if (not 0<p['training_available_max']<=p['cutoff_utc']<=origin_utc<p['prepared_at_utc']<=int(time.time())
            or origin_utc>=target['fixture_start_utc']-PREMATCH_MINIMUM_LEAD_SECONDS
            or target['fixture_start_utc']>=int(time.time())):
        raise Abstain('DYNAMIC_HISTORICAL_ORIGIN_INVALID')
    if target['fixture_id'] in p['training_ids'] or (target['league'],target['season'])!=('NBA',p['season']):
        raise ValueError('DYNAMIC_TARGET_TRAINING_OR_COHORT')
    f=_simulate(wrapper,target,origin_utc,method)
    f.metadata.update(historical_replay=True,prepared_at_utc=p['prepared_at_utc'],
                      verified_asof_origin_utc=origin_utc)
    return f


def _simulate(wrapper,target,cutoff_utc,method):
    p=wrapper['payload'];history=p['training']
    profiles=[];counts=[]
    for side in ('home','away'):
        tid=target[side+'_team_id'];entries=[r for r in history if tid in (r['home'],r['away'])]
        if len(entries)<6 or cutoff_utc-max(r['start'] for r in entries)>14*86400:raise Abstain('DYNAMIC_RECENT_TEAM_HISTORY_REQUIRED')
        entries=sorted(entries,key=lambda r:r['start'])[-10:];counts.extend(r['pace'] for r in entries)
        w=np.asarray([2**(-(cutoff_utc-r['start'])/(14*86400)) for r in entries])
        q=np.asarray([np.asarray(r['quarters'])[:,0 if tid==r['home'] else 1] for r in entries])
        profile=np.average(q,axis=0,weights=w);profiles.append(profile/profile.sum())
    # One game contributes once even if both teams played each other.
    recent={r['fixture_id']:r for tid in (target['home_team_id'],target['away_team_id'])
            for r in sorted([r for r in history if tid in (r['home'],r['away'])],key=lambda r:r['start'])[-10:]}
    rw=np.asarray([2**(-(cutoff_utc-r['start'])/(14*86400)) for r in recent.values()])
    rp=np.asarray([r['pace'] for r in recent.values()]);pace=float(np.average(rp,weights=rw))
    x=np.asarray([_vector(p['teams'],target[s+'_team_id'],target[o+'_team_id'],s=='home') for s,o in (('home','away'),('away','home'))])
    rates=x@np.asarray(p['coefficients']);means=rates*pace/100
    if np.any(means<50) or np.any(means>180):raise Abstain('DYNAMIC_SCORE_OUT_OF_RANGE')
    profile=np.asarray(profiles).T;quarter=profile*means
    project=np.zeros((8,2))
    for q in range(4):
        for s in range(2):project[2*q+s,s]=profile[q,s]*pace/100
    # Residual covariance already includes game-to-game pace variation; do not
    # add that variance twice. Parameter uncertainty is projected separately.
    covariance=np.asarray(p['residual_covariance'])+project@(x@np.asarray(p['parameter_covariance'])@x.T)@project.T
    paths=np.maximum(0,np.rint(quarter.reshape(8)+_normals(10000,method,POLICY['seed'])@np.linalg.cholesky(covariance).T)).astype(np.int32).reshape(-1,4,2)
    return Forecast(VERSION,quarter,samples=paths,metadata=dict(method=method,seed=POLICY['seed'],scenarios=10000,
        model_sha256=wrapper['sha256'],fit_cutoff_utc=p['cutoff_utc'],box_pace=pace,
        effective_pace_game_ids=sorted(recent),half_life_days=14.,recency_weighted_efficiency=True,
        opponent_adjusted=True,dynamic_full_game_mean=True,parameter_uncertainty_integrated=True,
        period_covariance='SHRUNK_EMPIRICAL_EIGHT_DIMENSIONAL_PLUS_PARAMETER_POSTERIOR',
        deterministic_period_allocation=False,missing_features=p['unsupported'],fallback=p['fallback'],
        measured_pbp=False,player_effects=False,rest_effects=False,travel_effects=False,
        calibration_status='NOT_CALIBRATED',confidence_index=None))

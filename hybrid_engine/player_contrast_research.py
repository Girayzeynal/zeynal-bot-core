"""Separate NBA historical minute-contrast candidate, not a live injury model.

Selection uses training exposures only: remove team/opponent/home nuisance
directions, require repeated observable minute variation, then cap independent
player columns by residual degrees of freedom. No outcomes select features.
Absolute causal/defensive/pace effects remain unsupported; no promotion.
"""
import time

import numpy as np
from core.team_identity import digest
from hybrid_engine.data import Abstain
from hybrid_engine.player_box_pilot import fit_box_association,projected_pair

VERSION='NBA_HISTORICAL_IDENTIFIABLE_MINUTE_CONTRAST_RESEARCH_V2'
POLICY=dict(minimum_appearances=6,minimum_residual_rms_minutes=1.,maximum_players=64,
    maximum_candidates=512,residual_degrees_of_freedom=10,observations_per_player_term=2,
    production_enabled=False,automatic_promotion=False)


def fit(games,cutoff_utc):
    if type(cutoff_utc) is not int or not 0<cutoff_utc<=int(time.time()):
        raise ValueError('PLAYER_CONTRAST_REAL_PAST_CUTOFF_REQUIRED')
    if not isinstance(games,list) or len(games)>1000:raise ValueError('PLAYER_CONTRAST_GAME_BUDGET')
    if any(not isinstance(g,dict) or g.get('league')!='NBA' for g in games):
        raise ValueError('PLAYER_CONTRAST_NBA_ONLY')
    # Reject corrupt exposures/labels before even fitting the team control.
    # The public reader supplies provenance-checked rows; this second boundary
    # also protects offline comparison callers from NaN/overflow arithmetic.
    for g in games:
        for side in ('home','away'):
            minutes=g['minutes'][side]
            if (not isinstance(minutes,dict) or not 6<=len(minutes)<=30 or
                    any(type(pid) is not str or not pid.isdigit() or
                        type(v) not in (float,int) or not np.isfinite(v) or not 0<=v<=48
                        for pid,v in minutes.items()) or abs(sum(minutes.values())-240)>3):
                raise ValueError('PLAYER_CONTRAST_NATIVE_MINUTE_BUDGET')
        if (not isinstance(g['score'],(tuple,list)) or len(g['score'])!=2 or
                any(type(v) not in (float,int) or not np.isfinite(v) or not 0<=v<=300 for v in g['score'])):
            raise ValueError('PLAYER_CONTRAST_FINITE_NATIVE_SCORES')
    control=fit_box_association(games,cutoff_utc,include_players=False)
    if control['status']!='REAL_HISTORICAL_BOX_MODEL_FITTED_RESEARCH_ONLY':
        raise Abstain('PLAYER_CONTRAST_THIRTY_NATIVE_BOX_GAMES_REQUIRED')
    teams=control['teams'];ix={t:i for i,t in enumerate(teams)};n=2*len(games);k=2+2*len(teams)
    appearances=control['player_appearance_games']
    candidates=sorted((p for p,count in appearances.items() if count>=POLICY['minimum_appearances']),
        key=lambda p:(-appearances[p],p))[:POLICY['maximum_candidates']]
    if not candidates:raise Abstain('PLAYER_CONTRAST_REPEATED_EXPOSURES_REQUIRED')
    pix={p:i for i,p in enumerate(candidates)}
    base=np.zeros((n,k));exposure=np.zeros((n,len(candidates)));y=np.zeros(n)
    for i,g in enumerate(games):
        for j,(side,other) in enumerate((('home','away'),('away','home'))):
            row=2*i+j;base[row,0]=1;base[row,1]=float(side=='home')
            base[row,2+ix[g[side+'_team_id']]]=1;base[row,2+len(teams)+ix[g[other+'_team_id']]]=1
            minutes=g['minutes'][side]
            for pid,v in minutes.items():
                if pid in pix:exposure[row,pix[pid]]=v/48
            y[row]=g['score'][j]
    u,s,_=np.linalg.svd(base,full_matrices=False)
    rank=int(np.sum(s>max(base.shape)*np.finfo(float).eps*s[0]))
    nuisance=u[:,:rank]
    residual=exposure-nuisance@(nuisance.T@exposure)
    capacity=min(POLICY['maximum_players'],max(0,(n-rank-POLICY['residual_degrees_of_freedom'])//POLICY['observations_per_player_term']))
    threshold=np.sqrt(n)*POLICY['minimum_residual_rms_minutes']/48
    selected=[];available=np.ones(len(candidates),dtype=bool)
    for _ in range(capacity):
        norms=np.linalg.norm(residual,axis=0);norms[~available]=-1
        best=int(np.argmax(norms))
        if norms[best]<threshold:break
        direction=residual[:,best]/norms[best]
        residual-=np.outer(direction,direction@residual)
        available[best]=False;selected.append(best)
    if not selected:raise Abstain('PLAYER_CONTRAST_NO_IDENTIFIABLE_MINUTE_VARIATION')
    selected.sort(key=lambda j:candidates[j]);players=[candidates[j] for j in selected]
    X=np.column_stack((base,exposure[:,selected]));full_rank=int(np.linalg.matrix_rank(X))
    if full_rank!=rank+len(players):raise ValueError('PLAYER_CONTRAST_INDEPENDENT_FEATURE_RANK')
    scale=np.r_[30.,3.,np.full(2*len(teams),4.),np.full(len(players),2.)]
    noise=max(1.,float(np.var(y,ddof=1)));precision=X.T@X/noise+np.diag(1/(scale*scale))
    prior=np.zeros(X.shape[1]);prior[0]=float(y.mean())
    coefficients=np.linalg.solve(precision,X.T@y/noise+prior/(scale*scale))
    if not np.isfinite(coefficients).all():raise ValueError('PLAYER_CONTRAST_NONFINITE_MODEL')
    p=dict(control,format=VERSION,policy=dict(POLICY),players=players,coefficients=coefficients.tolist(),
        fit_kind='HISTORICAL_PLAYER_MINUTE_CONTRASTS',estimated_parameters=X.shape[1],
        underdetermined_player_parameters=X.shape[1]>n,omitted_rare_players=len(appearances)-len(players),
        base_design_rank=rank,full_design_rank=full_rank,player_contrasts_rank_identified=True,
        source_blind_feature_selection=True,selection_uses_score_outcomes=False,
        absolute_causal_effect_identified=False,live_player_effect_applied=False,
        development_candidate_not_independent_validation=True,
        unsupported=['INDIVIDUAL_DEFENSE','PLAYER_PACE','PBP','VERIFIED_LIVE_MINUTES','CAUSAL_EFFECTS'])
    return dict(payload=p,sha256=digest(p))


def fit_for_comparison(games,cutoff_utc):return fit(games,cutoff_utc)['payload']


def conditional_pair(wrapper,home,away,home_rotation,away_rotation):
    p=wrapper['payload']
    if digest(p)!=wrapper['sha256'] or p['format']!=VERSION or p['policy']!=POLICY:
        raise ValueError('PLAYER_CONTRAST_MODEL_PIN')
    for rotation in (home_rotation,away_rotation):
        if (not isinstance(rotation,dict) or len(rotation)>30 or
                any(type(pid) is not str or not pid.isdigit() or
                    type(v) not in (float,int) or not np.isfinite(v) or not 0<=v<=48 for pid,v in rotation.items())):
            raise ValueError('PLAYER_CONTRAST_ROTATION_SCHEMA')
    return dict(prediction=projected_pair(p,home,away,home_rotation,away_rotation),
        model_sha256=wrapper['sha256'],conditional_on_supplied_minutes=True,
        source_availability_verified=False,live_player_effect_applied=False,production_enabled=False)

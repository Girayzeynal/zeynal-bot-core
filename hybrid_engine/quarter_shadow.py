"""Exploratory past-only stochastic quarter allocation; never installed in a bot.

Keeps every original regulation team score path and every point projection. Only
conditional within-game allocation uncertainty changes. This is not calibrated.
"""
import hashlib
from pathlib import Path

import numpy as np

from hybrid_engine.data import STRICT,Abstain,available_at
from hybrid_engine.distributions import Forecast
from hybrid_engine.intervals import sample_paths

VERSION='SHADOW_DIRICHLET_PERIOD_ALLOCATION_V1'


def fit_rows(cohort,target,cutoff):
    from hybrid_engine.data import prior_rows
    # A later target cut may select a newer receipt for an old match. Restore
    # the version available at FIT time; do not filter only that later cut.
    return prior_rows(cohort,dict(target,fixture_start_utc=cutoff+1),STRICT)


def predict(forecast,cut,*,seed=20261113):
    if type(seed) is not int or seed<0:raise ValueError('NONNEGATIVE_SHADOW_SEED_REQUIRED')
    if cut.evaluation_class!=STRICT:raise ValueError('STRICT_SHADOW_INPUTS_REQUIRED')
    original=sample_paths(forecast);scores=original.sum(axis=1);out=np.zeros_like(original)
    if np.any(forecast.scores<=0):raise Abstain('POSITIVE_TEAM_SCORE_REQUIRED')
    rng=np.random.default_rng(seed);trace={}
    for side,j in (('home',0),('away',1)):
        team=cut.target[side+'_team_id'];shares=[];ids=[]
        for r in cut.history:
            if r['fixture_id']==cut.target['fixture_id'] or available_at(r,STRICT)>cut.cutoff_utc or r['fixture_start_utc']>=cut.cutoff_utc:
                raise ValueError('SHADOW_QUARTER_FUTURE_OR_TARGET_LABEL')
            if team not in (r['home_team_id'],r['away_team_id']):continue
            own='home' if r['home_team_id']==team else 'away';q=np.asarray(r['periods'][own][:4],dtype=float)
            if len(q)!=4 or q.sum()<=0:continue
            shares.append(q/q.sum());ids.append(r['fixture_id'])
        if len(shares)<6:raise Abstain('INSUFFICIENT_PAST_QUARTER_SHARES')
        # Generic moment estimate, declared without using any target outcome.
        variance=np.var(np.asarray(shares),axis=0,ddof=1);weights=forecast.quarter_means[:,j]/forecast.scores[j]
        estimates=weights*(1-weights)/np.maximum(variance,1e-8)-1
        concentration=float(np.clip(np.median(estimates),4.,10000.))
        probabilities=rng.dirichlet(np.maximum(weights*concentration,1e-6),size=len(scores))
        raw=scores[:,j,None]*probabilities;allocated=np.floor(raw).astype(np.int32)
        remaining=scores[:,j]-allocated.sum(axis=1);order=np.argsort(-(raw-allocated),axis=1,kind='stable')
        for k in range(4):allocated[np.arange(len(scores)),order[:,k]]+=remaining>k
        out[:,:,j]=allocated;trace[side]=dict(past_games=len(shares),fit_ids=ids,concentration=concentration)
    if not np.array_equal(out.sum(axis=1),scores):raise ValueError('SHADOW_TEAM_TOTAL_CONSERVATION')
    return Forecast(VERSION,forecast.quarter_means.copy(),samples=out,
        metadata=dict(method='DIRICHLET_LARGEST_REMAINDER_SHADOW',seed=seed,scenarios=len(out),
            base_model=forecast.model,fit_cutoff_utc=cut.cutoff_utc,past_only_fit=trace,
            implementation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            point_profile_and_full_game_paths_unchanged=True,calibration_status='UNCALIBRATED',
            candidate_created_after_known_five_game_results=True,confirmatory=False,production_enabled=False))


def evaluate_walk_forward(cohort,previous_report):
    """Reconstruct the exact old test folds; this reused holdout is exploratory."""
    from hybrid_engine.data import feature_cut
    from hybrid_engine.models import HierarchicalStrength
    from hybrid_engine.intervals import prediction_intervals,empirical_coverage
    models={};reports={}
    for name,c in previous_report['cohorts'].items():
        cases=[];base_cases=[];losses=[];ids=[]
        for row in c.get('model_rows',{}).get('BAYES_QMC',[]):
            target=next(versions[0] for versions in cohort if versions[0]['fixture_id']==row['fixture_id'])
            cut=feature_cut(cohort,target,mode=STRICT);fit=row['trace']['fit_cutoff'];key=(name,fit)
            if key not in models:
                past=fit_rows(cohort,cut.target,fit)
                models[key]=HierarchicalStrength().fit(past,cutoff_utc=fit,mode=STRICT)
            model=models[key];base=model.predict(cut,method='RQMC_HALTON')
            if not np.allclose([base.scores[0],base.scores[1]],[row['prediction']['home'],row['prediction']['away']],atol=1e-8,rtol=1e-10):
                raise ValueError('SHADOW_BASELINE_FOLD_RECONSTRUCTION')
            shadow=predict(base,cut);b=prediction_intervals(base);s=prediction_intervals(shadow)
            periods={k:np.asarray(row['actual_quarters'])[:,j].tolist() for j,k in enumerate(('home','away'))}
            cases.append((s,periods));base_cases.append((b,periods));actual=np.asarray(row['actual_quarters']).sum(axis=1)
            def loss(bands):
                return float(np.mean([v['p95']-v['p05']+20*max(v['p05']-actual[q],0)+20*max(actual[q]-v['p95'],0)
                    for q,v in enumerate(bands['markets'][str(i+1)+'Q'] for i in range(4))]))
            losses.append(dict(fixture_id=row['fixture_id'],tipoff_utc=target['fixture_start_utc'],baseline=loss(b),candidate=loss(s)))
            ids.append(dict(fixture_id=row['fixture_id'],fit_cutoff=fit,prediction_cutoff=cut.cutoff_utc,
                max_history_available=max(available_at(r,STRICT) for r in cut.history),fit_ids=model.training_ids))
        if not losses:reports[name]=dict(n=0,status='INSUFFICIENT_DATA');continue
        days=sorted({(r['tipoff_utc']+10800)//86400 for r in losses});diff=np.array([r['candidate']-r['baseline'] for r in losses]);bounds=None
        if len(days)>=8:
            groups=[np.flatnonzero([(r['tipoff_utc']+10800)//86400==d for r in losses]) for d in days];rng=np.random.default_rng(20261113)
            draws=[float(np.mean(np.concatenate([diff[groups[j]] for j in rng.integers(0,len(groups),len(groups))]))) for _ in range(2000)]
            bounds=np.quantile(draws,[.025,.975]).tolist()
        reports[name]=dict(n=len(losses),day_clusters=len(days),traces=ids,
            baseline_coverage=empirical_coverage(base_cases),candidate_coverage=empirical_coverage(cases),interval_losses=losses,
            quarter_total_90_interval_score=dict(baseline=float(np.mean([r['baseline'] for r in losses])),candidate=float(np.mean([r['candidate'] for r in losses])),
                difference=float(diff.mean()),exploratory_day_cluster_95=bounds,lower_is_better=True),
            point_scores_and_full_game_distributions_unchanged=True)
    return dict(format='EXPLORATORY_QUARTER_SHADOW_WALK_FORWARD_V1',model_version=VERSION,cohorts=reports,
        reused_historical_test_set=True,fresh_confirmatory_holdout=False,calibration_fit=False,
        production_enabled=False,promotion_decision='NO_GO;NEW_DISJOINT_PROSPECTIVE_VALIDATION_REQUIRED')

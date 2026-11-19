"""Read-only engine/feature ablations; never a PREMATCH publication or promotion.

Default STRICT requires actual pre-origin availability. Explicit ASSUMED research
keeps native clocks untouched and uses the existing 24h availability assumption.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from core.team_identity import digest
from hybrid_engine.adaptive_data import native_catalog
from hybrid_engine.availability import effective_box_time
from hybrid_engine.boxes import normalize_box,checked_stats,publish_json
from hybrid_engine.data import STRICT,ASSUMED,Abstain,available_at,prior_rows,feature_cut,regulation,reference,local_path
from hybrid_engine.distributions import Budget,Forecast,gaussian_forecast,quarter_weights
from hybrid_engine.evaluation import v1_forecast,summarize,point_metrics
from hybrid_engine.intervals import prediction_intervals
from hybrid_engine.models import HierarchicalStrength
from hybrid_engine.possession import PossessionLaw,_aggregate,_quarter_rate
from hybrid_engine.research_history_union import union,VERSION as UNION_VERSION
from hybrid_engine.statistics import paired_cluster_interval,paired_winner_interval

VERSION='ISSUE90_CHRONOLOGICAL_ENGINE_STUDY_V1'
CORE_MODELS=('FAZ13_NATIVE','SCORE_ONLY','OPPONENT_ADJUSTED','BAYES_V1_FROZEN_MC',
             'BAYES_V1_FROZEN_RQMC','V2_TEAM_KERNEL_MC','V2_TEAM_KERNEL_RQMC')
PACE_MODELS=('V2_RATE_FIXED_PACE_KERNEL','V2_RATE_RECENT_PACE_KERNEL')


def corpus(receipts,*,year):
    catalogs=[];summary=[]
    for r in receipts:
        c=native_catalog(r,'NBA',year);catalogs.append((c,c['sha256']))
        if '/summary?event=' in r['source_url']:summary.append(r)
    cohort=union(catalogs);rejected=Counter()
    for versions in cohort:
        for row in versions:
            boxes=[]
            for r in summary:
                if not any(r['source_url'].endswith('summary?event='+pid) for pid in row['provider_fixture_ids']):continue
                try:boxes.append(normalize_box(row,r))
                except (ValueError,KeyError,TypeError) as exc:rejected[type(exc).__name__]+=1
            if boxes:row['box_versions']=boxes
    return cohort,dict(rejected)


def _pace_kernels(history,target,mode):
    # Same rate/count equations and sampler as adaptive_models.predict; this is
    # an offline mathematical replay, not an existing scheduled V2 publication.
    boxed=[]
    for r in history:
        candidates=[b for b in r.get('box_versions',[]) if b['regulation_eligible'] and
            all(len(r['periods'][s])==4 for s in ('home','away')) and
            (mode!=STRICT or effective_box_time(b)<target['fixture_start_utc'])]
        if not candidates:continue
        b=max(candidates,key=effective_box_time)
        for i,s in enumerate(('home','away')):
            if checked_stats(b['teams'][s])['points']!=regulation(r)[i]:raise ValueError('STUDY_BOX_SCORE_CONFLICT')
        boxed.append(dict(r,box=b,box_versions=[b]))
    if len(boxed)<30:raise Abstain('THIRTY_NATIVE_REGULATION_BOXES_REQUIRED')
    cut=feature_cut([[r] for r in boxed],target,mode=mode)
    entries={s:cut.features[s]['boxes'] for s in ('home','away')}
    if min(map(len,entries.values()))<6:raise Abstain('SIX_BOXES_PER_TARGET_TEAM_REQUIRED')
    home=[(b,own,other) for r,b,own,other in entries['home']]
    away=[(b,own,other) for r,b,own,other in entries['away']]
    rates=[_aggregate(home+[(b,other,own) for b,own,other in away]),
           _aggregate(away+[(b,other,own) for b,own,other in home])]
    weights=quarter_weights(cut);ratios=4*weights/weights.sum(axis=0)
    quarters=[[_quarter_rate(rate,ratios[q,s]) for s,rate in enumerate(rates)] for q in range(4)]
    counts=[float(np.mean([r['box']['teams'][s]['possessions_estimate'] for s in ('home','away')])) for r in boxed]
    recent={r['fixture_id']:float(np.mean([b['teams'][s]['possessions_estimate'] for s in ('home','away')]))
            for values in entries.values() for r,b,own,other in values}
    out={}
    for name,pace in zip(PACE_MODELS,(counts,list(recent.values()))):
        law=PossessionLaw(quarters,float(np.mean(pace)),float(np.std(pace)),Budget(seconds=5))
        rng=np.random.default_rng(20261118);samples=np.empty((10000,4,2),dtype=np.int32)
        for q in range(4):
            n=rng.choice(len(law.count_pmf),size=10000,p=law.count_pmf)
            for s in range(2):samples[:,q,s]=rng.multinomial(n,quarters[q][s].reward())@np.arange(4)
        out[name]=Forecast(name,law.means,samples=samples,metadata=dict(method='V2_RATE_KERNEL_MC',scenarios=10000,
            seed=20261118,pace_mean=float(np.mean(pace)),pace_std=float(np.std(pace)),measured_pbp=False,
            pace_definition='NATIVE_BOX_FGA_PLUS_0.44FTA_MINUS_ORB_PLUS_TOV_ESTIMATE',
            same_rate_fit_ids=sorted(recent),population_box_ids=sorted(r['fixture_id'] for r in boxed),
            mathematical_replay_not_scheduled_v2_publication=True))
    return out


def _record(forecast,cut,truth,role,line,seconds,fit_ids):
    q=np.array([truth['periods'][s][:4] for s in ('home','away')]).T
    bands=prediction_intervals(forecast)
    probs=forecast.market('TOTAL',line)
    result=dict(fixture_id=truth['fixture_id'],start_utc=truth['fixture_start_utc'],role=role,
        provider_fixture_ids=truth['provider_fixture_ids'],teams=[truth['home_team_id'],truth['away_team_id']],
        actual=regulation(truth),actual_quarters=q.tolist(),prediction=forecast.summary(),seconds=seconds,
        fit_ids=fit_ids,feature_ids=[r['fixture_id'] for r in cut.history],inputs_digest=cut.inputs_digest,
        raw_source_clock_max=max(r['ingested_at_utc'] for r in cut.history),
        bands=bands,markets=dict(TOTAL=dict(line=line,probabilities=probs,
            outcome=0 if sum(regulation(truth))<line else 2 if sum(regulation(truth))>line else 1)),
        line_kind='PREDECLARED_FAZ13_REFERENCE_SCENARIO_NOT_BOOKMAKER',
        capture_kind='RETROSPECTIVE_REPLAY_NOT_AN_ORIGINAL_PREGAME_FORECAST')
    paths=forecast.samples
    if paths is None and getattr(forecast.law,'paths',None) is not None:paths=forecast.law.paths.samples
    if paths is not None:
        samples=paths.astype(float);totals=samples.sum(axis=(1,2))
        correlations=np.corrcoef(samples.sum(axis=2).T);off_diagonal=correlations[np.triu_indices(4,1)]
        result['simulation_diagnostics']=dict(scenarios=len(samples),minimum=int(samples.min()),
            total_mean=float(totals.mean()),total_std=float(totals.std()),
            total_point_minus_sample_mean=float(forecast.scores.sum()-totals.mean()),
            max_quarter_point_minus_sample_mean=float(np.max(np.abs(forecast.quarter_means-samples.mean(axis=0)))),
            home_away_correlation=float(np.corrcoef(samples.sum(axis=1).T)[0,1]),
            mean_quarter_total_correlation=float(off_diagonal.mean()),
            sample_sha256=hashlib.sha256(paths.astype('<i4',copy=False).tobytes()).hexdigest(),
            sample_encoding='C_ORDER_INT32_LITTLE_ENDIAN_SCENARIO_QUARTER_SIDE',
            realism_status='DESCRIPTIVE_ONLY_NOT_VALIDATED_ROTATION_OR_PBP')
    return result


def _metrics(rows):
    result=summarize(rows)
    result['calibration_status']='NOT_CALIBRATED';result['confidence_index']=None
    if rows:
        error=np.array([r['prediction']['quarters'] for r in rows])-np.array([r['actual_quarters'] for r in rows])
        result['period_totals']={str(i+1)+'Q':point_metrics(error[:,i].sum(axis=1)) for i in range(4)}
        result['half_totals']={str(i+1)+'H':point_metrics(error[:,2*i:2*i+2].sum(axis=(1,2))) for i in range(2)}
    coverage={}
    for lo,hi,mass in (('p25','p75',.5),('p05','p95',.9)):
        valid=[r for r in rows if r['bands'].get('status')=='AVAILABLE' or 'TOTAL' in r['bands'].get('markets',{})]
        hits=sum(r['bands']['markets']['TOTAL'][lo]<=sum(r['actual'])<=r['bands']['markets']['TOTAL'][hi] for r in valid)
        coverage[lo+'_'+hi]=dict(n=len(valid),hits=hits,nominal_mass=mass,
            observed=hits/len(valid) if valid else None,status='DESCRIPTIVE_NOT_CALIBRATION_PROOF')
    result['total_coverage']=coverage
    return result


def evaluate(cohort,*,mode=STRICT):
    if mode not in (STRICT,ASSUMED):raise ValueError('EXPLICIT_STUDY_AVAILABILITY_POLICY')
    rows=[max(v,key=lambda r:(r['ingested_at_utc'],r['source_catalog_sha256'])) for v in cohort]
    if len({(r['league'],r['season']) for r in rows})!=1:raise ValueError('STUDY_SINGLE_LEAGUE_SEASON')
    days=sorted({(r['fixture_start_utc']+10800)//86400 for r in rows})
    if len(days)<10:raise Abstain('TEN_DISTINCT_GAME_DAYS_REQUIRED')
    val_day=days[len(days)//2];test_day=days[int(.7*len(days))]
    val_start=min(r['fixture_start_utc'] for r in rows if (r['fixture_start_utc']+10800)//86400==val_day)
    test_start=min(r['fixture_start_utc'] for r in rows if (r['fixture_start_utc']+10800)//86400==test_day)
    train=prior_rows(cohort,next(r for r in rows if r['fixture_start_utc']==val_start),mode)
    development=prior_rows(cohort,next(r for r in rows if r['fixture_start_utc']==test_start),mode)
    report=dict(format=VERSION,generated_at_utc=int(time.time()),evaluation_class=mode,
        split=dict(unit='WHOLE_ISTANBUL_DAYS_50_20_30',validation_start_utc=val_start,test_start_utc=test_start,
            train_ids=sorted(r['fixture_id'] for r in train),development_ids=sorted(r['fixture_id'] for r in development),
            test_labels_used_for_fit_or_features=False),
        source_union=UNION_VERSION,native_source_clocks_rewritten=False,prospective_forecasts_created=0,
        historical_replay_excluded_from_live_accuracy=True,automatic_promotion=False,production_changed=False,
        calibration_fit=False,confidence_index=None,fresh_confirmatory_holdout=False,acceptance='NO_GO',
        observed_bookmaker_comparison=dict(status='NOT_VERIFIED_NO_ADMITTED_NATIVE_CONTRACT',n=0),
        ablation_limitations=dict(measured_pace='ABSTAIN_NO_VERIFIED_PBP_POSSESSION_BOUNDARIES',
            player_effect='ABSTAIN_NO_PREMATCH_MINUTE_EXPOSURES',scheduled_v2_publication='NOT_AVAILABLE_IN_THIS_REPLAY'),
        models={},cases={name:[] for name in CORE_MODELS+PACE_MODELS},abstentions={})
    if len(train)<30 or len(development)<30:
        return dict(report,status='ABSTAIN_INSUFFICIENT_PRE_ORIGIN_TRAINING')
    frozen=HierarchicalStrength().fit(train,cutoff_utc=val_start-1,mode=mode)
    refreshed=HierarchicalStrength().fit(development,cutoff_utc=test_start-1,mode=mode)
    exclusions=Counter()
    for truth in sorted(rows,key=lambda r:(r['fixture_start_utc'],r['fixture_id'])):
        if truth['fixture_start_utc']<val_start:continue
        role='VALIDATION' if truth['fixture_start_utc']<test_start else 'TEST'
        history=train if role=='VALIDATION' else development
        try:cut=feature_cut([[r] for r in history],truth,mode=mode)
        except Abstain as exc:exclusions[str(exc)]+=1;continue
        p=reference(cut);line=float(round(p['total'])+.5);budget=Budget(seconds=5)
        means=[p['home'],p['away']];std=[cut.features[s]['points_for_std'] for s in ('home','away')]
        weights=quarter_weights(cut)
        jobs={'FAZ13_NATIVE':lambda:v1_forecast(cut),
            'SCORE_ONLY':lambda:gaussian_forecast(means,std,weights,method='MC',budget=budget),
            'OPPONENT_ADJUSTED':lambda:gaussian_forecast([
                (cut.features['home']['opponent_adjusted_for']+cut.features['away']['points_against'])/2,
                (cut.features['away']['opponent_adjusted_for']+cut.features['home']['points_against'])/2],std,weights,method='MC',budget=budget),
            'BAYES_V1_FROZEN_MC':lambda:frozen.predict(cut,method='MC',budget=budget,bounded_workspace=True),
            'BAYES_V1_FROZEN_RQMC':lambda:frozen.predict(cut,method='RQMC_HALTON',budget=budget,bounded_workspace=True)}
        # Updated-team core uses the same unchanged hierarchy fitted by V2;
        # it is NOT the complete scheduled V2 artifact/box/player pipeline.
        current=frozen if role=='VALIDATION' else refreshed
        jobs.update(V2_TEAM_KERNEL_MC=lambda:current.predict(cut,method='MC',budget=budget,bounded_workspace=True),
                    V2_TEAM_KERNEL_RQMC=lambda:current.predict(cut,method='RQMC_HALTON',budget=budget,bounded_workspace=True))
        for name,job in jobs.items():
            began=time.perf_counter()
            try:f=job()
            except Abstain as exc:exclusions[name+':'+str(exc)]+=1;continue
            fit_ids=current.training_ids if name.startswith('V2_') else frozen.training_ids if name.startswith('BAYES_') else []
            report['cases'][name].append(_record(f,cut,truth,role,line,time.perf_counter()-began,fit_ids))
        try:
            began=time.perf_counter();pace=_pace_kernels(history,cut.target,mode)
            for name,f in pace.items():report['cases'][name].append(_record(f,cut,truth,role,line,time.perf_counter()-began,
                f.metadata['population_box_ids']))
        except Abstain as exc:exclusions['PACE:'+str(exc)]+=1
    for name,cases in report['cases'].items():
        test=[r for r in cases if r['role']=='TEST'];validation=[r for r in cases if r['role']=='VALIDATION']
        report['models'][name]=dict(validation=_metrics(validation),test=_metrics(test))
    baseline=[r for r in report['cases']['FAZ13_NATIVE'] if r['role']=='TEST']
    report['paired_vs_faz13']={name:paired_cluster_interval(baseline,[r for r in cases if r['role']=='TEST'],iterations=1000)
                             for name,cases in report['cases'].items() if name!='FAZ13_NATIVE'}
    report['matched_test_comparisons']={}
    for name,cases in report['cases'].items():
        if name=='FAZ13_NATIVE':continue
        candidate=[r for r in cases if r['role']=='TEST'];ids={r['fixture_id'] for r in candidate}
        matched=[r for r in baseline if r['fixture_id'] in ids]
        report['matched_test_comparisons'][name]=dict(fixture_ids=sorted(ids),baseline=_metrics(matched),
            candidate=_metrics(candidate),winner_paired=paired_winner_interval(matched,candidate,iterations=1000))
    fixed=[r for r in report['cases'][PACE_MODELS[0]] if r['role']=='TEST']
    recent=[r for r in report['cases'][PACE_MODELS[1]] if r['role']=='TEST']
    report['controlled_pace_comparison']=dict(fixed=_metrics(fixed),recent=_metrics(recent),
        paired=paired_cluster_interval(fixed,recent,iterations=1000),
        caveat='BOX_ESTIMATE_NOT_MEASURED_PBP_SAME_RATES_SAME_COHORT')
    report['abstentions']=dict(exclusions);report['status']='EXPLORATORY_REPLAY_COMPLETE_NOT_PROSPECTIVE_EVIDENCE'
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipts-directory',required=True);parser.add_argument('--year',type=int,required=True)
    parser.add_argument('--assumed-research',action='store_true');parser.add_argument('--output-directory',required=True)
    args=parser.parse_args();folder=local_path(args.receipts_directory)
    receipts=[json.loads(p.read_text()) for p in sorted(folder.glob('*.json')) if p.name!='capture-summary.json']
    cohort,rejected=corpus(receipts,year=args.year)
    report=evaluate(cohort,mode=ASSUMED if args.assumed_research else STRICT)
    report['source_receipt_pins']=[digest(r) for r in receipts];report['box_rejections']=rejected
    report['source_permission']='NOT_ESTABLISHED_BY_THIS_STUDY'
    out=local_path(args.output_directory);out.mkdir(parents=True,exist_ok=True)
    path=out/('chronological-study-'+digest(report)+'.json');publish_json(path,dict(payload=report,sha256=digest(report)))
    print(json.dumps(dict(path=str(path),status=report['status'],acceptance=report['acceptance'],
        metrics={k:v['test'] for k,v in report['models'].items()})))


if __name__=='__main__':main()

"""Descriptive live-only metrics. Calibration curves measure errors; they never refit."""
import math
import numpy as np
from hybrid_engine.evaluation import point_metrics, probability_metrics
from hybrid_engine.intervals import empirical_coverage,actual_market_values
from hybrid_engine.markets import wilson
from hybrid_engine.calibration_guard import PLAN_DEFAULTS


def interval_scores(cases):
    """Proper central interval score (lower is better), distinct from coverage."""
    groups={}
    for bands,periods in cases:
        actual=actual_market_values(periods)
        for market,b in bands['markets'].items():
            for name,lo,hi,alpha in [('P25_P75','p25','p75',.5),('P05_P95','p05','p95',.1)]:
                low,high=b[lo],b[hi];y=actual[market]
                score=high-low+2/alpha*(max(0,low-y)+max(0,y-high))
                groups.setdefault((market,name),[]).append(score)
    out={}
    for (market,name),values in groups.items():out.setdefault(market,{})[name]=dict(n=len(values),mean_interval_score=float(np.mean(values)))
    return out


def reliability(probabilities,observations):
    output={}
    for j,label in enumerate(('home','regulation_tie','away')):
        bins=[]
        for i in range(10):
            indices=[k for k,p in enumerate(probabilities) if i/10<=p[j] and (p[j]<(i+1)/10 or i==9 and p[j]<=1)]
            n=len(indices);hits=sum(observations[k]==j for k in indices)
            bins.append(dict(n=n,mean_probability=None if not n else float(np.mean([probabilities[k][j] for k in indices])),
                observed_frequency=None if not n else hits/n,wilson_95=None if not n else wilson(hits,n)))
        output[label]=bins
    return output


def metrics(rows):
    settled=[r for r in rows if r['actual'] is not None]
    # A caller cannot silently pool different fitted versions to claim calibration.
    identities={(r.get('league'),r.get('season'),r.get('model_version'),r.get('model_digest')) for r in settled if r.get('model_digest')}
    if len(identities)>1:raise ValueError('REPORT_SEPARATE_FITTED_MODEL_COHORTS_REQUIRED')
    result=dict(n=len(settled),calibration_status='NOT_CALIBRATED',confidence_index=None,calibration_fit=False,superiority_claim=False)
    if not settled:return result
    for r in settled:
        if len(r['prediction'])!=2 or len(r['actual'])!=2 or any(type(x) not in (int,float) or not math.isfinite(x) or x<0 for x in r['prediction']+r['actual']):
            raise ValueError('REPORT_FINITE_TEAM_SCORES_REQUIRED')
        periods=r['actual_periods']
        if (set(periods)!= {'home','away'} or any(len(periods[s])<4 or any(type(x) is not int or x<0 for x in periods[s]) for s in ('home','away')) or
            [sum(periods[s][:4]) for s in ('home','away')]!=r['actual']):raise ValueError('REPORT_REGULATION_PERIOD_CONFLICT')
        stamp=r.get('prediction_generated_at_utc');label=r.get('label_available_utc')
        if stamp is not None and (type(stamp) is not int or not 0<stamp<r['fixture_start_utc']):raise ValueError('REPORT_LATE_FORECAST')
        if label is not None and (type(label) is not int or label<=r['fixture_start_utc']):raise ValueError('REPORT_EARLY_LABEL')
    errors=[p-a for r in settled for p,a in zip(r['prediction'],r['actual'])]
    result['team_scores']=point_metrics(errors)
    result['total']=point_metrics([sum(r['prediction'])-sum(r['actual']) for r in settled])
    result['margin']=point_metrics([r['prediction'][0]-r['prediction'][1]-r['actual'][0]+r['actual'][1] for r in settled])
    result['home']=point_metrics([r['prediction'][0]-r['actual'][0] for r in settled])
    result['away']=point_metrics([r['prediction'][1]-r['actual'][1] for r in settled])
    periods=[];bands=[];probs=[];observed=[]
    for r in settled:
        if r.get('predicted_quarters') is not None:
            q=np.asarray(r['predicted_quarters'],dtype=float)
            a=np.asarray([r['actual_periods'][s][:4] for s in ('home','away')],dtype=float).T
            if q.shape!=(4,2) or not np.isfinite(q).all() or np.any(q<0) or not np.allclose(q.sum(axis=0),r['prediction'],atol=.025,rtol=0):
                raise ValueError('REPORT_PERIOD_PROJECTION_CONFLICT')
            if r.get('predicted_halves') is not None:
                halves=np.asarray(r['predicted_halves'],dtype=float)
                if halves.shape!=(2,2) or not np.isfinite(halves).all() or not np.allclose(halves,np.array([q[:2].sum(axis=0),q[2:].sum(axis=0)]),atol=.015,rtol=0):
                    raise ValueError('REPORT_HALF_PROJECTION_CONFLICT')
            periods.append(q-a)
        b=r.get('intervals')
        if b and b.get('status')!='UNSUPPORTED':
            if b.get('scope')!='REGULATION_ONLY' or type(b.get('scenarios')) is not int or b['scenarios']<10000:
                raise ValueError('REPORT_SIMULATION_SCOPE_OR_COUNT')
            for v in b.get('markets',{}).values():
                values=[v[k] for k in ('p05','p10','p25','p50','p75','p90','p95')]
                if not all(type(x) in (float,int) and math.isfinite(x) for x in values) or values!=sorted(values):
                    raise ValueError('REPORT_INVALID_QUANTILES')
            bands.append((b,r['actual_periods']))
        p=r.get('winner')
        if p is not None:
            if len(p)!=3 or any(type(x) not in (int,float) or not math.isfinite(x) or not 0<=x<=1 for x in p) or abs(sum(p)-1)>1e-8:
                raise ValueError('REPORT_PROBABILITY_SIMPLEX')
            probs.append(p);observed.append(0 if r['actual'][0]>r['actual'][1] else 1 if r['actual'][0]==r['actual'][1] else 2)
    result['periods']={};result['halves']={};result['period_totals']={};result['half_totals']={}
    if periods:
        a=np.asarray(periods)
        result['periods']={str(i+1)+'Q':dict(n=len(a),**point_metrics(a[:,i])) for i in range(4)}
        result['halves']={str(i+1)+'H':dict(n=len(a),**point_metrics(a[:,2*i:2*i+2].sum(axis=1))) for i in range(2)}
        result['period_totals']={str(i+1)+'Q':dict(n=len(a),**point_metrics(a[:,i].sum(axis=1))) for i in range(4)}
        result['half_totals']={str(i+1)+'H':dict(n=len(a),**point_metrics(a[:,2*i:2*i+2].sum(axis=(1,2)))) for i in range(2)}
    result['coverage']=empirical_coverage(bands);result['interval_scores']=interval_scores(bands)
    if probs:
        result['winner']=probability_metrics(probs,observed)
        result['winner']['correct']=sum(int(np.argmax(p))==y for p,y in zip(probs,observed))
        result['winner']['class_order']=['HOME','REGULATION_TIE','AWAY']
        result['winner']['brier_definition']='MEAN_SUM_OF_THREE_SQUARED_CLASS_ERRORS_RANGE_0_TO_2'
        result['winner']['reliability']=reliability(probs,observed)
    result['interval_status']='DESCRIPTIVE_ONLY_INSUFFICIENT_PROSPECTIVE_VALIDATION'
    result['day_clusters']=len({(r['fixture_start_utc']+10800)//86400 for r in settled})
    result['confidence_intervals']=None
    result['confidence_interval_reason']='LIVE_COHORT_NOT_PREREGISTERED_FOR_INFERENTIAL_CLAIMS'
    result['future_calibration_requirements']=dict(minimum_past_fit=PLAN_DEFAULTS['minimum_past_fit'],minimum_disjoint_future_audit=PLAN_DEFAULTS['minimum_oos_audit'],minimum_day_clusters=PLAN_DEFAULTS['minimum_day_clusters'],
        parameters_fitted_now=False,automatic_refit=False,automatic_promotion=False,source_asset_audit_required=True)
    return result

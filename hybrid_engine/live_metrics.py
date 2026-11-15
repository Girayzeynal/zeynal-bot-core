"""Descriptive live-only metrics; no training, resampling forecasts or confidence claims."""
import math
import numpy as np
from hybrid_engine.evaluation import point_metrics, probability_metrics
from hybrid_engine.intervals import empirical_coverage


def metrics(rows):
    settled=[r for r in rows if r['actual'] is not None]
    errors=[p-a for r in settled for p,a in zip(r['prediction'],r['actual'])]
    result=dict(n=len(settled),calibration_status='NOT_CALIBRATED',confidence_index=None,
                calibration_fit=False,superiority_claim=False)
    if not settled:return result
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
            periods.append(q-a)
        b=r.get('intervals')
        if b and b.get('status')!='UNSUPPORTED':
            for v in b.get('markets',{}).values():
                values=[v[k] for k in ('p05','p10','p25','p50','p75','p90','p95')]
                if not all(type(x) in (float,int) and math.isfinite(x) for x in values) or values!=sorted(values):
                    raise ValueError('REPORT_INVALID_QUANTILES')
            bands.append((b,r['actual_periods']))
        p=r.get('winner')
        if p is not None:
            probs.append(p);observed.append(0 if r['actual'][0]>r['actual'][1] else 1 if r['actual'][0]==r['actual'][1] else 2)
    result['periods']={};result['halves']={}
    if periods:
        a=np.asarray(periods)
        result['periods']={str(i+1)+'Q':dict(n=len(a),**point_metrics(a[:,i])) for i in range(4)}
        result['halves']={str(i+1)+'H':dict(n=len(a),**point_metrics(a[:,2*i:2*i+2].sum(axis=1))) for i in range(2)}
    result['coverage']=empirical_coverage(bands)
    if probs:
        result['winner']=probability_metrics(probs,observed)
        result['winner']['correct']=sum(int(np.argmax(p))==y for p,y in zip(probs,observed))
    result['interval_status']='DESCRIPTIVE_ONLY_INSUFFICIENT_PROSPECTIVE_VALIDATION'
    result['day_clusters']=len({(r['fixture_start_utc']+10800)//86400 for r in settled})
    result['confidence_intervals']=None
    result['confidence_interval_reason']='LIVE_COHORT_NOT_PREREGISTERED_FOR_INFERENTIAL_CLAIMS'
    return result

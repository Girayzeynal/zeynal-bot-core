"""Prequential residual calibration for point-score research, not live admission.

Fixed shrinkage; no target labels, no fabricated player minutes. Residual bands
are empirical research bands, not guaranteed conditional coverage.
"""
from math import ceil
from statistics import median

PRIOR = 8
LIMIT_TOTAL = 12.
LIMIT_MARGIN = 8.


def _shrink(values, limit):
    if not values:
        return 0.
    return max(-limit, min(limit, median(values)*len(values)/(len(values)+PRIOR)))


def residual_correction(prior):
    errors = [[p-a for p,a in zip(r['predictions']['BLEND'],r['actual'])] for r in prior]
    total = _shrink([h+a for h,a in errors], LIMIT_TOTAL)
    margin = _shrink([h-a for h,a in errors], LIMIT_MARGIN)
    return [(total+margin)/2, (total-margin)/2]


def calibrate(scores, quarters, prior):
    correction=residual_correction(prior)
    scores=[max(0.,v-d) for v,d in zip(scores,correction)]
    if quarters is None:
        return scores,None
    # Learn quarter shares from earlier actuals only, and shrink toward the
    # current forecast's own shares. Rescale exactly to corrected team scores.
    result=[[0.,0.] for _ in range(4)]
    usable=[r for r in prior if r.get('actual_team_quarters') is not None]
    for side in range(2):
        total=sum(q[side] for q in quarters)
        own=[q[side]/total for q in quarters] if total>0 else [.25]*4
        past=[]
        for r in usable:
            values=r['actual_team_quarters'][side]
            s=sum(values)
            if s>0:past.append([v/s for v in values])
        weight=len(past)/(len(past)+PRIOR)
        shares=[(1-weight)*own[q]+weight*sum(p[q] for p in past)/len(past)
                for q in range(4)] if past else own
        norm=sum(shares)
        for q in range(4):
            result[q][side]=scores[side]*shares[q]/norm
    return scores,result


def empirical_band(point, errors, level):
    # Finite-sample conformal rank; if rank cannot be estimated, abstain.
    n=len(errors)
    k=ceil((n+1)*level)
    if k>n or n==0:
        return None
    radius=sorted(abs(e) for e in errors)[k-1]
    return [max(0.,point-radius),point+radius]


def interval_summary(rows):
    output={}
    for key in ('TOTAL','1Q','2Q','3Q','4Q','1H','2H'):
        metrics={}
        for level in (.5,.8,.9):
            bands=[(r['bands'][key][str(level)],r['realized'][key]) for r in rows
                   if key in r['bands'] and r['bands'][key][str(level)] is not None]
            metrics[str(level)]=dict(n=len(bands),coverage=sum(lo<=y<=hi for (lo,hi),y in bands)/len(bands) if bands else None,
                                     mean_width=sum(hi-lo for (lo,hi),_ in bands)/len(bands) if bands else None)
        output[key]=metrics
    return output


def market_values(scores, quarters):
    result={'TOTAL':sum(scores)}
    if quarters is not None:
        for q in range(4):result[str(q+1)+'Q']=sum(quarters[q])
        for h in range(2):result[str(h+1)+'H']=sum(result[str(q+1)+'Q'] for q in (2*h,2*h+1))
    return result


def bands_for(prediction, prior):
    return {key:{str(level):empirical_band(value,
                [r['calibrated_values'][key]-r['realized'][key] for r in prior
                 if key in r['calibrated_values'] and key in r['realized']],level)
                for level in (.5,.8,.9)} for key,value in prediction.items()}

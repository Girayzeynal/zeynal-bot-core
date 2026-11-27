"""Unique-fixture, past-label-only point-score blend research (not live).

Use only previously authenticated published pairs; no refits of the original
models, no player assumptions, no probability calibration or archive writes.
The selection rule is fixed here, not selected by observed target accuracy.
"""
from collections import defaultdict
from math import sqrt
from statistics import mean
from hybrid_engine.prequential_residual import calibrate, market_values, bands_for, interval_summary

VERSION = 'UNIQUE_CHRONOLOGICAL_POINT_BLEND_V1'
PRIOR_GAMES = 8
GRID = [(i/4, j/4, (4-i-j)/4) for i in range(5) for j in range(5-i)]
EQUAL = (1/3, 1/3, 1/3)


def _identity(base):
    return base['league'], base['season'], base['fixture_id']


def _signature(candidate, base):
    return (base['snapshot_sha256'], base['model_digest'], tuple(base['prediction']),
            tuple(base['actual']), base['label_available_utc'],
            tuple(candidate['prediction']),
            tuple(tuple(q) for q in candidate.get('predicted_quarters') or []))


def _mix(scores, weights):
    return [sum(w*s[j] for w, s in zip(weights, scores)) for j in range(2)]


def _loss(prediction, actual):
    h, a = (prediction[j]-actual[j] for j in range(2))
    return (abs(h+a)+abs(h-a))/2


def _weights(prior):
    if not prior:
        return EQUAL
    best = min(GRID, key=lambda w: (
        mean(_loss(_mix(r['scores'], w), r['actual']) for r in prior),
        sum((x-y)**2 for x,y in zip(w,EQUAL)), w))
    shrink = len(prior)/(len(prior)+PRIOR_GAMES)
    return tuple(shrink*x+(1-shrink)*y for x,y in zip(best,EQUAL))


def _metrics(rows, name):
    errors = [[p-a for p,a in zip(r['predictions'][name], r['actual'])] for r in rows]
    totals = [sum(e) for e in errors]
    quarters = [r for r in rows if r['quarters'].get(name) is not None
                and r['actual_quarters'] is not None]
    return dict(total_mae=mean(map(abs,totals)), total_rmse=sqrt(mean(e*e for e in totals)),
                bias=mean(totals), team_mae=mean(abs(e) for pair in errors for e in pair),
                margin_mae=mean(abs(h-a) for h,a in errors), quarter_n=len(quarters),
                quarter_mae=[mean(abs(sum(r['quarters'][name][q])-r['actual_quarters'][q])
                                  for r in quarters) for q in range(4)] if quarters else None,
                half_mae=[mean(abs(sum(sum(r['quarters'][name][q])-r['actual_quarters'][q]
                                      for q in (2*h,2*h+1))) for r in quarters)
                          for h in range(2)] if quarters else None)


def evaluate(protocols):
    # Only native V2 tempo and native V3. Current-assessment aliases are
    # intentionally excluded rather than counted as an independent model.
    index = defaultdict(lambda: defaultdict(list))
    for meta, groups in protocols:
        family = meta['family']
        if family not in ('adaptive-v2','nba-v3'):
            continue
        for key, pairs in groups.items():
            if key[0]!='NBA' or (family=='adaptive-v2' and key[-1]!='PACE_EFFICIENCY'):
                continue
            for candidate, base in pairs:
                index[_identity(base)][family].append((candidate,base))
    duplicates, conflicts = 0, 0
    cohorts = defaultdict(list)
    for identity, families in sorted(index.items()):
        duplicates += sum(max(0,len(rows)-1) for rows in families.values())
        if set(families) != {'adaptive-v2','nba-v3'}:
            continue
        selected = []
        invalid = False
        for family in ('adaptive-v2','nba-v3'):
            rows = families[family]
            # Select the earliest durable publication; never select by errors.
            rank = min((c['candidate_archived_at_utc'],c['prediction_generated_at_utc']) for c,b in rows)
            tied = [(c,b) for c,b in rows if (c['candidate_archived_at_utc'],c['prediction_generated_at_utc'])==rank]
            if len({_signature(c,b) for c,b in tied})!=1:
                invalid=True
                break
            selected.append(tied[0])
        if invalid:
            conflicts+=1
            continue
        (v2,b2),(v3,b3)=selected
        if (_signature(b2,b2)!=_signature(b3,b3) or
                b2['fixture_start_utc']!=b3['fixture_start_utc'] or
                b2.get('actual_periods')!=b3.get('actual_periods')):
            conflicts+=1
            continue
        decision=max(v2['candidate_archived_at_utc'],v3['candidate_archived_at_utc'])
        final=b2['label_available_utc']
        if not decision < b2['fixture_start_utc'] < final:
            conflicts+=1
            continue
        q=[r.get('predicted_quarters') for r in (b2,v2,v3)]
        actual_periods=b2.get('actual_periods')
        actual_q=[sum(actual_periods[s][i] for s in ('home','away')) for i in range(4)] if actual_periods else None
        cohorts[(identity[0],identity[1],b2['model_digest'])].append(dict(
            fixture_id=identity[2], decision=decision, final=final,
            actual=b2['actual'], scores=[r['prediction'] for r in (b2,v2,v3)],
            source_quarters=q, actual_quarters=actual_q,
            actual_team_quarters=[actual_periods[s][:4] for s in ('home','away')] if actual_periods else None))
    groups=[]
    names=('V1','V2','V3','BLEND','CALIBRATED_SHADOW')
    for (league,season,model), rows in sorted(cohorts.items()):
        ordered=sorted(rows,key=lambda r:(r['decision'],r['fixture_id']))
        trace=[]
        for r in ordered:
            prior=[p for p in ordered if p['final']<r['decision']]
            weights=_weights(prior)
            preds=dict(zip(names[:3],r['scores']))
            preds['BLEND']=_mix(r['scores'],weights)
            quarters=dict(zip(names[:3],r['source_quarters']))
            quarters['BLEND']=[_mix([q[i] for q in r['source_quarters']],weights)
                               for i in range(4)] if all(r['source_quarters']) else None
            past=[p for p in trace if p['final']<r['decision']]
            preds['CALIBRATED_SHADOW'],quarters['CALIBRATED_SHADOW']=calibrate(
                preds['BLEND'],quarters['BLEND'],past)
            calibrated_values=market_values(preds['CALIBRATED_SHADOW'],quarters['CALIBRATED_SHADOW'])
            realized=market_values(r['actual'],
                list(zip(*r['actual_team_quarters'])) if r['actual_team_quarters'] is not None else None)
            trace.append(dict(r, predictions=preds, quarters=quarters, weights=weights,
                              training_n=len(prior),calibration_n=len(past),
                              calibrated_values=calibrated_values,realized=realized,
                              bands=bands_for(calibrated_values,past)))
        metrics={name:_metrics(trace,name) for name in names}
        delta=[abs(sum(r['predictions']['BLEND'])-sum(r['actual']))-
               abs(sum(r['predictions']['V1'])-sum(r['actual'])) for r in trace]
        groups.append(dict(league=league,season=season,original_model_digest=model,n=len(trace),
                           trained_n=sum(r['training_n']>0 for r in trace),metrics=metrics,
                           interval_research=interval_summary(trace),
                           residual_calibration_n=sum(r['calibration_n']>0 for r in trace),
                           improved=sum(d < -1e-9 for d in delta),worsened=sum(d > 1e-9 for d in delta),
                           unchanged=sum(abs(d)<=1e-9 for d in delta),
                           trace=[dict(fixture_id=r['fixture_id'],decision_utc=r['decision'],
                                       label_available_utc=r['final'],training_n=r['training_n'],
                                       weights=list(r['weights']),calibration_n=r['calibration_n']) for r in trace]))
    return dict(version=VERSION,n=sum(g['n'] for g in groups),duplicate_records=duplicates,
                conflicts=conflicts,groups=groups,production_enabled=False,
                prospective_publication=False,calibrated=False,
                weight_fit_performed=any(g['trained_n']>0 for g in groups))

"""Pure descriptive team/total/margin metrics and same-game comparison plans."""
from dataclasses import asdict
from statistics import fmean
import math

from historical_backtest import HistoricalPrediction,evaluate_predictions


def historical(row):
    return HistoricalPrediction(row['fixture_id'],'NBA',row['generated_at'],row['result_observed_utc'],
        row['expected_home'],row['expected_away'],row['actual_home'],row['actual_away'],
        fixture_start_ts_utc=row['start_utc'],prediction_scope=row['scope'],result_scope=row['scope'])


def score_metrics(rows):
    rows=list(rows)
    if not rows:return None
    records=[historical(r) for r in rows]
    result=asdict(evaluate_predictions(records))
    if len({(r['model'],r['model_version'],r['scope']) for r in rows})!=1:
        raise ValueError('separate model/version/scope cohorts required')
    for name,errors in (
        ('home',[r.expected_home-r.actual_home for r in records]),
        ('away',[r.expected_away-r.actual_away for r in records]),
        ('margin',[(r.expected_home-r.expected_away)-(r.actual_home-r.actual_away) for r in records])):
        result[name+'_mae']=fmean(abs(e) for e in errors)
        result[name+'_rmse']=math.sqrt(fmean(e*e for e in errors))
        result[name+'_bias']=fmean(errors)
    return result


def paired_compare(left,right):
    """Compare archived outputs only; never create the missing version's forecast."""
    left=list(left);right=list(right)
    score_metrics(left);score_metrics(right)
    if left and right and left[0]['scope']!=right[0]['scope']:
        return dict(status='INCOMPATIBLE_SCOPE',paired_games=0,metrics=None)
    a={r['fixture_id']:r for r in left};b={r['fixture_id']:r for r in right}
    common=sorted(a.keys()&b.keys())
    if not common:return dict(status='NO_COMMON_GAMES',paired_games=0,metrics=None,
        unmatched_left=len(left),unmatched_right=len(right))
    for fixture in common:
        if any(a[fixture][k]!=b[fixture][k] for k in ('start_utc','actual_home','actual_away','scope')):
            raise ValueError('paired fixture result identity mismatch')
    timing_mismatches=[f for f in common if a[f]['generated_at']!=b[f]['generated_at']]
    common=[f for f in common if f not in timing_mismatches]
    if not common:return dict(status='PREDICTION_CUTOFF_MISMATCH',paired_games=0,metrics=None,
        timing_mismatches=timing_mismatches)
    lm=score_metrics([a[f] for f in common]);rm=score_metrics([b[f] for f in common])
    keys=('home_mae','away_mae','score_mae','total_mae','margin_mae',
          'home_rmse','away_rmse','score_rmse','total_rmse','margin_rmse')
    return dict(status='DESCRIPTIVE_PAIRED_ONLY',paired_games=len(common),fixtures=common,
        unmatched_left=len(a)-len(common),unmatched_right=len(b)-len(common),
        metrics=dict(left=lm,right=rm,right_minus_left={k:rm[k]-lm[k] for k in keys}),
        timing_mismatches=timing_mismatches,
        statistical_claim='NONE_SMALL_SAMPLE',calibration_status='NOT_ESTABLISHED')


def walk_forward_plan(rows,minimum_training=30):
    """Plan observations available at prediction time without fitting coefficients."""
    if type(minimum_training) is not int or minimum_training<1:raise ValueError('invalid minimum training')
    rows=list(rows)
    grouped={}
    for row in rows:grouped.setdefault((row['model'],row['model_version'],row['scope']),[]).append(row)
    for cohort in grouped.values():score_metrics(cohort)
    folds=[]
    for target in sorted(rows,key=lambda r:(r['generated_at'],r['model'],r['fixture_id'])):
        key=(target['model'],target['model_version'],target['scope'])
        available=[r for r in grouped[key] if r['fixture_id']!=target['fixture_id'] and r['result_observed_utc']<target['generated_at']]
        folds.append(dict(fixture_id=target['fixture_id'],model=key[0],model_version=key[1],scope=key[2],
            prediction_utc=target['generated_at'],training_ids=sorted(r['fixture_id'] for r in available),
            available_training_games=len(available),eligible=len(available)>=minimum_training))
    return dict(folds=folds,minimum_training=minimum_training,eligible_folds=sum(f['eligible'] for f in folds),
                parameters_fitted=False,original_forecasts_changed=False,usage='OFFLINE_PLANNING_ONLY')

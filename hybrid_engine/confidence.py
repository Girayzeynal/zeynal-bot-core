"""Explainable quality index; never interprets event or interval probability as confidence."""
import math
from hybrid_engine.markets import MarketCalibration

WEIGHTS=dict(data_sufficiency=.25,calibration=.30,past_error=.20,uncertainty=.15,model_agreement=.10)


def confidence_index(*,context,calibration=None,history=None):
    reasons=[];parts={};cutoff=context['prediction_utc']
    if not isinstance(calibration,MarketCalibration):reasons.append('NO_VERIFIED_DISJOINT_CALIBRATION')
    else:
        try:
            audited=calibration.apply(context['probabilities'],model_digest=context['model_digest'],
                market=context['market'],line=context['line'],prediction_utc=cutoff)
            expected=audited['probabilities'][audited['selected_class']]
            gap=max(abs(bound-expected) for bound in audited['frequency_interval_95'])
            # Reliability deviation is a quality measure. Do NOT reuse the old
            # event-frequency lower bound named confidence_index as this index.
            parts['calibration']=100*max(0.,1-gap/.10)
        except ValueError:reasons.append('CALIBRATION_SCOPE_OR_TIME_CONFLICT')
    if (not history or history.get('role')!='PRIOR_AUDIT' or history.get('available_max_utc',cutoff+1)>cutoff or
        history.get('n',0)<100 or history.get('model_digest')!=context['model_digest']):
        reasons.append('NO_SUFFICIENT_PRIOR_MODEL_ERROR_AND_COVERAGE_AUDIT')
    else:
        mae=history['mae'];coverage=history['interval_coverage_90']
        if not math.isfinite(mae) or mae<0 or not 0<=coverage<=1:raise ValueError('INVALID_CONFIDENCE_HISTORY')
        parts['past_error']=100/(1+mae/10)
        width=context.get('relative_interval_width')
        if width is None or not math.isfinite(width) or width<0:reasons.append('NO_VALID_UNCERTAINTY_MEASURE')
        else:parts['uncertainty']=100*max(0.,1-abs(coverage-.9)) /(1+width)
    n=context.get('minimum_team_history',0)
    if n<6:reasons.append('INSUFFICIENT_TEAM_HISTORY')
    parts['data_sufficiency']=min(100.,max(0.,n/10*100))
    if not context.get('verified_roster_and_rotation'):reasons.append('UNVERIFIED_ROSTER_AND_ROTATION')
    disagreement=context.get('model_disagreement')
    if disagreement is None or not math.isfinite(disagreement) or not 0<=disagreement<=1:reasons.append('NO_VERIFIED_MODEL_AGREEMENT')
    else:parts['model_agreement']=100*(1-disagreement)
    score=None if reasons else round(sum(WEIGHTS[k]*parts[k] for k in WEIGHTS),1)
    return dict(status='NOT_ESTIMABLE' if reasons else 'AUDITED_POLICY_QUALITY_INDEX',value=score,scale=[0,100],
        components=parts,weights=WEIGHTS,reasons=reasons,
        calibration_component_definition='100*(1-worst_audited_frequency_gap/0.10), bounded at zero',
        meaning='POLICY_QUALITY_INDEX_NOT_EVENT_PROBABILITY_OR_INTERVAL_COVERAGE',weights_learned_from_outcomes=False)

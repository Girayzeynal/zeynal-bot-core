"""Observed markets and ML/total intersections from the SAME frozen paths.

Raw regulation intersections are not an OTC-inclusive parlay settlement model.
No combined price, bookmaker rule or calibrated joint probability is invented.
"""
import time
import numpy as np

from hybrid_engine.data import Abstain
from hybrid_engine.decision_layer import DecisionDistribution,evaluate_quote,settled_value


def audit(forecast,trace,quotes=(), *, rules=None,asof_utc,final=None):
    if type(asof_utc) is not int or not 0<asof_utc<=int(time.time()):raise ValueError('JOINT_ACTUAL_AUDIT_CLOCK_REQUIRED')
    distribution=DecisionDistribution(forecast,trace);rules=rules or {};markets=[]
    if len(quotes)>128:raise ValueError('JOINT_MARKET_BUDGET')
    for quote in quotes:
        rule=rules.get(quote.sha256)
        if rule is not None and rule.payload.get('include_overtime') and quote.payload['period']!='FULL':
            raise Abstain('JOINT_NON_FULL_OVERTIME_CONTRACT_UNSUPPORTED')
        item=evaluate_quote(distribution,quote,rules.get(quote.sha256),asof_utc=asof_utc)
        item['realized']=None
        if final is not None:
            if (final['fixture_id']!=trace['fixture_id'] or final['snapshot_sha256']!=trace['snapshot_sha256'] or
                final['model_digest']!=trace['model_digest'] or final['fixture_start_utc']!=trace['tipoff_utc'] or
                not trace['tipoff_utc']<final['label_available_utc']<=asof_utc):
                raise ValueError('JOINT_FINAL_FIXTURE_SNAPSHOT_MODEL_CLOCK')
            if item.get('raw_probabilities') is not None:
                rule=rules[quote.sha256].payload;q=quote.payload
                value=settled_value(final['actual_periods'],q['period'],q['market'],include_overtime=rule['include_overtime'])
                threshold=-q['line'] if q['market']=='HOME_HANDICAP' else q['line']
                direction='under' if value<threshold else 'push' if value==threshold else 'over'
                item['realized']=dict(value=value,outcome=direction,signed_line_deviation=value-threshold,
                    actual_return={s:(price-1 if direction==s else 0 if direction=='push' else -1) for s,price in q['prices'].items()})
        markets.append(item)
    pairs=[]
    for ml in markets:
        q=ml.get('quote',{})
        if q.get('market')!='WINNER' or q.get('period')!='FULL':continue
        for total in markets:
            t=total.get('quote',{})
            if (t.get('market')!='TOTAL' or t.get('period')!='FULL' or q['bookmaker_id']!=t['bookmaker_id'] or
                ml.get('conditional_regulation_probabilities') is None or total.get('conditional_regulation_probabilities') is None):continue
            h=distribution.values('FULL','WINNER');v=distribution.values('FULL','TOTAL')
            joint={winner+'_'+side:float(np.mean((h>0 if winner=='home' else h<0)&(v>t['line'] if side=='over' else v<t['line'])))
                   for winner in ('home','away') for side in ('over','under')}
            pairs.append(dict(winner_quote_sha256=ml['quote_sha256'],total_quote_sha256=total['quote_sha256'],
                raw_regulation_joint_probabilities=joint,scenarios=len(h),
                method='SAME_PATH_BOOLEAN_INTERSECTION_NOT_MULTIPLIED_MARGINALS',
                calibrated_joint_probabilities=None,expected_value=None,confidence_index=None,
                status='RAW_JOINT_RESEARCH_NO_VERIFIED_COMBINED_CONTRACT'))
    return dict(format='OBSERVED_JOINT_MARKET_AUDIT_V1',markets=markets,joint=pairs,
        status='NO_MARKET_DATA' if not quotes else 'RESEARCH_AUDIT',
        forecasts_changed=False,calibration_fit=False,production_enabled=False)

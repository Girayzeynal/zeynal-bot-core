"""All-line settlement audit; no selected-line-only calibration or OT scope substitution."""
from collections import defaultdict
import math

import numpy as np

from core.team_identity import digest
from hybrid_engine.decision_layer import settled_value
from hybrid_engine.evaluation import probability_metrics
from hybrid_engine.markets import wilson
from hybrid_engine.statistics import calibration_curve


def audit_markets(records,batches,outcomes):
    snapshots={r['snapshot_sha256']:r['snapshot'] for r in records};groups=defaultdict(dict)
    excluded=defaultdict(int);seen_quote_rows=0;seen_versions=0
    for batch in batches:
        pin=batch['snapshot_sha256']
        if pin not in snapshots:raise ValueError('DECISION_FORECAST_NOT_IN_TRUSTED_ARCHIVE')
        p=snapshots[pin];all_ids=batch['all_quote_ids'];evaluations=batch['evaluations']
        actual_ids=[e['quote_sha256'] for e in evaluations if e.get('quote_sha256') is not None]
        if len(set(all_ids))!=len(all_ids) or sorted(actual_ids)!=sorted(all_ids):raise ValueError('CHERRY_PICKED_OR_DUPLICATE_QUOTE_MANIFEST')
        for decision in evaluations:
            if decision.get('quote_sha256') is None:excluded['NO_MARKET_DATA']+=1;continue
            seen_quote_rows+=1;q=decision['quote']
            if digest(q)!=decision['quote_sha256']:raise ValueError('DECISION_QUOTE_PIN')
            if (q['fixture_id']!=p['fixture_id'] or q['league']!=p['league'] or q['season']!=p['season'] or
                q['tipoff_utc']!=p['fixture_start_utc'] or q['home_team_id']!=p['home']['provider_id'] or q['away_team_id']!=p['away']['provider_id']):
                raise ValueError('MARKET_SETTLEMENT_FORECAST_IDENTITY')
            if not q['ingested_at_utc']<=p['prediction_generated_at_utc'] or decision['prediction_utc']!=p['prediction_generated_at_utc']:
                raise ValueError('POSTHOC_MARKET_LINE_CANNOT_ENTER_CALIBRATION')
            if decision.get('raw_probabilities') is None or not decision.get('settlement'):
                excluded[decision['status']]+=1;continue
            if (decision['audit_class']!='PREGAME_RESEARCH_DECISION' or decision['evaluated_at_utc']>=p['fixture_start_utc'] or
                batch.get('recorded_at_utc',p['fixture_start_utc'])>=p['fixture_start_utc']):
                excluded['POSTHOC_DECISION_NOT_PREGAME_EVIDENCE']+=1;continue
            outcome=outcomes.get(p['fixture_id'])
            if outcome is None:excluded['PENDING_FINAL']+=1;continue
            s=decision['settlement']
            if s['period']!=q['period'] or s['market']!=q['market']:raise ValueError('MARKET_SETTLEMENT_SCOPE_CONFLICT')
            value=settled_value(outcome['periods'],q['period'],q['market'],include_overtime=s['include_overtime'])
            line=-q['line'] if q['market']=='HOME_HANDICAP' else q['line']
            y=0 if value<line else 1 if value==line else 2
            key=(p['league'],p['model_version'],q['period'],q['market'],s['include_overtime'],q['line'],q['bookmaker_id'])
            item=dict(fixture_id=p['fixture_id'],prediction_utc=p['prediction_generated_at_utc'],quote_observed_utc=q['observed_at_utc'],
                quote_sha256=decision['quote_sha256'],probabilities=[decision['raw_probabilities'][k] for k in ('under','push','over')],
                outcome=y,selected=bool(decision['selected']),actual_value=value)
            old=groups[key].get(p['fixture_id'])
            if old is not None:
                seen_versions+=1
                if old['outcome']!=y:raise ValueError('MARKET_OUTCOME_VERSION_CONFLICT')
            if old is None or (item['prediction_utc'],item['quote_observed_utc'],item['quote_sha256'])<(old['prediction_utc'],old['quote_observed_utc'],old['quote_sha256']):
                groups[key][p['fixture_id']]=item
    reports=[]
    for key,by_id in sorted(groups.items()):
        rows=list(by_id.values());p=[r['probabilities'] for r in rows];y=[r['outcome'] for r in rows]
        stats=probability_metrics(p,y);push=sum(v==1 for v in y);directions=[]
        for r in rows:
            probs=r['probabilities']
            if r['outcome']!=1 and probs[0]!=probs[2]:directions.append(int((2 if probs[2]>probs[0] else 0)==r['outcome']))
        stats.update(direction_hit_rate=(sum(directions)/len(directions) if directions else None),direction_count=len(directions),
            direction_interval_95=wilson(sum(directions),len(directions)),push_rate=push/len(rows),push_count=push,
            push_interval_95=wilson(push,len(rows)),selected_count=sum(r['selected'] for r in rows),
            unselected_count=sum(not r['selected'] for r in rows),
            reliability={k:calibration_curve([r['probabilities'][j] for r in rows],[int(r['outcome']==j) for r in rows]) for j,k in enumerate(('under','push','over'))})
        reports.append(dict(cohort=list(key),independent_forecasts=len(rows),metrics=stats,
            metric_class='ALL_ELIGIBLE_LINES_NOT_ONLY_SELECTED',calibration_verified=False,closing_line_value=None,
            real_bet_roi=None,unit='ONE_FIRST_QUOTE_PER_FIXTURE_EXACT_LINE_BOOK_AND_SCOPE'))
    return dict(status='DESCRIPTIVE_PREGAME_MARKET_AUDIT' if reports else 'NO_VERIFIED_PREGAME_SETTLEMENT_DECISIONS',
        quote_rows_seen=seen_quote_rows,quote_versions_not_independent=seen_versions,groups=reports,excluded=dict(excluded),
        independent_fixtures=len({r['fixture_id'] for group in groups.values() for r in group.values()}),
        pooling_different_lines_or_ot_scopes=False,selected_lines_only_metrics=False,
        checkpoint_count_is_not_sum_of_line_counts=True)

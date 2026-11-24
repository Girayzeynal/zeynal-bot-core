"""Current research decisions with their own clock; never retime a forecast.

The sealed original-forecast evaluator is unchanged. A later native price can
be reviewed now, before the earliest tipoff, but cannot become an input or a
performance observation at the original forecast issue time.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time
import threading

import numpy as np

from core.team_identity import digest
from hybrid_engine.boxes import publish_json
from hybrid_engine.data import local_path,Abstain
from hybrid_engine.decision_layer import QuoteEvidence,RuleEvidence,POLICY
from hybrid_engine.market_observations import fixture_identity,validate
from hybrid_engine.observed_markets import implied_prices

VERSION='CURRENT_MARKET_REVIEW_V1'
_JOURNAL_LOCK=threading.Lock()
POLICY_SHA=digest(dict(version=VERSION,implementation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                      recommendations_enabled=False,forecast_retiming_allowed=False))


def admit_odds(observation,snapshot,discovery,detail):
    """Replay native parser membership; no caller-provided verification boolean."""
    from hybrid_engine.provider_bridge import odds_observations
    candidates,_=odds_observations(detail,snapshot,discovery=discovery)
    if observation['sha256'] not in {r['sha256'] for r in candidates}:
        raise ValueError('NATIVE_PRICE_OBSERVATION_NOT_IN_RECEIPTS')
    p=validate(observation['payload'])
    if digest(p)!=observation['sha256']:
        raise ValueError('NATIVE_PRICE_OBSERVATION_PIN')
    quotes=[]
    for row in p['quotes']:
        q=dict(format='EXPLICIT_BOOK_MARKET_V1',**p['fixture'],**deepcopy(row),
            bookmaker_id=p['bookmaker']['id'],bookmaker=p['bookmaker']['name'],
            observed_at_utc=p['source']['captured_at_utc'],ingested_at_utc=p['available_at_utc'],
            published_at_utc=p['source']['published_at_utc'],source_url=p['source']['url'],
            source_document_sha256=p['source']['document_sha256'],
            native_quote_sha256=p['source']['native_quote_sha256'],observation_sha256=observation['sha256'],
            event_clock_binding=deepcopy(p['source']['event_clock_binding']),
            settlement_scope='UNKNOWN',closing_time_verified=False)
        QuoteEvidence.validate(q);quotes.append(QuoteEvidence(q,digest(q)))
    return quotes


def evaluate(observation,distribution,*,asof_utc,native_quotes=(),rules=None):
    p=validate(observation['payload'])
    if digest(p)!=observation['sha256']:raise ValueError('CURRENT_REVIEW_OBSERVATION_PIN')
    trace=distribution.trace
    fixture=fixture_identity({k:trace[k] for k in ('league','season','fixture_id','home_team_id','away_team_id','tipoff_utc')})
    if fixture!=p['fixture']:raise ValueError('CURRENT_REVIEW_FIXTURE_PIN')
    if type(asof_utc) is not int or not trace['prediction_utc']<=asof_utc<=int(time.time()):
        raise ValueError('CURRENT_REVIEW_TIME_INVALID')
    if any(not isinstance(q,QuoteEvidence) for q in native_quotes):raise ValueError('CURRENT_REVIEW_QUOTE_TYPE')
    quotes={q.sha256:q for q in native_quotes}
    if any(digest(q.payload)!=q.sha256 for q in quotes.values()):raise ValueError('CURRENT_REVIEW_QUOTE_PIN')
    result=dict(format=VERSION,policy_sha256=POLICY_SHA,fixture=fixture,bookmaker=deepcopy(p['bookmaker']),
        source=deepcopy(p['source']),observation_sha256=observation['sha256'],
        prediction_utc=trace['prediction_utc'],decision_utc=asof_utc,available_at_utc=p['available_at_utc'],
        model_digest=trace['model_digest'],model_version=trace['model_version'],
        forecast_age_seconds=asof_utc-trace['prediction_utc'],rows=[],
        probability_status='RAW_NOT_CALIBRATED',calibration_status='NOT_CALIBRATED',confidence_index=None,
        selection_enabled=False,forecast_changed=False,eligible_for_original_forecast_metrics=False,
        independent_unit='FIXTURE_NOT_QUOTE_COUNT',sample_count=len(distribution.paths))
    for row in p['quotes']:
        values=distribution.values(row['period'],row['market'])
        threshold=-row['line'] if row['market']=='HOME_HANDICAP' else row['line']
        raw=dict(under=float(np.mean(values<threshold)),push=float(np.mean(values==threshold)),over=float(np.mean(values>threshold)))
        item=dict(deepcopy(row),conditional_regulation_probabilities=raw,raw_contract_probabilities=None,
            conditional_probability_is_contract_settlement=False,expected_value=None,
            confidence_index=None,recommended_direction=None,calibrated_probabilities=None,
            status='SETTLEMENT_RULE_UNVERIFIED',reasons=[],information=[])
        if p['available_at_utc']>trace['prediction_utc']:item['information'].append('LATER_PRICE_CURRENT_REVIEW')
        if row['prices']:
            item['price_benchmarks']=dict(break_even_conditional_on_no_push={s:1/d for s,d in row['prices'].items()},
                no_vig=implied_prices(row['prices']['over'],row['prices']['under']) if set(row['prices'])=={'over','under'} else None,
                not_true_event_probabilities=True,settlement_scope_verified=False)
        else:item['price_benchmarks']=None
        candidates=[q for q in quotes.values() if all(q.payload[k]==row[k] for k in ('period','market','line','prices'))]
        quote=candidates[0] if len(candidates)==1 else None
        if quote is not None:
            q=quote.payload;QuoteEvidence.validate(q)
            if (q.get('observation_sha256')!=observation['sha256'] or
                    q.get('native_quote_sha256')!=p['source'].get('native_quote_sha256') or
                    q.get('source_document_sha256')!=p['source'].get('document_sha256') or
                    q.get('observed_at_utc')!=p['source']['captured_at_utc'] or
                    q.get('ingested_at_utc')!=p['available_at_utc'] or
                    q.get('published_at_utc')!=p['source']['published_at_utc'] or
                    q['bookmaker_id']!=p['bookmaker']['id'] or any(q[k]!=fixture[k] for k in fixture)):
                raise ValueError('CURRENT_REVIEW_NATIVE_SCOPE_CONFLICT')
            item['quote_sha256']=quote.sha256
        else:item['reasons'].append('NATIVE_PRICE_EVIDENCE_REQUIRED')
        if p['source']['method']=='MANUAL_SCREENSHOT':item['reasons'].append('MANUAL_PRICE_NOT_NATIVE_VERIFIED')
        captured=p['source']['captured_at_utc'];published=p['source']['published_at_utc']
        if captured is None:item['reasons'].append('SOURCE_CAPTURE_TIME_UNKNOWN')
        elif not captured<=p['available_at_utc']<=asof_utc:item['reasons'].append('PRICE_NOT_AVAILABLE_AT_REVIEW')
        elif asof_utc-captured>POLICY['quote_max_age_seconds']:item['reasons'].append('STALE_AT_DECISION_TIME')
        if published is not None and not 0<=asof_utc-published<=POLICY['quote_max_age_seconds']:
            item['reasons'].append('STALE_PUBLISHER_PRICE_AT_DECISION_TIME')
        cutoff=fixture['tipoff_utc']
        clock=p['source'].get('event_clock_binding')
        if clock:
            if digest(clock['payload'])!=clock['sha256']:raise ValueError('CURRENT_REVIEW_CLOCK_PIN')
            cutoff=min(cutoff,clock['payload']['prematch_deadline_utc'])
        if asof_utc>=cutoff:item['reasons'].append('POST_TIPOFF_ARCHIVE_REVIEW_ONLY')
        rule=(rules or {}).get((p['bookmaker']['id'],fixture['league'],row['period'],row['market']))
        if rule is None:item['reasons'].append('SETTLEMENT_RULE_UNVERIFIED')
        else:
            if not isinstance(rule,RuleEvidence) or digest(rule.payload)!=rule.sha256:raise ValueError('CURRENT_REVIEW_RULE_PIN')
            r=rule.payload;RuleEvidence.validate(r)
            if (any(r[k]!=(fixture['league'] if k=='league' else p['bookmaker']['id'] if k=='bookmaker_id' else row[k]) for k in ('league','bookmaker_id','period','market')) or
                    not 0<r['observed_at_utc']<=r['ingested_at_utc']<=asof_utc or r['effective_from_utc']>asof_utc or
                    r['effective_until_utc'] is not None and asof_utc>=r['effective_until_utc']):
                item['reasons'].append('RULE_SCOPE_OR_TIME_CONFLICT')
            if r['include_overtime'] and row['period']!='FULL':item['reasons'].append('UNSUPPORTED_PERIOD_OVERTIME_RULE')
            item['rule_sha256']=rule.sha256
        if not float(2*row['line']).is_integer():item['reasons'].append('SPLIT_STAKE_ASIAN_QUARTER_LINE_UNSUPPORTED')
        if not row['prices']:item['reasons'].append('NO_OBSERVED_PRICES')
        if not item['reasons']:
            try:contract=distribution.values(row['period'],row['market'],include_overtime=rule.payload['include_overtime'])
            except Abstain:item['reasons'].append('NO_VERIFIED_OVERTIME_SIMULATION_PATHS')
            else:
                mass=dict(under=float(np.mean(contract<threshold)),push=float(np.mean(contract==threshold)),over=float(np.mean(contract>threshold)))
                ev={s:mass[s]*(price-1)-mass['under' if s=='over' else 'over'] for s,price in row['prices'].items()}
                item.update(raw_contract_probabilities=mass,conditional_probability_is_contract_settlement=True,
                    expected_value=ev,status='NO_EDGE' if max(ev.values())<=0 else 'UNCALIBRATED')
                item['price_benchmarks']['settlement_scope_verified']=True
                no_push=1-mass['push'];bench=item['price_benchmarks']['no_vig']
                item['break_even_unconditional_win_probability']={s:no_push/price for s,price in row['prices'].items()}
                item['conditional_no_push_edge']=({s:mass[s]/no_push-bench['over_or_home' if s=='over' else 'under_or_away']
                                                   for s in ('under','over')} if bench is not None and no_push>0 else None)
        if item['reasons']:item['status']=item['reasons'][0]
        item['reasons'].append('NO_APPROVED_DISJOINT_CALIBRATION')
        result['rows'].append(item)
    return result


def fixture_journal_directory(root,league,fixture_id):
    # The exact canonical identity determines a bounded rollover directory.
    # Never use caller-controlled fixture strings as path components.
    return local_path(root/'fixtures'/digest(dict(league=league,fixture_id=fixture_id)))


class CurrentReviewJournal:
    """Separate immutable files; no SQL, prediction table or model edits."""
    def __init__(self,directory):self.root=local_path(directory)

    def record(self,snapshot,distribution,reviews,*,decision_utc):
        with _JOURNAL_LOCK:
            return self._record(snapshot,distribution,reviews,decision_utc=decision_utc)

    def _record(self,snapshot,distribution,reviews,*,decision_utc):
        from hybrid_engine.intervals import prediction_intervals
        from hybrid_engine.decision_audit import trace_for
        if distribution.trace!=trace_for(snapshot):raise ValueError('CURRENT_REVIEW_ORIGINAL_TRACE_PIN')
        if (not reviews or type(decision_utc) is not int or
                not snapshot['prediction_generated_at_utc']<=decision_utc<=int(time.time())):
            raise ValueError('CURRENT_REVIEW_ARCHIVE_CLOCK_OR_ROWS')
        if any(r['decision_utc']!=decision_utc or r['prediction_utc']!=snapshot['prediction_generated_at_utc'] or
               r['model_digest']!=snapshot['model_digest'] or r['model_version']!=snapshot['model_version'] or
               r['fixture']!={k:distribution.trace[k] for k in ('league','season','fixture_id','home_team_id','away_team_id','tipoff_utc')} or
               r['policy_sha256']!=POLICY_SHA or r['format']!=VERSION for r in reviews):
            raise ValueError('CURRENT_REVIEW_BATCH_SCOPE_CONFLICT')
        band=prediction_intervals(distribution.forecast)
        if band['sample_sha256']!=snapshot['intervals']['sample_sha256']:raise ValueError('CURRENT_REVIEW_SAMPLE_PIN')
        manifest=dict(format='CURRENT_MARKET_REVIEW_BATCH_V1',policy_sha256=POLICY_SHA,
            original_snapshot_sha256=digest(snapshot),sample_sha256=band['sample_sha256'],
            prediction_utc=snapshot['prediction_generated_at_utc'],decision_utc=decision_utc,
            reviews=deepcopy(reviews),forecast_changed=False,eligible_for_original_forecast_metrics=False)
        if snapshot.get('record_type')=='CURRENT_RESEARCH_ASSESSMENT_V1':
            manifest.update(forecast_record_type=snapshot['record_type'],
                linked_original_snapshot_sha256=snapshot['linked_original_snapshot_sha256'],
                current_assessment_sha256=snapshot['current_assessment_sha256'])
        key=digest(manifest);filename='review-'+key+'.json'
        legacy=local_path(self.root/filename)
        segment=fixture_journal_directory(self.root,snapshot['league'],snapshot['fixture_id'])
        rollover=local_path(segment/filename)
        if legacy.exists() and rollover.exists():
            raise ValueError('CURRENT_REVIEW_DUPLICATE_ARCHIVE_LOCATION')
        path=legacy if legacy.exists() else rollover if rollover.exists() else legacy
        if path.exists():
            if path.stat().st_size>2*1024*1024:raise ValueError('CURRENT_REVIEW_RECORD_SIZE')
            old=json.loads(path.read_text())
            p=old['payload']
            stored={k:v for k,v in p.items() if k not in ('recorded_at_utc','record_class','eligible_for_current_prematch_metrics')}
            if digest(p)!=old['sha256'] or old['manifest_sha256']!=key or stored!=manifest:
                raise ValueError('CURRENT_REVIEW_IMMUTABLE_CONFLICT')
            return old
        archived=int(time.time());cutoff=snapshot['fixture_start_utc']
        for review in reviews:
            clock=review['source'].get('event_clock_binding')
            if clock:cutoff=min(cutoff,clock['payload']['prematch_deadline_utc'])
        payload=dict(manifest,recorded_at_utc=archived,
                     record_class='PREGAME_CURRENT_REVIEW' if archived<cutoff else 'POST_TIPOFF_REVIEW_ONLY',
                     eligible_for_current_prematch_metrics=False)
        body=dict(payload=payload,sha256=digest(payload),manifest_sha256=key)
        size=len((json.dumps(body,sort_keys=True,allow_nan=False)+'\n').encode())
        if size>2*1024*1024:raise ValueError('CURRENT_REVIEW_RECORD_SIZE')
        def full(directory):
            files=list(directory.glob('review-*.json')) if directory.exists() else []
            return len(files)>=256 or sum(local_path(f).stat().st_size for f in files)+size>16*1024*1024
        # Do not delete, relocate or rewrite existing root files. Once a
        # fixture rolls over, keep new records in its own bounded directory.
        if segment.exists() or full(self.root):
            path=rollover
            if full(segment):raise ValueError('CURRENT_REVIEW_STORAGE_BUDGET')
        path.parent.mkdir(parents=True,exist_ok=True);publish_json(path,body)
        return body

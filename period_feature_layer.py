"""Newly materialized period observations; no retrospective availability claims."""
import time
from copy import deepcopy
from prediction_inputs import digest
from prospective_error_audit import period_final


def materialize_period(summary, *, source_observed_utc, source_evidence_sha256, input_ref):
    now=int(time.time())
    if type(source_observed_utc) is not int or not 0<source_observed_utc<=now:
        raise ValueError('invalid source observation time')
    if not isinstance(source_evidence_sha256,str) or len(source_evidence_sha256)!=64 or any(c not in '0123456789abcdef' for c in source_evidence_sha256):
        raise ValueError('source digest required')
    result=period_final(summary,source_observed_utc);event=result['event']
    payload=dict(schema_version=1,provider='ESPN',fixture_id=event['provider_fixture_id'],
        start_utc=event['start_ts_utc'],home_team_id=event['home_team_id'],away_team_id=event['away_team_id'],
        source_url='https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event='+event['provider_fixture_id'],
        source_observed_utc=source_observed_utc,materialized_utc=now,usable_after_utc=max(now,source_observed_utc),
        source_evidence_sha256=source_evidence_sha256,input_ref=deepcopy(input_ref),
        quarters_home=result['periods']['home'][:4],quarters_away=result['periods']['away'][:4],
        regulation=dict(home=result['regulation_home'],away=result['regulation_away'],scope='REGULATION_ONLY'),
        final=dict(home=event['actual_home'],away=event['actual_away'],scope='FINAL_WITH_OT'),
        overtime_home=result['periods']['home'][4:],overtime_away=result['periods']['away'][4:],
        original_summary=deepcopy(summary),usage='NEW_HISTORICAL_FEATURE_NOT_ORIGINAL_FORECAST')
    return dict(payload=payload,sha256=digest(payload))


def _validated_unique(records,prediction_utc):
    selected={};canonical={}
    for record in records:
        p=record['payload']
        if digest(p)!=record['sha256']:raise ValueError('period feature digest mismatch')
        if (type(p.get('schema_version')) is not int or p['schema_version']!=1 or p.get('provider')!='ESPN'
                or p.get('source_url')!='https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event='+p['fixture_id']):
            raise ValueError('period feature schema/source mismatch')
        parsed=period_final(p['original_summary'],p['source_observed_utc'])
        event=parsed['event']
        if (p['fixture_id']!=event['provider_fixture_id'] or p['start_utc']!=event['start_ts_utc']
                or p['home_team_id']!=event['home_team_id'] or p['away_team_id']!=event['away_team_id']
                or p['regulation']!=dict(home=parsed['regulation_home'],away=parsed['regulation_away'],scope='REGULATION_ONLY')
                or p['final']!=dict(home=event['actual_home'],away=event['actual_away'],scope='FINAL_WITH_OT')
                or p['quarters_home']!=parsed['periods']['home'][:4] or p['quarters_away']!=parsed['periods']['away'][:4]
                or p['overtime_home']!=parsed['periods']['home'][4:] or p['overtime_away']!=parsed['periods']['away'][4:]):
            raise ValueError('period feature semantic mismatch')
        if (type(p['materialized_utc']) is not int or not p['source_observed_utc']<=p['materialized_utc']<=int(time.time())
                or p['usable_after_utc']!=max(p['source_observed_utc'],p['materialized_utc'])):
            raise ValueError('invalid feature chronology')
        if prediction_utc is not None and p['usable_after_utc']>=prediction_utc:continue
        key=(p['provider'],p['fixture_id'])
        signature=(p['start_utc'],tuple(sorted((p['home_team_id'],p['away_team_id']))))
        if signature in canonical and canonical[signature]!=key:raise ValueError('ambiguous alias game')
        canonical[signature]=key
        if key in selected:
            prior=selected[key]['payload']
            for field in ('start_utc','home_team_id','away_team_id','regulation','final','quarters_home','quarters_away','overtime_home','overtime_away'):
                if prior[field]!=p[field]:raise ValueError('conflicting period observation')
            if prior['usable_after_utc']<=p['usable_after_utc']:continue
        selected[key]=record
    return sorted(selected.values(),key=lambda r:(r['payload']['start_utc'],r['payload']['fixture_id']))


def select_available(records,prediction_utc):
    if type(prediction_utc) is not int or prediction_utc<=0:raise ValueError('invalid feature cutoff')
    return _validated_unique(records,prediction_utc)


def export_observations(records):
    """Export deduplicated observations, without asserting prediction availability."""
    return _validated_unique(records,None)

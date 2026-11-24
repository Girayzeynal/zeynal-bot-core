"""Explicitly configured, pinned structured rule receipts. No guessed book rules."""
import json
import os
from pathlib import Path
import time

from core.team_identity import digest
from hybrid_engine.data import local_path
from hybrid_engine.decision_layer import RuleEvidence


class RuleBook:
    def __init__(self,path=None,sha256=None):
        self.path=local_path(path) if path else None;self.pin=sha256
        if bool(self.path)!=bool(self.pin):raise ValueError('RULE_MANIFEST_AND_TRUSTED_PIN_REQUIRED')

    @classmethod
    def configured(cls):
        return cls(os.getenv('ZEYNAL_TEST_RULE_MANIFEST'),os.getenv('ZEYNAL_TEST_RULE_MANIFEST_SHA256'))

    def rules(self,asof_utc=None):
        if self.path is None:return {}
        now=int(time.time()) if asof_utc is None else asof_utc
        if type(now) is not int or not 0<now<=int(time.time()):raise ValueError('RULE_ACTUAL_CLOCK_REQUIRED')
        if self.path.stat().st_size>1024*1024:raise ValueError('RULE_MANIFEST_SIZE')
        w=json.loads(self.path.read_text());p=w['payload']
        if w['sha256']!=self.pin or digest(p)!=self.pin or p['format']!='CONFIGURED_RULE_RECEIPTS_V1':
            raise ValueError('RULE_MANIFEST_TRUSTED_PIN')
        if not isinstance(p['entries'],list) or len(p['entries'])>128:raise ValueError('RULE_ENTRY_BUDGET')
        result={}
        for entry in p['entries']:
            r=entry['receipt']
            rule=RuleEvidence.admit(r,expected_url=entry['expected_url'],trusted_document_sha256=entry['document_sha256'])
            q=rule.payload
            if not 0<q['observed_at_utc']<=q['ingested_at_utc']<=now or q['effective_from_utc']>now:
                continue
            if q['effective_until_utc'] is not None and now>=q['effective_until_utc']:continue
            key=tuple(q[k] for k in ('bookmaker_id','league','period','market'))
            if key in result:raise ValueError('RULE_AMBIGUOUS_SCOPE')
            result[key]=rule
        return result

    def status(self):
        try:return 'CONFIGURED_RECEIPTS_'+str(len(self.rules())) if self.path else 'NOT_CONFIGURED_NO_RULE_ASSUMED'
        except (ValueError,KeyError,TypeError,OSError):return 'INVALID_CONFIGURED_RULE_RECEIPTS'


def for_bridge(bridge,asof_utc):
    book=getattr(bridge,'rule_book',None)
    return {} if book is None else book.rules(asof_utc)


def evaluate_bound(bridge,observation,distribution,context,*,asof_utc,native_quotes):
    from hybrid_engine.current_market_review import evaluate
    from hybrid_engine.time_policy import MAXIMUM_V3_MODEL_AGE_SECONDS
    # Legacy first-forecast review retains its historical six-hour policy.
    # Only a verified current-research assessment uses the new 24-hour ceiling.
    current_v3=context.get('record_type')=='CURRENT_RESEARCH_ASSESSMENT_V1'
    model_age_limit=MAXIMUM_V3_MODEL_AGE_SECONDS if current_v3 else 21600
    cutoff=context.get('parameter_fit_cutoff_utc')
    age=asof_utc-cutoff if type(cutoff) is int else None
    issue=('MODEL_FIT_CUTOFF_UNKNOWN' if age is None else
           'MODEL_PARAMETERS_STALE' if not 0<=age<=model_age_limit else None)
    rules_issue=None
    try:
        rules=for_bridge(bridge,asof_utc)
    except (ValueError,KeyError,TypeError,OSError):
        # A broken optional contract registry cannot invalidate independent
        # native quote evidence or normal-time paths. Never infer a rule.
        rules={};rules_issue='CONFIGURED_SETTLEMENT_RULES_INVALID'
    result=evaluate(observation,distribution,asof_utc=asof_utc,native_quotes=native_quotes,rules=rules if not issue else {})
    if rules_issue:
        for row in result['rows']:
            row['reasons'].append(rules_issue)
    result['parameter_fit_age_seconds']=age
    result['model_fit_age_limit_seconds']=model_age_limit
    result['research_record_type']='CURRENT_RESEARCH_ASSESSMENT_V1' if current_v3 else 'FIRST_OR_LEGACY_REVIEW'
    if issue:
        for row in result['rows']:
            row['reasons'].insert(0,issue);row['status']=issue
    return result

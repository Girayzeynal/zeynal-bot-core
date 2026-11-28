"""Immutable rotation-specific point-direction observations.

Reuse native provider documents, not legacy V1/V3 model directions.
No network, odds recommendation, probability or coefficient mutation.
Only independently configured regulation settlement rules admit a result.
"""
import time
from collections import Counter
from pathlib import Path
import math
from core.team_identity import digest
from hybrid_engine.data import local_path
from hybrid_engine.rotation_periods import read
from hybrid_engine.rotation_report import actual_periods
from hybrid_engine.provider_bridge import ProviderBridge,odds_observations
from hybrid_engine.current_market_review import admit_odds,fixture_journal_directory
from hybrid_engine.provider_identity import archived_price_clock
from hybrid_engine.decision_layer import RuleEvidence,settled_value,POLICY
from hybrid_engine.rotation_direction_policy import action
from hybrid_engine.time_policy import PREMATCH_MINIMUM_LEAD_SECONDS
from hybrid_engine.boxes import publish_json
from hybrid_engine.sqlite_read_guard import error_reason

VERSION='ROTATION_POINT_DIRECTION_V1'
PREFIX='rotation-direction-'
MAX_FILES=512
AXIS={'TOTAL':'total','HOME':'home','AWAY':'away','HOME_HANDICAP':'margin','WINNER':'margin'}

def direction(mean,line,market):
    if market not in AXIS or not math.isfinite(mean) or not math.isfinite(line):
        raise ValueError('ROTATION_DIRECTION_VALUE')
    boundary=-line if market=='HOME_HANDICAP' else line
    return 'over' if mean>boundary else 'under' if mean<boundary else 'none'

def build(raw,snapshot,bridge,discovery_pin,detail_pin,decision):
    g,mtime,pin,p,row=raw
    if (type(decision) is not int or not g<=mtime<=decision<row['fixture_start_utc']-PREMATCH_MINIMUM_LEAD_SECONDS
        or p['original_snapshot_sha256']!=digest(snapshot) or row['snapshot_sha256']!=digest(snapshot)
        or row['fixture_id']!=snapshot['fixture_id'] or p['fixture_start_utc']!=snapshot['fixture_start_utc']
        or p['calibrated'] or p['forecast_changed'] or p['production_enabled']):
        raise ValueError('ROTATION_DIRECTION_RAW_BINDING')
    discovery=bridge.read_receipt(discovery_pin);detail=bridge.read_receipt(detail_pin)
    if digest(discovery)!=discovery_pin or digest(detail)!=detail_pin:raise ValueError('ROTATION_DIRECTION_SOURCE_PIN')
    with archived_price_clock(decision):
        observations,_=odds_observations(detail,snapshot,discovery=discovery)
        rules=bridge.rule_book.rules(decision)
        rows=[];seen=set();deadline=row['fixture_start_utc']
        for obs in observations:
            source=obs['payload']['source'];binding=source['event_clock_binding']
            cutoff=binding['payload']['prematch_deadline_utc'];deadline=min(deadline,cutoff)
            stamps=(source['published_at_utc'],source['captured_at_utc'],obs['payload']['available_at_utc'],decision)
            if (digest(binding['payload'])!=binding['sha256'] or not all(type(v) is int for v in stamps)
                or not 0<stamps[0]<=stamps[1]<=stamps[2]<=stamps[3]<cutoff-PREMATCH_MINIMUM_LEAD_SECONDS
                or decision-stamps[0]>POLICY['quote_max_age_seconds'] or decision-stamps[1]>POLICY['quote_max_age_seconds']):continue
            for q in admit_odds(obs,snapshot,discovery,detail):
                v=q.payload;k=(v['bookmaker_id'],v['period'],v['market'],v['line'])
                if k in seen:continue
                seen.add(k)
                if v['market'] not in AXIS or v['period'] not in p['simulation']['markets'] or not float(2*v['line']).is_integer():continue
                if set(v['prices'])!={'under','over'}:continue
                mean=p['simulation']['markets'][v['period']][AXIS[v['market']]]['mean']
                side=direction(mean,v['line'],v['market'])
                rule=rules.get((v['bookmaker_id'],row['league'],v['period'],v['market']))
                reason='SETTLEMENT_RULE_UNVERIFIED';rule_pin=None
                if isinstance(rule,RuleEvidence):
                    rp=rule.payload;RuleEvidence.validate(rp)
                    if (digest(rp)!=rule.sha256 or
                        (rp['bookmaker_id'],rp['league'],rp['period'],rp['market'])!=(v['bookmaker_id'],row['league'],v['period'],v['market'])
                        or not 0<rp['observed_at_utc']<=rp['ingested_at_utc']<=decision
                        or rp['effective_from_utc']>decision or rp['effective_until_utc'] is not None and decision>=rp['effective_until_utc']):
                        raise ValueError('ROTATION_DIRECTION_RULE_PIN')
                    rule_pin=rule.sha256
                    reason='OVERTIME_MODEL_UNAVAILABLE' if rp['include_overtime'] else 'NO_DISTINCT_POINT_DIRECTION' if side=='none' else 'VERIFIED_REGULATION_POINT_DIRECTION'
                rows.append(dict(bookmaker_id=v['bookmaker_id'],period=v['period'],market=v['market'],line=v['line'],
                    quote_sha256=q.sha256,observation_sha256=obs['sha256'],rule_sha256=rule_pin,
                    point_mean=mean,point_direction=side,status=reason))
    if not rows:raise ValueError('ROTATION_DIRECTION_NO_FRESH_NATIVE_QUOTES')
    return dict(format=VERSION,fixture_id=row['fixture_id'],season=row['season'],raw_receipt_sha256=pin,
        original_snapshot_sha256=digest(snapshot),raw_generated_at_utc=g,decision_utc=decision,
        deadline_utc=deadline,discovery_pin=discovery_pin,detail_pin=detail_pin,rows=rows,
        calibrated=False,forecast_changed=False,production_enabled=False)

def source_pairs(root,snapshot,now):
    # Existing market journals are locators only. Native documents are replayed.
    from hybrid_engine.market_direction_results import read_wrapper
    journal=root/'current-market-reviews'
    segment=fixture_journal_directory(journal,snapshot['league'],snapshot['fixture_id'])
    paths=list(journal.glob('review-*.json'))+list(segment.glob('review-*.json'))
    if len(paths)>1024:raise ValueError('ROTATION_DIRECTION_LOCATOR_BUDGET')
    found=set()
    for path in paths:
        try:
            if path.stat().st_mtime<now-600:continue
            w=read_wrapper(path);p=w['payload']
            native=p['native_price_context']
            if digest(native)!=digest(snapshot):continue
            for r in p['reviews']:
                s=r['source'];cp=s['event_clock_binding']['payload']
                if s['provider_id']=='THE_ODDS_API' and 0<=now-s['captured_at_utc']<=POLICY['quote_max_age_seconds']:
                    found.add((s['captured_at_utc'],cp['discovery_receipt_sha256'],s['receipt_sha256']))
        except (ValueError,KeyError,TypeError,OSError,AttributeError):continue
    return sorted(found,reverse=True)

def capture(folder,raw,snapshot,bridge):
    folder=local_path(folder);now=int(time.time())
    if raw[4]['actual'] is not None or now>=raw[4]['fixture_start_utc']-PREMATCH_MINIMUM_LEAD_SECONDS:return 'HOLD_CLOSED'
    # One immutable observation per raw forecast + source pair + rule state.
    # Existing decisions remain available for first-decision audit.
    for _,d,s in source_pairs(folder.parent,snapshot,now):
        try:p=build(raw,snapshot,bridge,d,s,now)
        except (ValueError,KeyError,TypeError,OSError):continue
        key=digest(dict(raw=raw[2],discovery=d,detail=s,rules=[(v['quote_sha256'],v['rule_sha256'],v['status']) for v in p['rows']]))
        path=folder/(PREFIX+key+'.json')
        if path.exists():return 'ALREADY_RECORDED'
        if len(list(folder.glob(PREFIX+'*.json')))>=MAX_FILES:return 'HOLD_STORAGE_BUDGET'
        if int(time.time())>=p['deadline_utc']-PREMATCH_MINIMUM_LEAD_SECONDS:return 'HOLD_CLOSED'
        publish_json(path,dict(payload=p,sha256=digest(p)))
        completed=int(time.time())
        proof=dict(payload_sha256=digest(p),completed_at_utc=completed,eligible=completed<p['deadline_utc']-PREMATCH_MINIMUM_LEAD_SECONDS)
        publish_json(folder/('direction-commit-'+key+'.json'),dict(payload=proof,sha256=digest(proof)))
        return 'CAPTURED_DIRECTION_OBSERVATION' if proof['eligible'] else 'HOLD_CLOSED'
    return 'HOLD_NO_FRESH_NATIVE_QUOTES'

def audit(folder,entries,now,bridge=None,ledger=None):
    from hybrid_engine.player_inputs import load_snapshot
    from hybrid_engine.market_direction_results import read_wrapper
    folder=local_path(folder)
    bridge=bridge or ProviderBridge(None,folder.parent/'provider-evidence')
    ledger=ledger or folder.parent/'live-nba/nba-hybrid.sqlite'
    by={e[2]:e for e in entries};chosen={};excluded=Counter()
    paths=sorted(folder.glob(PREFIX+'*.json'))
    if len(paths)>MAX_FILES:raise ValueError('ROTATION_DIRECTION_SCAN_BUDGET')
    for path in paths:
        try:
            w=read_wrapper(path);p=w['payload'];t=by[p['raw_receipt_sha256']]
            g=p['decision_utc'];key=path.stem.removeprefix(PREFIX)
            proof_path=folder/('direction-commit-'+key+'.json')
            proof=read_wrapper(proof_path,65536)['payload'];completed=proof['completed_at_utc']
            if (type(g) is not int or type(completed) is not int or not g<=path.stat().st_mtime<completed+1
                or not g<=completed<=now or not completed<=proof_path.stat().st_mtime<p['deadline_utc']-PREMATCH_MINIMUM_LEAD_SECONDS
                or proof['eligible'] is not True or proof['payload_sha256']!=w['sha256']):
                raise ValueError('ROTATION_DIRECTION_DURABLE_CLOCK')
            snapshot=load_snapshot(ledger,t[4]['fixture_id'],verified_row=t[4])
            if build(t,snapshot,bridge,p['discovery_pin'],p['detail_pin'],g)!=p:raise ValueError('ROTATION_DIRECTION_REPLAY')
            for v in p['rows']:
                scope=(p['fixture_id'],v['bookmaker_id'],v['period'],v['market'],v['line'])
                order=(g,completed,w['sha256'])
                if scope not in chosen or order<chosen[scope][0]:chosen[scope]=(order,v,t)
        except (ValueError,KeyError,TypeError,OSError,AttributeError,IndexError) as exc:excluded[error_reason(exc)]+=1
    counts=Counter();fixtures=set();failures=[]
    for _,v,t in chosen.values():
        row=t[4];fixtures.add(row['fixture_id'])
        if v['status']!='VERIFIED_REGULATION_POINT_DIRECTION':counts[v['status']]+=1;continue
        if actual_periods(row,now) is None:counts['PENDING_FINAL']+=1;continue
        actual=settled_value(row['actual_periods'],v['period'],v['market'],include_overtime=False)
        side=direction(actual,v['line'],v['market'])
        outcome='PUSH' if side=='none' else 'WIN' if side==v['point_direction'] else 'LOSS'
        counts[outcome]+=1
        if action(outcome,verified=True)=='INVESTIGATE_FAILURE':
            failures.append(dict(fixture_id=row['fixture_id'],home=row['home'],away=row['away'],
                period=v['period'],market=v['market'],line=v['line'],bookmaker_id=v['bookmaker_id'],
                direction=v['point_direction'],actual=actual,point_mean=v['point_mean'],
                cause='UNDETERMINED_REQUIRES_EVIDENCE'))
    return dict(fixtures=len(fixtures),observations=len(chosen),counts=dict(counts),excluded=dict(excluded),failures=failures)

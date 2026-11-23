"""Explicit offline prospective challenger experiment, separate from live records.

Register before fresh captures, publish before tipoff, join only native finals.
Never tunes weights/calibration on the development 18 games or sends Telegram.
"""
import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import time

from core.team_identity import digest
from hybrid_engine.boxes import publish_json
from hybrid_engine.challenger_review import predict_snapshot, source_pins, summarize_cases, metric_row, paired_row
from hybrid_engine.data import local_path
from hybrid_engine.forward_nba_results import read_confirmed
from hybrid_engine.forward_validation import ForwardRegistry
from hybrid_engine.statistics import paired_cluster_interval
from ledger_reports import LedgerReports

FORMAT = 'PREREGISTERED_CHALLENGER_PROTOCOL_V1'
POLICY = dict(primary='UPDATED_BAYES_STOCHASTIC_PERIODS', baseline='FAZ13_REFERENCE',
    primary_metric='team_mae', minimum_future_games=100, minimum_day_clusters=20,
    minimum_relative_improvement=.02, minimum_primary_coverage=.8,
    maximum_feature_age_seconds=3600, minimum_lead_seconds=900,
    candidate_selection='ALL_ELIGIBLE_FIRST_PUBLICATIONS_CHRONOLOGICAL_NO_RESULT_SELECTION',
    development_data='PRE_REGISTRATION_RECORDS_CANNOT_ENTER_CONFIRMATORY_COHORT',
    calibration_fit=False, automatic_promotion=False)


def load_plan(directory, *, now=None):
    root = local_path(directory); now = int(time.time()) if now is None else now
    paths = list(root.glob('plan-*.json'))
    if len(paths) != 1: raise ValueError('ONE_EXISTING_CHALLENGER_PROTOCOL_REQUIRED')
    path = local_path(paths[0])
    if path.stat().st_size > 128*1024: raise ValueError('CHALLENGER_PROTOCOL_BUDGET')
    w = json.loads(path.read_text()); p = w['payload']
    if (w['sha256'] != digest(p) or path.stem != 'plan-'+w['sha256'] or p['format'] != FORMAT or
            p['policy'] != POLICY or p['source_pins'] != source_pins() or
            type(p['registered_at_utc']) is not int or not 0 < p['registered_at_utc'] <= now or
            p['production_enabled'] is not False):
        raise ValueError('CHALLENGER_PROTOCOL_PIN_CLOCK_OR_POLICY')
    return w


def register(directory):
    root = local_path(directory)
    if list(root.glob('plan-*.json')): return load_plan(root), False
    p = dict(format=FORMAT, registered_at_utc=int(time.time()), policy=POLICY,
        source_pins=source_pins(), production_enabled=False)
    w = dict(payload=p, sha256=digest(p)); root.mkdir(parents=True, exist_ok=True)
    publish_json(root/('plan-'+w['sha256']+'.json'), w)
    return load_plan(root), True


def admission(snapshot, plan, now):
    if any(type(snapshot.get(k)) is not int or snapshot[k] <= 0 for k in
           ('fixture_start_utc','feature_cutoff_utc','prediction_generated_at_utc')):
        return 'ORIGINAL_CUTOFF_UNAVAILABLE_OR_INVALID'
    if now >= snapshot['fixture_start_utc']: return 'MATCH_ALREADY_STARTED'
    if snapshot['feature_cutoff_utc'] < plan['payload']['registered_at_utc']: return 'ORIGINAL_CAPTURE_PRECEDES_PROTOCOL'
    if not snapshot['feature_cutoff_utc'] <= snapshot['prediction_generated_at_utc'] <= now: return 'INVALID_ORIGINAL_CAPTURE_CLOCK'
    if snapshot['fixture_start_utc']-now < POLICY['minimum_lead_seconds']: return 'INSUFFICIENT_PRETIPOFF_LEAD'
    if now-snapshot['feature_cutoff_utc'] > POLICY['maximum_feature_age_seconds']: return 'ORIGINAL_INPUTS_TOO_OLD_FOR_PROTOCOL'
    return None


def capture(ledger, assets, directory, *, maximum=4, admission_seconds=180.):
    if type(maximum) is not int or not 1 <= maximum <= 8 or not 1 <= admission_seconds <= 600:
        raise ValueError('BOUNDED_CHALLENGER_FORWARD_BATCH_REQUIRED')
    root = local_path(directory); plan = load_plan(root); now = int(time.time())
    reports = LedgerReports(local_path(ledger)).read('NBA')
    # No calibration/fit is performed while merely validating the source ledger.
    existing = ForwardRegistry(root/'forecasts')
    prior = {r['payload']['fixture']['canonical_id'] for r in existing.records()
             if r['payload']['version'] == plan['sha256']}
    originals = {r['snapshot_sha256']: r for r in reports['forecasts']}
    records = sorted(read_confirmed(ledger), key=lambda r:(r['snapshot']['fixture_start_utc'],r['snapshot']['fixture_id']))
    counts=Counter(r['snapshot']['fixture_id'] for r in records)
    results = []; selected = []; skips = {}; began = time.monotonic()
    for r in records:
        p = r['snapshot']; original = originals[r['snapshot_sha256']]
        reason = 'RESULT_ALREADY_AVAILABLE' if original['actual'] is not None else admission(p,plan,now)
        if counts[p['fixture_id']] != 1: reason='AMBIGUOUS_ORIGINAL_MODEL'
        if not p['created_at_utc'] <= original['first_archived_at_utc'] <= now: reason='ORIGINAL_COMMIT_CLOCK_INVALID'
        if p['fixture_id'] in prior: reason = 'ALREADY_PUBLISHED_UNDER_PROTOCOL'
        if reason:
            skips[reason] = skips.get(reason,0)+1; continue
        selected.append(r)
    for r in selected[:maximum]:
        if time.monotonic()-began >= admission_seconds: break
        p = r['snapshot']; reason = admission(p,plan,int(time.time()))
        if reason: results.append(dict(fixture_id=p['fixture_id'],status='BLOCKED',reason=reason)); continue
        try:
            e = predict_snapshot(p,assets)
            body = dict(record_type='PROSPECTIVE_CHALLENGER_RESEARCH_NOT_ACTIVE_MODEL',
                fixture=dict(canonical_id=p['fixture_id'],start_ts_utc=p['fixture_start_utc'],
                    provider_fixture_ids=p['provider_fixture_ids'],league=p['league'],season=p['season']),
                version=plan['sha256'], actual=None, assets=[existing.asset('original-snapshot',p), existing.asset('protocol',plan)],
                source_available_max_utc=max(e['history_available_max_utc'],p['source_data_time_utc']),
                prediction_generated_at_utc=int(time.time()), original_snapshot_sha256=r['snapshot_sha256'],
                original_input_cutoff_utc=e['prediction_cutoff_utc'],experiment=e,
                confidence_index=None,calibration_status='NOT_CALIBRATED',production_enabled=False)
            saved,new = existing.record(body)
            results.append(dict(fixture_id=p['fixture_id'],status='ARCHIVED' if new else 'REPLAY_EXISTING',
                forecast_sha256=digest(saved),protocol_sha256=plan['sha256']))
        except (ValueError,KeyError,TypeError,OSError,RuntimeError) as exc:
            results.append(dict(fixture_id=p['fixture_id'],status='BLOCKED',error_type=type(exc).__name__,
                reason='SOURCE_OR_CANDIDATE_VALIDATION_FAILED_NO_ACTIVE_RECORD_REPLACED'))
    return dict(format='PROSPECTIVE_CHALLENGER_BATCH_V1',protocol_sha256=plan['sha256'],
        eligible=len(selected),results=results,remaining=len(selected)-len(results),skipped=skips,
        budget_scope='CHECKED_BETWEEN_FIXTURES_NOT_HARD_DEADLINE',admission_budget_seconds=admission_seconds,
        active_predictions_replaced=False,production_changed=False,online_training=False,
        inference_location='EXPLICIT_OFFLINE_CLI_NOT_TELEGRAM_REQUEST',calibration_fit=False)


def performance(ledger, directory):
    root = local_path(directory); plan = load_plan(root)
    # A source-ledger correction or malformed final is rejected by this existing reader.
    rows = LedgerReports(local_path(ledger)).read('NBA')['forecasts']
    by_pin = {r['snapshot_sha256']:r for r in rows}
    cases = []; pending = 0; exclusions = {}
    for item in ForwardRegistry(root/'forecasts').records():
        p = item['payload']; pub = item['publication']; key = p['original_snapshot_sha256']
        if p['version'] != plan['sha256']: raise ValueError('CHALLENGER_RECORD_PROTOCOL_CONFLICT')
        original = by_pin.get(key)
        if original is None or p['fixture']['canonical_id'] != original['fixture_id'] or p['fixture']['start_ts_utc'] != original['fixture_start_utc']:
            raise ValueError('CHALLENGER_RESULT_ORIGINAL_IDENTITY')
        if (p['experiment']['snapshot_sha256'] != key or p['original_input_cutoff_utc'] != p['experiment']['prediction_cutoff_utc'] or
                p['experiment']['history_available_max_utc'] > p['original_input_cutoff_utc'] or
                not plan['payload']['registered_at_utc'] <= p['original_input_cutoff_utc'] <= p['prediction_generated_at_utc'] <=
                    pub['first_archived_at_utc'] < original['fixture_start_utc'] or not pub['eligible_for_prospective_audit']):
            exclusions['PROTOCOL_OR_PREMATCH_CLOCK_FAILED'] = exclusions.get('PROTOCOL_OR_PREMATCH_CLOCK_FAILED',0)+1; continue
        if original['actual'] is None: pending+=1; continue
        if original['label_available_utc'] > int(time.time()): pending+=1; continue
        r = deepcopy(original); r['prediction_generated_at_utc'] = p['prediction_generated_at_utc']
        cases.append(dict(original=r,experiment=p['experiment']))
    groups = summarize_cases(cases)
    for g in groups:
        comparison = g['paired'][POLICY['baseline']][POLICY['primary']]
        matched=[c for c in cases if c['original']['model_digest']==g['cohort']['original_model_digest'] and
            c['original']['model_version']==g['cohort']['original_model_version'] and
            c['original']['league']==g['cohort']['league'] and c['original']['season']==g['cohort']['season'] and
            c['experiment']['components'][POLICY['baseline']]['status']=='AVAILABLE' and
            c['experiment']['components'][POLICY['primary']]['status']=='AVAILABLE']
        # ONE preregistered candidate/metric; do not select among the exploratory
        # panel's many intervals after seeing results. Other metrics stay descriptive.
        primary=paired_cluster_interval(
            [paired_row(metric_row(c['original'],c['experiment']['components'][POLICY['baseline']])) for c in matched],
            [paired_row(metric_row(c['original'],c['experiment']['components'][POLICY['primary']])) for c in matched],family_size=1)
        metric = primary.get('metrics',{}).get(POLICY['primary_metric'],{})
        interval = metric.get('interval')
        sufficient = comparison['n_common'] >= POLICY['minimum_future_games'] and g['day_clusters'] >= POLICY['minimum_day_clusters']
        coverage = comparison['n_common']/g['n'] if g['n'] else 0.
        qualifies = sufficient and coverage >= POLICY['minimum_primary_coverage'] and interval is not None and interval[1] < 0 and metric['candidate'] <= (1-POLICY['minimum_relative_improvement'])*metric['baseline']
        g['primary_statistical_gate'] = 'PASS_REQUIRES_SEPARATE_RELEASE_REVIEW' if qualifies else 'NOT_PROVEN'
        g['primary_policy'] = POLICY
        g['preregistered_primary_interval']=dict(metric=POLICY['primary_metric'],n=primary['n'],
            day_clusters=primary['day_clusters'],result=metric,scope='ONLY_THE_SINGLE_PREREGISTERED_PRIMARY_COMPARISON',
            dependence_limit='CROSS_DAY_REPEATED_TEAM_DEPENDENCE_NOT_FULLY_MODELED')
    return dict(format='PREREGISTERED_CHALLENGER_RESULTS_V1',protocol_sha256=plan['sha256'],groups=groups,
        settled=len(cases),pending=pending,exclusions=exclusions,confidence_index=None,calibration_fit=False,
        production_changed=False,automatic_promotion=False,release_decision='NO_GO_WITHOUT_SEPARATE_ACCEPTANCE_AND_APPROVAL')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=('plan','capture','results'))
    p.add_argument('--directory',required=True);p.add_argument('--ledger');p.add_argument('--assets-directory');a=p.parse_args()
    try:
        root=local_path(a.directory)
        if a.ledger:
            protected=local_path(a.ledger).parent
            if root == protected or protected in root.parents: raise ValueError('SEPARATE_CHALLENGER_DIRECTORY_REQUIRED')
        if a.action=='plan':
            w,new=register(root);r=dict(status='REGISTERED' if new else 'EXISTING',protocol_sha256=w['sha256'],
                registered_at_utc=w['payload']['registered_at_utc'],policy=w['payload']['policy'],production_changed=False)
        elif not a.ledger: raise ValueError('EXISTING_LEDGER_REQUIRED')
        elif a.action=='capture':
            if not a.assets_directory: raise ValueError('ORIGINAL_ASSETS_REQUIRED')
            r=capture(a.ledger,a.assets_directory,root)
            target=root/('batch-'+digest(r)+'.json');publish_json(target,dict(payload=r,sha256=digest(r)))
            r=dict(r,path=str(target))
        else:
            r=performance(a.ledger,root); target=root/('results-'+digest(r)+'.json')
            publish_json(target,dict(payload=r,sha256=digest(r)));r=dict(path=str(target),settled=r['settled'],pending=r['pending'],
                protocol_sha256=r['protocol_sha256'],release_decision=r['release_decision'],production_changed=False)
        print(json.dumps(r,sort_keys=True,allow_nan=False));return 0
    except (ValueError,KeyError,TypeError,OSError,RuntimeError) as exc:
        print(json.dumps(dict(status='BLOCKED',error_type=type(exc).__name__,
            reason='CHALLENGER_PROTOCOL_OPERATION_INCOMPLETE_NO_ACTIVE_FORECAST_CHANGED',production_changed=False)));return 2


if __name__=='__main__': raise SystemExit(main())

"""Offline same-input challengers. Historical replays are never PREMATCH records.

Reuse the existing hierarchy, Faz13, possession and quarter samplers. Labels are
joined only after inference. No live provider, Telegram handler or active model
uses this module. Updated posteriors are not a single calibrated parameter fit.
"""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from core.team_identity import digest
from hybrid_engine.archive_audit import audit_ledger, file_sha
from hybrid_engine.boxes import publish_json
from hybrid_engine.data import STRICT, Abstain, Cut, available_at, local_path
from hybrid_engine.distributions import Budget
from hybrid_engine.evaluation import v1_forecast
from hybrid_engine.forecast_error_review import review as select_first
from hybrid_engine.forward_nba_results import read_confirmed
from hybrid_engine.intervals import prediction_intervals
from hybrid_engine.live_metrics import metrics
from hybrid_engine.posterior_refresh import refresh
from hybrid_engine.live_nba import PreparedBayes
from hybrid_engine.possession import PossessionModel
from hybrid_engine.prediction_audit import Assets, audit_snapshot
from hybrid_engine.quarter_shadow import predict as quarter_predict
from hybrid_engine.research_candidates import feature_readiness
from hybrid_engine.statistics import paired_cluster_interval, paired_winner_interval

VERSION = 'SAME_INPUT_OFFLINE_CHALLENGERS_V1'
NAMES = ('FROZEN_ARCHIVED', 'FAZ13_REFERENCE', 'UPDATED_BAYES_QMC',
         'UPDATED_BAYES_MC', 'UPDATED_BAYES_STOCHASTIC_PERIODS',
         'POSSESSION_ANALYTIC', 'POSSESSION_MC')


def source_pins():
    root = Path(__file__).parent
    names = ('challenger_review.py', 'models.py', 'data.py', 'distributions.py',
             'evaluation.py', 'possession.py', 'quarter_shadow.py', 'posterior_refresh.py', 'challenger_forward.py',
             'prediction_audit.py', 'research_candidates.py', 'statistics.py',
             'intervals.py', 'live_metrics.py', 'forecast_error_review.py',
             'live_nba.py', 'forward_validation.py', 'forward_nba_results.py',
             'archive_audit.py', 'quality_monitor.py', 'availability.py', 'boxes.py', 'markets.py',
             '../ledger_reports.py', '../live_analysis_ledger.py',
             '../historical_research.py', '../prematch_monte_carlo.py')
    return {name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in names}


def predict_snapshot(snapshot, directory):
    """Predictors receive the original snapshot/assets, NEVER the target result."""
    audit = audit_snapshot(snapshot, directory)
    cut = Cut(**Assets(directory).read(snapshot['input_asset']))
    if cut.evaluation_class != STRICT or cut.cutoff_utc > snapshot['prediction_generated_at_utc']:
        raise ValueError('CHALLENGER_STRICT_ORIGINAL_CUTOFF_REQUIRED')
    if any(r['fixture_id'] == snapshot['fixture_id'] or available_at(r, STRICT) > cut.cutoff_utc
           for r in cut.history):
        raise ValueError('CHALLENGER_HISTORY_LEAKAGE')
    readiness = feature_readiness(cut)
    result = {'FROZEN_ARCHIVED': dict(status='AVAILABLE', prediction=deepcopy(snapshot['prediction']),
        intervals=deepcopy(snapshot['intervals']), parameter_fit_cutoff_utc=snapshot['parameter_fit_cutoff_utc'],
        fit_sha256=snapshot['prepared_artifact_sha256'], elapsed_seconds=0.,
        publication_kind='ORIGINAL_ARCHIVED_PREMATCH_NOT_REPLACED')}
    budget = Budget(seconds=5.)
    bayes = None; update_trace = None
    began = time.perf_counter()
    try:
        # The original posterior retains the full old fit; only distinct native
        # recent games are added. This is NOT a full league refit or new noise fit.
        prepared = PreparedBayes(Assets(directory).root/snapshot['prepared_asset']['file'],
            trusted_sha256=snapshot['prepared_artifact_sha256'])
        bayes, update_trace = refresh(prepared, cut)
    except Abstain as exc:
        for name in NAMES[2:5]: result[name] = dict(status='ABSTAIN', reason=str(exc))
    fit_seconds = time.perf_counter()-began
    jobs = {'FAZ13_REFERENCE': lambda: v1_forecast(cut)}
    if bayes is not None:
        jobs.update(UPDATED_BAYES_QMC=lambda: bayes.predict(cut, budget=budget, method='RQMC_HALTON', bounded_workspace=True),
            UPDATED_BAYES_MC=lambda: bayes.predict(cut, budget=budget, method='MC', bounded_workspace=True))
    if readiness['possession_readiness'] == 'ELIGIBLE_FOR_OFFLINE_COMPARISON':
        for method in ('ANALYTIC', 'MC'):
            jobs['POSSESSION_'+method] = lambda method=method: PossessionModel().predict(cut, budget=budget, method=method)
    else:
        for name in NAMES[-2:]: result[name] = dict(status='ABSTAIN', reason=readiness['possession_readiness'])
    for name, job in jobs.items():
        start = time.perf_counter()
        try:
            f = job()
            result[name] = dict(status='AVAILABLE', prediction=f.summary(), intervals=prediction_intervals(f),
                elapsed_seconds=time.perf_counter()-start,
                parameter_fit_cutoff_utc=(f.metadata or {}).get('fit_cutoff_utc'),
                fit_sha256=(f.metadata or {}).get('artifact_digest'),
                publication_kind='RECOMPUTED_RESEARCH_NOT_ORIGINAL_PREMATCH')
            if name == 'UPDATED_BAYES_QMC':
                try:
                    shadow = quarter_predict(f, cut)
                    result['UPDATED_BAYES_STOCHASTIC_PERIODS'] = dict(status='AVAILABLE', prediction=shadow.summary(),
                        intervals=prediction_intervals(shadow), parameter_fit_cutoff_utc=cut.cutoff_utc,
                        fit_sha256=bayes.artifact_digest, elapsed_seconds=time.perf_counter()-start,
                        publication_kind='RECOMPUTED_RESEARCH_NOT_ORIGINAL_PREMATCH')
                except Abstain as exc:
                    result['UPDATED_BAYES_STOCHASTIC_PERIODS'] = dict(status='ABSTAIN', reason=str(exc))
        except Abstain as exc:
            result[name] = dict(status='ABSTAIN', reason=str(exc))
            if name == 'UPDATED_BAYES_QMC':
                result['UPDATED_BAYES_STOCHASTIC_PERIODS'] = dict(status='ABSTAIN', reason='BASE_QMC_UNAVAILABLE')
    return dict(snapshot_sha256=digest(snapshot), inputs_digest=cut.inputs_digest,
        prediction_cutoff_utc=cut.cutoff_utc, history_available_max_utc=max(available_at(r, STRICT) for r in cut.history),
        training_ids=[] if bayes is None else bayes.training_ids, posterior_update=update_trace, training_fit_seconds=fit_seconds,
        native_audit_status=audit['status'], readiness=readiness, components=result)


def metric_row(original, component):
    """Offline policy aggregation across explicitly tracked fits, NOT live accuracy."""
    p = component['prediction']
    return dict(fixture_id=original['fixture_id'], fixture_start_utc=original['fixture_start_utc'],
        actual=original['actual'], actual_periods=original['actual_periods'],
        label_available_utc=original['label_available_utc'],
        prediction_generated_at_utc=original['prediction_generated_at_utc'],
        prediction=[p['home'], p['away']], predicted_quarters=p['quarters'], predicted_halves=p['halves'],
        winner=p.get('winner'), intervals=component['intervals'])


def paired_row(row):
    q = np.asarray(row['predicted_quarters'])
    h, a = row['prediction']
    return dict(fixture_id=row['fixture_id'], start_utc=row['fixture_start_utc'], actual=row['actual'],
        actual_quarters=np.array([row['actual_periods'][s][:4] for s in ('home', 'away')]).T.tolist(),
        prediction=dict(home=h, away=a, total=h+a, margin=h-a, quarters=q.tolist(), winner=row.get('winner')))


def summarize_cases(cases):
    groups = {}
    for c in cases:
        r = c['original']; key = (r['league'], r['season'], r['model_version'], r['model_digest'])
        groups.setdefault(key, []).append(c)
    output = []
    for key, group in sorted(groups.items()):
        rows = {name: [] for name in NAMES}; blocked = Counter()
        for c in group:
            for name, component in c['experiment']['components'].items():
                if component['status'] == 'AVAILABLE': rows[name].append(metric_row(c['original'], component))
                else: blocked[name+':'+component['reason']] += 1
        comparisons = {}
        for baseline in ('FROZEN_ARCHIVED', 'FAZ13_REFERENCE'):
            b = {r['fixture_id']: r for r in rows[baseline]}
            comparisons[baseline] = {}
            for name in NAMES:
                if name == baseline: continue
                common = sorted(set(b)&{r['fixture_id'] for r in rows[name]})
                left = [b[fid] for fid in common]; right = [r for r in rows[name] if r['fixture_id'] in common]
                comparisons[baseline][name] = dict(n_common=len(common), fixture_ids=common,
                    baseline=metrics(left), candidate=metrics(right),
                    points=paired_cluster_interval([paired_row(r) for r in left], [paired_row(r) for r in right], family_size=78),
                    winner=paired_winner_interval([paired_row(r) for r in left], [paired_row(r) for r in right]))
        output.append(dict(cohort=dict(zip(('league', 'season', 'original_model_version', 'original_model_digest'), key)),
            n=len(group), day_clusters=len({(c['original']['fixture_start_utc']+10800)//86400 for c in group}),
            models={name: metrics(values) for name, values in rows.items()}, paired=comparisons,
            abstentions=dict(blocked), calibration_status='NOT_CALIBRATED', confidence_index=None,
            aggregation='EXPLORATORY_FIXED_POLICY_ACROSS_TRACKED_UPDATES_NOT_A_CALIBRATION_FIT_COHORT'))
    return output


def run(ledger, assets_directory, *, maximum=24, admission_seconds=180.):
    if type(maximum) is not int or not 1 <= maximum <= 200 or not 1 <= admission_seconds <= 600:
        raise ValueError('CHALLENGER_OFFLINE_BUDGET_REQUIRED')
    path = local_path(ledger); assets = local_path(assets_directory)
    if not path.is_file() or not assets.is_dir(): raise ValueError('CHALLENGER_EXISTING_LEDGER_AND_ASSETS_REQUIRED')
    before = file_sha(path); wal = Path(str(path)+'-wal'); wal_before = file_sha(wal) if wal.exists() else None
    audit = audit_ledger(path)  # Existing bounded native ledger/result validation.
    if audit['sqlite_integrity'] != 'ok' or audit['issues'] or audit['performance'] is None:
        raise ValueError('CHALLENGER_NATIVE_LEDGER_AUDIT_FAILED')
    now = audit['observed_at_utc']; rows = audit['performance']['forecasts']
    selected = select_first(rows, asof_utc=now)
    eligible = {c['snapshot_sha256'] for g in selected['groups'] for c in g['cases']}
    by_pin = {r['snapshot_sha256']: r for r in rows}
    snapshots = read_confirmed(path)
    snapshots = sorted((r for r in snapshots if r['snapshot_sha256'] in eligible),
        key=lambda r: (r['snapshot']['fixture_start_utc'], r['snapshot']['fixture_id'], r['snapshot']['model_digest']))
    cases = []; failures = []; began = time.monotonic()
    for record in snapshots[:maximum]:
        if time.monotonic()-began >= admission_seconds: break
        p = record['snapshot']; start = time.perf_counter()
        try:
            experiment = predict_snapshot(p, assets)
            if experiment['snapshot_sha256'] != record['snapshot_sha256']: raise ValueError('CHALLENGER_SNAPSHOT_PIN')
            cases.append(dict(original=by_pin[record['snapshot_sha256']], experiment=experiment,
                elapsed_seconds=time.perf_counter()-start))
        except (ValueError, KeyError, TypeError, OSError, RuntimeError) as exc:
            failures.append(dict(fixture_id=p['fixture_id'], snapshot_sha256=record['snapshot_sha256'],
                status='BLOCKED', error_type=type(exc).__name__, reason='ORIGINAL_NATIVE_INPUT_OR_CANDIDATE_VALIDATION_FAILED'))
    after = file_sha(path); wal_after = file_sha(wal) if wal.exists() else None
    unchanged = before == after and wal_before == wal_after
    return dict(format=VERSION, generated_at_utc=int(time.time()), source_pins=source_pins(),
        evidence_class='EXPLORATORY_RETROSPECTIVE_ORIGINAL_INPUT_REPLAY_NOT_NEW_PREMATCH',
        development_outcomes_already_inspected=True, fresh_confirmatory_holdout=False,
        eligible=len(snapshots), reviewed=len(cases), blocked=len(failures),
        remaining=len(snapshots)-len(cases)-len(failures), maximum=maximum,
        admission_budget_seconds=admission_seconds, budget_scope='BETWEEN_FIXTURES_NOT_HARD_PROCESS_TIMEOUT',
        groups=summarize_cases(cases), cases=cases, failures=failures, exclusions=selected['exclusions'],
        database_sha256_before=before, database_sha256_after=after, database_bytes_unchanged=before == after,
        database_and_wal_unchanged=unchanged, sqlite_integrity=audit['sqlite_integrity'],
        status=('BLOCKED_CONCURRENT_DATABASE_CHANGE' if not unchanged else
                'REVIEW_WITH_BLOCKS' if failures else 'REVIEW_COMPLETE'),
        predictions_replaced=False, prematch_records_created=0, calibration_fit=False, online_training=False,
        offline_posterior_updates=True, full_league_refit=False, confidence_index=None, production_changed=False,
        acceptance=dict(decision='NO_GO', production_default='FAZ13', superiority_proven=False,
            blockers=['FRESH_PREREGISTERED_DISJOINT_PROSPECTIVE_VALIDATION_REQUIRED',
                'PLAYER_IMPACT_AND_POSSESSION_REQUIRE_VERIFIED_INPUT_COVERAGE',
                'REAL_TELEGRAM_AND_LIVE_PROVIDER_RESOURCE_EVIDENCE_SEPARATE']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger', required=True); parser.add_argument('--assets-directory', required=True)
    parser.add_argument('--output-directory', required=True); parser.add_argument('--maximum', type=int, default=24)
    args = parser.parse_args()
    try:
        root = local_path(args.output_directory)
        # Refuse output into the ledger/assets directory; reports cannot be model inputs.
        protected = (local_path(args.ledger).parent, local_path(args.assets_directory))
        if any(root == p or p in root.parents for p in protected): raise ValueError('CHALLENGER_SEPARATE_REPORT_DIRECTORY_REQUIRED')
        result = run(args.ledger, args.assets_directory, maximum=args.maximum)
        root.mkdir(parents=True, exist_ok=True)
        target = root/('challengers-'+digest(result)+'.json')
        publish_json(target, dict(payload=result, sha256=digest(result)))
        summary = dict(path=str(target), status=result['status'], reviewed=result['reviewed'], blocked=result['blocked'],
            remaining=result['remaining'], database_and_wal_unchanged=result['database_and_wal_unchanged'],
            groups=[dict(cohort=g['cohort'], n=g['n'], day_clusters=g['day_clusters'],
                models={n: dict(n=m['n'], total=m.get('total'), team_scores=m.get('team_scores'),
                    winner=m.get('winner', {}).get('correct'),
                    total_coverage=m.get('coverage', {}).get('TOTAL')) for n, m in g['models'].items()},
                abstentions=g['abstentions']) for g in result['groups']],
            acceptance='NO_GO', actual_telegram_delivery_verified=False, production_changed=False)
        print(json.dumps(summary, sort_keys=True, allow_nan=False))
        return 0 if result['status'] == 'REVIEW_COMPLETE' else 2
    except (ValueError, KeyError, TypeError, OSError, RuntimeError) as exc:
        print(json.dumps(dict(status='BLOCKED', error_type=type(exc).__name__,
            reason='CHALLENGER_REVIEW_INCOMPLETE_NO_ARCHIVE_REPLACED', production_changed=False)))
        return 2


if __name__ == '__main__': raise SystemExit(main())

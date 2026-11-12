"""Strict expanding walk-forward only. No assumed-publication-time escape hatch."""
from collections import Counter
from dataclasses import replace
import hashlib
from pathlib import Path
import time

import numpy as np

from core.team_identity import digest
from hybrid_engine.audit import known_fixture, source_audit
from hybrid_engine.data import STRICT, Abstain, available_at, feature_cut, load_manifest, reference, regulation
from hybrid_engine.distributions import Forecast, gaussian_forecast, quarter_weights
from hybrid_engine.evaluation import Ensemble, serialize_forecast, summarize, v1_forecast
from hybrid_engine.models import BoostedScores, HierarchicalStrength
from hybrid_engine.possession import PossessionModel
from hybrid_engine.statistics import market_metrics, paired_cluster_interval, paired_market_interval
from hybrid_engine.availability import effective_time, effective_box_time

MODELS = ('FAZ13_MC', 'FAZ13_QMC', 'FAZ13_ANALYTIC', 'POSSESSION_MC', 'POSSESSION_ANALYTIC', 'BAYES_QMC', 'LIGHTGBM', 'CATBOOST')
BASELINES = ('LEAGUE_MEAN', 'RECENT_POINTS_FOR')


def rolling_folds(examples):
    times = sorted({e['cut'].cutoff_utc for e in examples})
    if len(times) < 20: raise Abstain('INSUFFICIENT_DISTINCT_KICKOFFS_FOR_WALK_FORWARD')
    validation_width = max(1, int(.2*len(times))); first_test = int(.7*len(times)); step = max(1, int(.1*len(times)))
    for fold, start in enumerate(range(first_test, len(times), step)):
        test_cut = times[start]; validation_cut = times[start-validation_width]
        end = times[min(start+step, len(times))-1]+1
        train = [label_at(e, validation_cut, 'TRAIN') for e in examples if e['cut'].cutoff_utc < validation_cut]
        validation = [label_at(e, test_cut, 'VALIDATION') for e in examples if validation_cut <= e['cut'].cutoff_utc < test_cut]
        train = [e for e in train if e is not None]; validation = [e for e in validation if e is not None]
        test = [dict(e, role='TEST') for e in examples if test_cut <= e['cut'].cutoff_utc < end]
        yield dict(fold=fold, validation_cutoff=validation_cut, test_cutoff=test_cut, test_end=end,
                   train=train, validation=validation, test=test)


def label_at(example, cutoff, role):
    """Training uses the label version known at fit time, TEST uses current truth."""
    if 'label_versions' not in example:
        return dict(example, role=role) if example['label_available_utc'] <= cutoff else None
    choices = [r for r in example['label_versions'] if available_at(r, STRICT) <= cutoff]
    if not choices: return None
    row = max(choices, key=lambda r: (available_at(r, STRICT), r['source_catalog_sha256']))
    return dict(example, role=role, label=regulation(row), label_available_utc=available_at(row, STRICT),
        label_source=row['source_catalog_sha256'])


def forecast_all(cut, bayes, boosted, reasons):
    p = reference(cut); scores = [p[s] for s in ('home', 'away')]
    std = [cut.features[s]['points_for_std'] for s in ('home', 'away')]
    weights = quarter_weights(cut)
    jobs = dict(FAZ13_MC=lambda: v1_forecast(cut),
        FAZ13_QMC=lambda: gaussian_forecast(scores, std, weights, method='RQMC_HALTON', model='FAZ13_NORMAL_QMC'),
        FAZ13_ANALYTIC=lambda: gaussian_forecast(scores, std, weights, method='ANALYTIC', model='FAZ13_NORMAL_ANALYTIC'),
        POSSESSION_MC=lambda: PossessionModel().predict(cut, method='MC'),
        POSSESSION_ANALYTIC=lambda: PossessionModel().predict(cut, method='ANALYTIC'))
    league_mean = float(np.mean([regulation(r) for r in cut.history]))
    jobs['LEAGUE_MEAN'] = lambda: gaussian_forecast([league_mean]*2, [12.]*2, np.ones((4, 2)), method='ANALYTIC', model='LEAGUE_MEAN')
    jobs['RECENT_POINTS_FOR'] = lambda: gaussian_forecast([cut.features[s]['points_for'] for s in ('home','away')],
        [max(1.,v) for v in std], weights, method='ANALYTIC', model='RECENT_POINTS_FOR')
    if min(std) <= 0:
        for name in ('FAZ13_QMC', 'FAZ13_ANALYTIC'):
            jobs.pop(name); reasons[name+':NO_OBSERVED_SCORE_DISPERSION'] += 1
    if bayes is not None: jobs['BAYES_QMC'] = lambda: bayes.predict(cut, method='RQMC_HALTON')
    for name, model in boosted.items(): jobs[name] = lambda model=model: model.predict(cut, method='RQMC_HALTON')
    forecasts = {}; elapsed = {}
    for name, job in jobs.items():
        began = time.perf_counter()
        try: forecasts[name] = job()
        except Abstain as exc: reasons[name+':'+str(exc)] += 1
        elapsed[name] = time.perf_counter()-began
    return forecasts, elapsed


def serialize(cut, forecast, row, seconds, fold, source_version, fixture_evidence):
    result = serialize_forecast(cut, forecast, row, seconds, 'TEST')
    data_time = max(available_at(r, STRICT) for r in cut.history)
    local_time = max(max(r['observed_at_utc'], r['ingested_at_utc']) for r in cut.history)
    for side in ('home', 'away'):
        for r, box, own, other in cut.features[side]['boxes']:
            data_time = max(data_time, effective_box_time(box))
    data_time = max(data_time, effective_time(fixture_evidence, 'FIXTURE'))
    if data_time > cut.cutoff_utc: raise ValueError('TRACE_DATA_AFTER_PREDICTION_CUTOFF')
    result['trace'] = dict(model_version=forecast.model, model_digest=digest(dict(version=forecast.model,
        code=source_version, training=(forecast.metadata or {}).get('artifact_digest'))),
        source_version=source_version, prediction_utc=cut.cutoff_utc, data_time_utc=data_time,
        local_retrieval_utc=local_time, replay_generated_at_utc=int(time.time()),
        input_digest=cut.inputs_digest, fixture_source=fixture_evidence,
        providers=sorted({r.get('provider', 'UNKNOWN') for r in cut.history}),
        fit_cutoff=(forecast.metadata or {}).get('fit_cutoff_utc'), fold=fold, evidence_class=STRICT)
    lines = {}; p = reference(cut); q = forecast.quarter_means
    centers = dict(TOTAL=p['total'], HOME=p['home'], AWAY=p['away'], HOME_HANDICAP=-p['margin'],
        **{'1Q': sum(p['quarters'][s][0] for s in ('home', 'away')),
           '1H': sum(p['halves'][s][0] for s in ('home', 'away'))})
    actual = result['actual']; aq = np.asarray(result['actual_quarters'])
    outcomes = dict(TOTAL=sum(actual), HOME=actual[0], AWAY=actual[1], HOME_HANDICAP=actual[0]-actual[1],
        **{'1Q': int(aq[0].sum()), '1H': int(aq[:2].sum())})
    result['line_grid'] = []
    for market, center in centers.items():
        width = 2.5 if market == '1Q' else 5.
        for offset in (-width, 0., width):
            line = center+offset
            comparison_line = -line if market == 'HOME_HANDICAP' else line
            try: probabilities = forecast.market('MARGIN' if market == 'HOME_HANDICAP' else market, comparison_line)
            except Abstain: probabilities = None
            result['line_grid'].append(dict(market=market, offset=offset, line=line, probabilities=probabilities,
                outcome=0 if outcomes[market] < comparison_line else 1 if outcomes[market] == comparison_line else 2,
                confidence_index=None, calibration_status='NO_VERIFIED_PAST_PROFILE'))
    return result


def evaluate(cohort, provenance, *, progress=None):
    report = dict(format='STRICT_HYBRID_WALK_FORWARD_V1', generated_at_utc=int(time.time()),
        evaluation_class=STRICT, data_class=provenance['data_class'], provenance=provenance,
        source_audit=source_audit(cohort, provenance), cohorts={}, abstentions={},
        market_line_source='PRE_CUTOFF_MODEL_REFERENCE_SCENARIOS_NOT_BOOKMAKER_QUOTES',
        actual_market_quote_coverage=0, confidence_policy='NO_NUMERIC_CONFIDENCE_WITHOUT_DISJOINT_PAST_CALIBRATION_AUDIT',
        production_default='FAZ13', production_changed=False)
    source_files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')}
    for name in ('historical_research.py', 'prematch_monte_carlo.py', 'verified_analysis.py'):
        source_files['../'+name] = hashlib.sha256((Path(__file__).parent.parent/name).read_bytes()).hexdigest()
    report['code_digest'] = digest(source_files); report['source_file_pins'] = source_files
    groups = {}; rejected = Counter()
    for versions in cohort:
        native = [r for r in versions if r.get('_native_truth', True)]
        row = max(native, key=lambda r: r['ingested_at_utc'])
        try:
            fixture = known_fixture(row, provenance.get('fixture_knowledge', []), row['fixture_start_utc']-1)
            cut = feature_cut(cohort, row, mode=STRICT)
        except Abstain as exc: rejected[str(exc)] += 1; continue
        cut = replace(cut, inputs_digest=digest(dict(features=cut.inputs_digest, fixture=fixture)))
        first_label = min(versions, key=lambda r: available_at(r, STRICT))
        groups.setdefault(row['league']+' '+row['season'], []).append(dict(cut=cut, row=row,
            label=regulation(first_label), label_versions=versions, fixture=fixture,
            label_available_utc=available_at(first_label, STRICT)))
    report['abstentions'] = dict(rejected)
    for key, examples in groups.items():
        target = dict(folds=[], model_rows={n: [] for n in MODELS+BASELINES+('ENSEMBLE', 'VALIDATION_SELECTED')}, abstentions={})
        report['cohorts'][key] = target; reasons = Counter()
        try: folds = list(rolling_folds(examples))
        except Abstain as exc: target.update(status='ABSTAIN', reason=str(exc)); continue
        for fold in folds:
            if not fold['validation'] or not fold['test'] or not fold['train']:
                reasons['EMPTY_FOLD_AFTER_AVAILABILITY_PURGE'] += 1; continue
            trace = {k: v for k, v in fold.items() if k not in ('train', 'validation', 'test')}
            trace['training_ids'] = [e['cut'].target['fixture_id'] for e in fold['train']]
            trace['validation_ids'] = [e['cut'].target['fixture_id'] for e in fold['validation']]
            trace['test_ids'] = [e['cut'].target['fixture_id'] for e in fold['test']]
            trace['label_version_pins'] = {role: [dict(fixture_id=e['cut'].target['fixture_id'],
                available_utc=e['label_available_utc'], label=e['label'], source=e.get('label_source'))
                for e in fold[role]] for role in ('train','validation')}
            assert not set(trace['training_ids'])&set(trace['test_ids'])
            assert not set(trace['validation_ids'])&set(trace['test_ids'])
            target['folds'].append(trace); bayes = None; boosted = {}
            try: bayes = HierarchicalStrength().fit([r for r in fold['validation'][0]['cut'].history if available_at(r, STRICT) <= fold['validation_cutoff']],
                cutoff_utc=fold['validation_cutoff'], mode=STRICT)
            except Abstain as exc: reasons['BAYES:'+str(exc)] += 1
            for backend in ('LIGHTGBM', 'CATBOOST'):
                try: boosted[backend] = BoostedScores(backend).fit(fold['train'], cutoff_utc=fold['validation_cutoff'])
                except Abstain as exc: reasons[backend+':'+str(exc)] += 1
            validation_predictions = []
            for e in fold['validation']:
                forecasts, _ = forecast_all(e['cut'], bayes, boosted, reasons)
                validation_predictions.append(dict(fixture_id=e['cut'].target['fixture_id'], role='VALIDATION',
                    available_utc=e['label_available_utc'], label=e['label'],
                    forecasts={n: Forecast(f.model, f.quarter_means) for n, f in forecasts.items()}))
            for backend, model in boosted.items():
                try: model.fit_residual_scale(fold['validation'], cutoff_utc=fold['test_cutoff'])
                except Abstain as exc: reasons[backend+':'+str(exc)] += 1
            names = set.intersection(*(set(r['forecasts']) for r in validation_predictions))
            candidates = names-{'FAZ13_MC', 'FAZ13_QMC', 'FAZ13_ANALYTIC'}-set(BASELINES)
            validation_mae = {n: float(np.mean([np.abs(r['forecasts'][n].scores-r['label']).mean() for r in validation_predictions])) for n in sorted(candidates)}
            trace['validation_selected'] = min(validation_mae, key=validation_mae.get) if candidates and len(validation_predictions) >= 30 else None
            trace['validation_candidate_mae'] = validation_mae
            ensemble = None
            try: ensemble = Ensemble().fit([dict(r, forecasts={n: r['forecasts'][n] for n in sorted(names-set(BASELINES))}) for r in validation_predictions], cutoff_utc=fold['test_cutoff'])
            except Abstain as exc: reasons['ENSEMBLE:'+str(exc)] += 1
            trace['ensemble'] = None if ensemble is None else dict(weights=dict(zip(ensemble.names, ensemble.weights.tolist())),
                digest=ensemble.artifact_digest, fit_cutoff=ensemble.cutoff, validation_ids=ensemble.validation_ids)
            for e in fold['test']:
                forecasts, elapsed = forecast_all(e['cut'], bayes, boosted, reasons)
                if ensemble:
                    began = time.perf_counter()
                    try: forecasts['ENSEMBLE'] = ensemble.predict(forecasts, cutoff_utc=e['cut'].cutoff_utc)
                    except Abstain as exc: reasons['ENSEMBLE:'+str(exc)] += 1
                    elapsed['ENSEMBLE'] = time.perf_counter()-began
                for name, forecast in forecasts.items():
                    saved = serialize(e['cut'], forecast, e['row'], elapsed[name], fold['fold'], report['code_digest'], e['fixture'])
                    target['model_rows'][name].append(saved)
                    if name == trace['validation_selected']: target['model_rows']['VALIDATION_SELECTED'].append(saved)
            if progress: progress(dict(cohort=key, fold=fold['fold'], test_games=len(fold['test'])))
        target['abstentions'] = dict(reasons)
        rows = target['model_rows']
        target['coverage_metrics_not_rankable'] = {n: summarize(data) for n,data in rows.items()}
        common = set.intersection(*(set(r['fixture_id'] for r in rows[n]) for n in MODELS))
        target['all_requested_models_common_games'] = len(common)
        target['common_cohort_metrics'] = {n: summarize([r for r in rows[n] if r['fixture_id'] in common]) for n in MODELS}
        target['paired_vs_faz13'] = {n: paired_cluster_interval(rows['FAZ13_MC'], data) for n, data in rows.items() if n != 'FAZ13_MC'}
        target['coverage_only_market_metrics_not_rankable'] = {n: {m: {str(o): market_metrics(data, m, o) for o in ((-2.5, 0., 2.5) if m == '1Q' else (-5., 0., 5.))}
            for m in ('1Q', '1H', 'TOTAL', 'HOME', 'AWAY', 'HOME_HANDICAP')} for n, data in rows.items()}
        target['market_common_cohort_metrics'] = {}
        for market in ('1Q', '1H', 'TOTAL', 'HOME', 'AWAY', 'HOME_HANDICAP'):
            target['market_common_cohort_metrics'][market] = {}
            for offset in ((-2.5, 0., 2.5) if market == '1Q' else (-5., 0., 5.)):
                ids = set.intersection(*(set(r['fixture_id'] for r in rows[n] if any(m['market'] == market and m['offset'] == offset and m['probabilities'] is not None for m in r['line_grid'])) for n in MODELS))
                target['market_common_cohort_metrics'][market][str(offset)] = dict(n_common=len(ids),
                    models={n: market_metrics([r for r in rows[n] if r['fixture_id'] in ids], market, offset) for n in MODELS})
        target['market_paired_vs_faz13'] = {n: {m: {str(o): paired_market_interval(rows['FAZ13_MC'], data, m, o)
            for o in ((-2.5, 0., 2.5) if m == '1Q' else (-5., 0., 5.))}
            for m in ('1Q', '1H', 'TOTAL', 'HOME', 'AWAY', 'HOME_HANDICAP')} for n, data in rows.items() if n != 'FAZ13_MC'}
    report['acceptance'] = dict(status='BLOCKED', production_default='FAZ13', main_merge_permitted=False,
        production_deploy_permitted=False, strict_test_games=sum(len(c.get('model_rows', {}).get('FAZ13_MC', [])) for c in report['cohorts'].values()),
        blockers=['NO_PROVEN_STRICT_OUT_OF_SAMPLE_IMPROVEMENT', 'NO_VERIFIED_MARKET_CALIBRATION_PROFILE',
            'COMBINED_TELEGRAM_ML_RESOURCE_RESULT_REQUIRES_SEPARATE_EVIDENCE'],
        safety='NO_PRODUCTION_RESOURCE_DATABASE_SECRET_OR_SNAPSHOT_ACCESS')
    qualifying = []
    for key, cohort in report['cohorts'].items():
        comparison = cohort.get('paired_vs_faz13', {}).get('VALIDATION_SELECTED', {})
        metric = comparison.get('metrics', {}).get('team_mae', {})
        baseline_count = len(cohort.get('model_rows', {}).get('FAZ13_MC', []))
        interval = metric.get('interval')
        if (comparison.get('n', 0) >= 50 and comparison.get('day_clusters', 0) >= 20 and
                comparison['n'] >= .8*baseline_count and interval is not None and interval[1] < 0 and
                metric['candidate'] <= .98*metric['baseline'] and provenance['data_class'] == 'REAL_HISTORICAL'):
            qualifying.append(key)
    report['acceptance']['qualifying_primary_experiments'] = qualifying
    if qualifying: report['acceptance']['blockers'].remove('NO_PROVEN_STRICT_OUT_OF_SAMPLE_IMPROVEMENT')
    if not groups: report['acceptance']['blockers'].append('NO_PRE_CUTOFF_FIXTURE_AND_HISTORY_COHORT')
    return report


def run_walkforward(manifest, *, progress=None):
    cohort, provenance = load_manifest(manifest)
    return evaluate(cohort, provenance, progress=progress)

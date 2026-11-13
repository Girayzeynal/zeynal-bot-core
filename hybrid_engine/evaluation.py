"""Offline, chronological research evaluation. Never imported by Telegram handlers."""
from collections import Counter
import math
import time
from threading import RLock
from unittest.mock import patch

import numpy as np

from core.team_identity import digest
from hybrid_engine.data import (ASSUMED, STRICT, PERMISSION, Abstain, available_at,
    feature_cut, inventory, load_manifest, reference, regulation)
from hybrid_engine.distributions import Budget, Forecast, gaussian_forecast, quarter_weights
from hybrid_engine.models import BoostedScores, HierarchicalStrength
from hybrid_engine.possession import PossessionModel
from prematch_monte_carlo import PrematchMonteCarloEngine, PrematchSimulationInput
import prematch_monte_carlo as v1_module

_v1_trace_lock = RLock()


class V1Law:
    def __init__(self, cut, line):
        p = reference(cut)
        self.line = line
        samples = np.empty((10000, 4, 2), dtype=np.int32); cursor = 0
        original_allocate = None
        def traced(total, periods, rng):
            nonlocal cursor
            allocation = original_allocate(total, periods, rng)
            samples[cursor//2, :, cursor % 2] = allocation; cursor += 1
            return allocation
        request = PrematchSimulationInput(
            home_mean=p['home'], away_mean=p['away'],
            home_std=cut.features['home']['points_for_std'],
            away_std=cut.features['away']['points_for_std'],
            score_correlation=0., simulations=10000, seed=20261108, market_total=line)
        # Offline/sandbox adapter only. Preserve the original sampler, RNG sequence and
        # returned periods; don't replace production code with a research reimplementation.
        with _v1_trace_lock:
            original_allocate = v1_module._allocate_periods
            with patch.object(v1_module, '_allocate_periods', new=traced):
                self.result = PrematchMonteCarloEngine().simulate(request)
        if cursor != 20000: raise ValueError('V1_NATIVE_PERIOD_TRACE_INCOMPLETE')
        self.paths = Forecast('V1_NATIVE_GAMMA_PERIOD_PATHS', np.array([p['quarters'][s] for s in ('home', 'away')]).T, samples=samples)

    def winner(self):
        r = self.result
        return [r.home_regulation_win_probability, r.regulation_tie_probability, r.away_regulation_win_probability]

    def market(self, kind, line):
        return self.paths.market(kind, line)


def v1_forecast(cut):
    p = reference(cut)
    law = V1Law(cut, p['total']) if min(cut.features[s]['points_for_std'] for s in ('home', 'away')) > 0 else None
    return Forecast('FAZ13_V1_REFERENCE', np.array([p['quarters'][s] for s in ('home', 'away')]).T,
        law=law, metadata=dict(method='EXISTING_PRODUCTION_MC', scenarios=10000 if law else 0,
            seed=20261108, score_formula='REUSED_HISTORICAL_REFERENCE',
            quarter_probabilities='ACTUAL_EXISTING_GAMMA18_ALLOCATOR_TRACE_NOT_POINT_PROFILE_UNCERTAINTY'))


def chronological_split(examples):
    """Split unique kickoff times 60/20/20; purge labels unavailable at next fold."""
    times = sorted({e['cut'].cutoff_utc for e in examples})
    if len(times) < 10: raise Abstain('INSUFFICIENT_DISTINCT_KICKOFFS_FOR_THREE_FOLDS')
    validation_start = times[int(.6*len(times))]; test_start = times[int(.8*len(times))]
    out = dict(TRAIN=[], VALIDATION=[], TEST=[]); purged = 0
    for e in examples:
        t = e['cut'].cutoff_utc
        role = 'TRAIN' if t < validation_start else 'VALIDATION' if t < test_start else 'TEST'
        if (role == 'TRAIN' and e['label_available_utc'] > validation_start or
                role == 'VALIDATION' and e['label_available_utc'] > test_start):
            purged += 1; continue
        out[role].append(dict(e, role=role))
    return out, dict(validation_cutoff_utc=validation_start, test_cutoff_utc=test_start,
                     purged_labels=purged, split='UNIQUE_KICKOFF_60_20_20_PURGED')


def simplex(vector):
    u = np.sort(vector)[::-1]; sums = np.cumsum(u)-1
    rho = np.flatnonzero(u-sums/np.arange(1, len(u)+1) > 0)[-1]
    return np.maximum(vector-sums[rho]/(rho+1), 0.)


class Ensemble:
    """One convex weight vector for every quarter/team and probability distribution."""
    def fit(self, records, *, cutoff_utc, minimum=30):
        if len(records) < minimum: raise Abstain('INSUFFICIENT_PAST_OOS_ENSEMBLE_VALIDATION')
        if len({r['fixture_id'] for r in records}) != len(records): raise ValueError('DUPLICATE_ENSEMBLE_VALIDATION')
        if not records[0]['forecasts']: raise Abstain('NO_COMMON_ENSEMBLE_COMPONENTS')
        if any(r['role'] != 'VALIDATION' or r['available_utc'] > cutoff_utc for r in records):
            raise ValueError('ENSEMBLE_WEIGHTS_REQUIRE_PAST_VALIDATION_ONLY')
        self.names = sorted(records[0]['forecasts'])
        if any(sorted(r['forecasts']) != self.names for r in records):
            raise ValueError('ENSEMBLE_REQUIRES_COMMON_VALIDATION_COHORT')
        # Joint team-score loss chooses common weights; market-specific test tuning is forbidden.
        x = np.array([[r['forecasts'][n].scores for n in self.names] for r in records])
        y = np.array([r['label'] for r in records])
        errors = (x-y[:, None, :]).transpose(0, 2, 1).reshape(-1, len(self.names))
        gram = errors.T@errors/len(errors)
        step = 1/max(1., 2*np.linalg.norm(gram, 2)); weights = np.full(len(self.names), 1/len(self.names))
        for _ in range(1500):
            next_weights = simplex(weights-step*2*gram@weights)
            if np.max(np.abs(next_weights-weights)) < 1e-10: break
            weights = next_weights
        self.weights = weights; self.cutoff = cutoff_utc
        self.validation_ids = sorted(r['fixture_id'] for r in records)
        self.artifact_digest = digest(dict(weights=dict(zip(self.names, weights.tolist())),
            cutoff_utc=cutoff_utc, validation_ids=self.validation_ids,
            forecasts=x.tolist(), labels=y.tolist(), objective='JOINT_TEAM_SCORE_MSE'))
        return self

    def predict(self, forecasts, *, cutoff_utc):
        if cutoff_utc < self.cutoff: raise ValueError('ENSEMBLE_CUTOFF_LEAKAGE')
        if any(n not in forecasts for n, w in zip(self.names, self.weights) if w > 1e-8):
            raise Abstain('ENSEMBLE_COMPONENT_UNAVAILABLE_NO_WEIGHT_RENORMALIZATION')
        components = [(float(w), forecasts[n]) for n, w in zip(self.names, self.weights) if w > 1e-8]
        quarters = sum(w*f.quarter_means for w, f in components)
        return Forecast('PAST_VALIDATION_CONVEX_ENSEMBLE', quarters, law=MixtureLaw(components),
            metadata=dict(weights=dict(zip(self.names, self.weights.tolist())),
                fit_cutoff_utc=self.cutoff, validation_games=len(self.validation_ids),
                artifact_digest=self.artifact_digest, objective='JOINT_TEAM_SCORE_MSE',
                probability_status='MIXTURE_NOT_CALIBRATED'))


class MixtureLaw:
    def __init__(self, components): self.components = components
    def winner(self):
        probabilities = [f.probabilities() for w, f in self.components]
        if any(p is None for p in probabilities): return None
        return sum(w*np.array(p) for (w, f), p in zip(self.components, probabilities)).tolist()
    def market(self, kind, line):
        values = [(w, f.market(kind, line)) for w, f in self.components]
        return {key: sum(w*p[key] for w, p in values) for key in ('under', 'push', 'over')}


def calibration(probabilities, observations):
    p = np.asarray(probabilities); y = np.asarray(observations); bins = []
    for i in range(10):
        mask = (p >= i/10)&(p <= 1 if i == 9 else p < (i+1)/10)
        bins.append(dict(count=int(mask.sum()), predicted=float(p[mask].mean()) if mask.any() else None,
                         observed=float(y[mask].mean()) if mask.any() else None))
    return dict(bins=bins, ece=sum(b['count']/len(p)*abs(b['predicted']-b['observed']) for b in bins if b['count']))


def probability_metrics(p, y):
    p = np.array(p); y = np.array(y)
    if (p.ndim != 2 or p.shape[1] != 3 or y.ndim != 1 or not np.issubdtype(y.dtype, np.integer) or np.any(y < 0) or np.any(y > 2) or len(y) != len(p) or not len(p) or
            not np.isfinite(p).all() or np.any(p < 0) or not np.allclose(p.sum(axis=1), 1)):
        raise ValueError('NORMALIZED_THREE_CLASS_PROBABILITIES_REQUIRED')
    truth = np.eye(3)[y]
    return dict(n=len(y), brier=float(np.mean(np.sum((p-truth)**2, axis=1))),
        log_loss=float(-np.mean(np.log(np.clip(p[np.arange(len(y)), y], 1e-15, 1)))),
        home_or_under_calibration=calibration(p[:, 0], y == 0))


def point_metrics(error):
    e = np.asarray(error)
    return dict(mae=float(np.mean(np.abs(e))), rmse=float(np.sqrt(np.mean(e**2))), bias=float(np.mean(e)))


def summarize(rows):
    if not rows: return dict(n=0)
    q = np.array([r['prediction']['quarters'] for r in rows]); actual_q = np.array([r['actual_quarters'] for r in rows])
    scores = q.sum(axis=1); actual = actual_q.sum(axis=1)
    result = dict(n=len(rows), team_scores=point_metrics(scores-actual),
        home=point_metrics(scores[:, 0]-actual[:, 0]), away=point_metrics(scores[:, 1]-actual[:, 1]),
        total=point_metrics(scores.sum(axis=1)-actual.sum(axis=1)),
        margin=point_metrics((scores[:, 0]-scores[:, 1])-(actual[:, 0]-actual[:, 1])),
        periods={str(i+1)+'Q': point_metrics(q[:, i]-actual_q[:, i]) for i in range(4)},
        halves={str(i+1)+'H': point_metrics(q[:, 2*i:2*i+2].sum(axis=1)-actual_q[:, 2*i:2*i+2].sum(axis=1)) for i in range(2)},
        runtime_seconds=dict(p50=float(np.median([r['seconds'] for r in rows])),
            p95=float(np.quantile([r['seconds'] for r in rows], .95)), maximum=max(r['seconds'] for r in rows)))
    valid = [r for r in rows if r['prediction']['winner'] is not None]
    if valid:
        result['winner'] = probability_metrics([r['prediction']['winner'] for r in valid],
            [0 if r['actual'][0] > r['actual'][1] else 1 if r['actual'][0] == r['actual'][1] else 2 for r in valid])
    result['evaluation_line_markets'] = {}
    for kind in ('TOTAL', 'HOME', 'AWAY', 'MARGIN', '1H', '2H', '1Q', '2Q', '3Q', '4Q'):
        valid = [r['markets'][kind] for r in rows if kind in r['markets']]
        if valid:
            result['evaluation_line_markets'][kind] = probability_metrics(
                [[v['probabilities'][k] for k in ('under', 'push', 'over')] for v in valid], [v['outcome'] for v in valid])
    return result


def serialize_forecast(cut, forecast, row, seconds, role):
    p = reference(cut); q = np.array([p['quarters'][s] for s in ('home', 'away')]).T
    actual_q = np.array([row['periods'][s][:4] for s in ('home', 'away')]).T
    lines = dict(TOTAL=p['total'], HOME=p['home'], AWAY=p['away'], MARGIN=p['margin'],
        **{'1H': float(q[:2].sum()), '2H': float(q[2:].sum())},
        **{str(i+1)+'Q': float(q[i].sum()) for i in range(4)})
    actual = actual_q.sum(axis=0)
    outcomes = dict(TOTAL=int(actual.sum()), HOME=int(actual[0]), AWAY=int(actual[1]), MARGIN=int(actual[0]-actual[1]),
        **{'1H': int(actual_q[:2].sum()), '2H': int(actual_q[2:].sum())},
        **{str(i+1)+'Q': int(actual_q[i].sum()) for i in range(4)})
    markets = {}
    for kind, line in lines.items():
        try: probabilities = forecast.market(kind, line)
        except Abstain: continue
        markets[kind] = dict(line=line, probabilities=probabilities,
            outcome=0 if outcomes[kind] < line else 1 if outcomes[kind] == line else 2)
    return dict(fixture_id=cut.target['fixture_id'], start_utc=cut.target['fixture_start_utc'], role=role,
        evaluation_class=cut.evaluation_class, inputs_digest=cut.inputs_digest, actual=actual.tolist(),
        actual_quarters=actual_q.tolist(), prediction=forecast.summary(), seconds=seconds, markets=markets)


def paired_comparison(candidate, baseline, *, iterations=2000, seed=20261112):
    b = {r['fixture_id']: r for r in baseline}; c = {r['fixture_id']: r for r in candidate}
    ids = sorted(set(b)&set(c))
    if not ids: return dict(n=0)
    def losses(r):
        p = r['prediction']; a = r['actual']
        return [np.abs(np.array([p['home'], p['away']])-a).mean(), abs(p['total']-sum(a)), abs(p['margin']-(a[0]-a[1]))]
    bl = np.array([losses(b[i]) for i in ids]); ca = np.array([losses(c[i]) for i in ids]); diff = ca-bl
    rng = np.random.default_rng(seed); boot = diff[rng.integers(0, len(ids), (iterations, len(ids)))].mean(axis=1)
    result = dict(n=len(ids), unit='PAIRED_GAME_NOT_TEAM_ROWS',
        **{name: dict(candidate_mae=float(ca[:, j].mean()), baseline_mae=float(bl[:, j].mean()),
            difference=float(diff[:, j].mean()), bootstrap_95_interval=np.quantile(boot[:, j], [.025, .975]).tolist())
            for j, name in enumerate(('team_scores', 'total', 'margin'))})
    probability_ids = [i for i in ids if b[i]['prediction']['winner'] is not None and c[i]['prediction']['winner'] is not None]
    if probability_ids:
        def losses_for(rows):
            output = []
            for i in probability_ids:
                p = np.array(rows[i]['prediction']['winner']); a = rows[i]['actual']
                y = 0 if a[0] > a[1] else 1 if a[0] == a[1] else 2
                output.append([np.sum((p-np.eye(3)[y])**2), -np.log(max(1e-15, p[y]))])
            return np.array(output)
        bl = losses_for(b); ca = losses_for(c); diff = ca-bl
        boot = diff[rng.integers(0, len(probability_ids), (iterations, len(probability_ids)))].mean(axis=1)
        result['winner'] = dict(n=len(probability_ids), **{name: dict(candidate=float(ca[:, j].mean()),
            baseline=float(bl[:, j].mean()), difference=float(diff[:, j].mean()),
            bootstrap_95_interval=np.quantile(boot[:, j], [.025, .975]).tolist()) for j, name in enumerate(('brier', 'log_loss'))})
    return result


def run_research(manifest_path, *, mode=STRICT, progress=None):
    cohort, provenance = load_manifest(manifest_path); groups = {}; rejected = Counter()
    for versions in cohort:
        row = versions[0]
        try: cut = feature_cut(cohort, row, mode=mode)
        except Abstain as exc: rejected[str(exc)] += 1; continue
        key = row['league']+' '+row['season']
        groups.setdefault(key, []).append(dict(cut=cut, label=regulation(row), row=row,
            label_available_utc=available_at(row, mode)))
    result = dict(format='HYBRID_RESEARCH_REPORT_V1', generated_at_utc=int(time.time()),
        record_type='BACKTEST_SIMULATION', evaluation_class=mode, provenance=provenance,
        inventory=inventory(cohort), feature_abstentions=dict(rejected), cohorts={},
        evaluation_lines='PREDECLARED_V1_REFERENCE_PROJECTIONS_NOT_OBSERVED_MARKET_QUOTES',
        scope='REGULATION_ONLY', automatic_production_update_permitted=False)
    for key, examples in sorted(groups.items()):
        try: folds, split = chronological_split(examples)
        except Abstain as exc:
            result['cohorts'][key] = dict(status='ABSTAIN', reason=str(exc)); continue
        fit_cutoff = split['validation_cutoff_utc']; test_cutoff = split['test_cutoff_utc']
        report = dict(split=split, counts={k: len(v) for k, v in folds.items()}, abstentions={}, models={}, comparisons={}, offline_training={})
        result['cohorts'][key] = report
        if any(not v for v in folds.values()):
            report.update(status='ABSTAIN', reason='EMPTY_FOLD_AFTER_LABEL_AVAILABILITY_PURGE'); continue
        if progress: progress(dict(cohort=key, counts=report['counts']))
        bayes = None; ml = {}; reasons = Counter()
        began = time.perf_counter()
        try: bayes = HierarchicalStrength().fit([r for r in folds['VALIDATION'][0]['cut'].history if available_at(r, mode) <= fit_cutoff], cutoff_utc=fit_cutoff, mode=mode)
        except Abstain as exc: reasons['BAYES:'+str(exc)] += 1
        if bayes: report['offline_training']['BAYES'] = dict(seconds=time.perf_counter()-began,
            games=len(bayes.training_ids), cutoff_utc=fit_cutoff, artifact_digest=bayes.artifact_digest)
        for name in ('LIGHTGBM', 'CATBOOST'):
            began = time.perf_counter()
            try: ml[name] = BoostedScores(name).fit(folds['TRAIN'], cutoff_utc=fit_cutoff)
            except Abstain as exc: reasons[name+':'+str(exc)] += 1
            if name in ml: report['offline_training'][name] = dict(seconds=time.perf_counter()-began,
                examples=len(folds['TRAIN']), cutoff_utc=fit_cutoff, artifact_digest=ml[name].artifact_digest)
        validation_records = []; stored = dict(VALIDATION={}, TEST={}); ensemble = None
        for role in ('VALIDATION', 'TEST'):
            if role == 'TEST':
                for name, model in ml.items():
                    try: model.fit_residual_scale(folds['VALIDATION'], cutoff_utc=test_cutoff)
                    except Abstain as exc: reasons[name+':'+str(exc)] += 1
                if validation_records:
                    common_names = set.intersection(*(set(r['forecasts']) for r in validation_records))
                    common = [dict(r, forecasts={n: f for n, f in r['forecasts'].items() if n in common_names}) for r in validation_records]
                    try: ensemble = Ensemble().fit(common, cutoff_utc=test_cutoff)
                    except Abstain as exc: reasons['ENSEMBLE:'+str(exc)] += 1
            for e in folds[role]:
                cut = e['cut']; forecasts = {}; f = cut.features
                league_mean = float(np.mean([regulation(r) for r in cut.history]))
                mean_scores = [f[s]['points_for'] for s in ('home', 'away')]
                jobs = {'FAZ13': lambda: v1_forecast(cut),
                    'LEAGUE_MEAN': lambda: gaussian_forecast([league_mean]*2, [12.]*2, np.ones((4, 2)), method='ANALYTIC', model='LEAGUE_MEAN'),
                    'RECENT_POINTS_FOR': lambda: gaussian_forecast(mean_scores, [max(1., f[s]['points_for_std']) for s in ('home', 'away')], quarter_weights(cut), method='ANALYTIC', model='RECENT_POINTS_FOR'),
                    'POSSESSION': lambda: PossessionModel().predict(cut),
                    'FAZ13_ANALYTIC': lambda: gaussian_forecast([reference(cut)[s] for s in ('home', 'away')],
                        [max(1., f[s]['points_for_std']) for s in ('home', 'away')], quarter_weights(cut), method='ANALYTIC', model='FAZ13_NORMAL_ANALYTIC'),
                    'FAZ13_RQMC': lambda: gaussian_forecast([reference(cut)[s] for s in ('home', 'away')],
                        [max(1., f[s]['points_for_std']) for s in ('home', 'away')], quarter_weights(cut), method='RQMC_HALTON', model='FAZ13_NORMAL_RQMC')}
                if bayes: jobs['BAYES'] = lambda: bayes.predict(cut, method='RQMC_HALTON')
                for name, model in ml.items(): jobs[name] = lambda model=model: model.predict(cut, method='RQMC_HALTON')
                for name, job in jobs.items():
                    began = time.perf_counter()
                    try: forecast = job()
                    except Abstain as exc: reasons[name+':'+str(exc)] += 1; continue
                    seconds = time.perf_counter()-began; forecasts[name] = forecast
                    stored[role].setdefault(name, []).append(serialize_forecast(cut, forecast, e['row'], seconds, role))
                if role == 'VALIDATION':
                    validation_records.append(dict(fixture_id=cut.target['fixture_id'], role=role,
                        available_utc=e['label_available_utc'], label=e['label'], forecasts=forecasts))
                elif ensemble:
                    began = time.perf_counter()
                    try: combined = ensemble.predict(forecasts, cutoff_utc=cut.cutoff_utc)
                    except Abstain as exc: reasons['ENSEMBLE:'+str(exc)] += 1; continue
                    stored[role].setdefault('ENSEMBLE', []).append(serialize_forecast(cut, combined, e['row'], time.perf_counter()-began, role))
            if progress: progress(dict(cohort=key, completed=role))
        report['abstentions'] = dict(reasons)
        report['models'] = {name: {role: summarize(data.get(name, [])) for role, data in stored.items()}
                            for name in sorted(set(stored['TEST'])|set(stored['VALIDATION']))}
        # Select on validation only, before inspecting test losses. Test rankings are exploratory.
        candidates = [n for n in stored['VALIDATION'] if n not in ('FAZ13', 'FAZ13_ANALYTIC', 'FAZ13_RQMC', 'LEAGUE_MEAN', 'RECENT_POINTS_FOR')]
        common_ids = set.intersection(*(set(r['fixture_id'] for r in stored['VALIDATION'][n]) for n in candidates)) if candidates else set()
        selection_mae = {n: summarize([r for r in stored['VALIDATION'][n] if r['fixture_id'] in common_ids])['team_scores']['mae'] for n in candidates} if common_ids else {}
        selected = min(selection_mae, key=selection_mae.get) if selection_mae else None
        report['selection_common_validation_games'] = len(common_ids)
        report['selection_common_validation_mae'] = selection_mae
        report['validation_selected_candidate'] = selected
        for name, data in stored['TEST'].items():
            if name != 'FAZ13': report['comparisons'][name] = paired_comparison(data, stored['TEST'].get('FAZ13', []))
        report['ensemble'] = None if ensemble is None else dict(weights=dict(zip(ensemble.names, ensemble.weights.tolist())),
            validation_ids=ensemble.validation_ids, artifact_digest=ensemble.artifact_digest, fit_cutoff_utc=ensemble.cutoff)
        report['predictions'] = stored
        report['bayesian_artifact'] = None if bayes is None else bayes.artifact()
    blockers = []
    if mode != STRICT: blockers.append('HISTORICAL_AVAILABILITY_ASSUMED_NOT_PROVEN')
    if provenance['data_class'] != 'REAL_HISTORICAL': blockers.append('REAL_HISTORICAL_DATA_REQUIRED')
    if provenance['source_permission'] != PERMISSION: blockers.append('SOURCE_TRAINING_PERMISSION_NOT_ESTABLISHED')
    if not groups: blockers.append('NO_ELIGIBLE_POINT_IN_TIME_COHORT')
    accepted = []
    for key, r in result['cohorts'].items():
        if r.get('status') == 'ABSTAIN': continue
        selected = r['validation_selected_candidate']; comparison = r['comparisons'].get(selected, {})
        m = comparison.get('team_scores', {})
        if (comparison.get('n', 0) >= 50 and r['counts']['TRAIN'] >= 100 and r['counts']['VALIDATION'] >= 30 and
                m.get('bootstrap_95_interval', [0, 0])[1] < 0 and m['candidate_mae'] <= .98*m['baseline_mae']):
            accepted.append(dict(cohort=key, model=selected))
    if not accepted: blockers.append('NO_VALIDATION_SELECTED_MODEL_PROVES_PREDECLARED_2PCT_MAE_GAIN_WITH_95CI')
    result['promotion_gate'] = dict(status='BLOCKED' if blockers else 'ELIGIBLE_FOR_SEPARATE_HUMAN_REVIEW',
        blockers=blockers, qualifying_experiments=accepted, minimum_test_games=50,
        primary_endpoint='JOINT_TEAM_SCORE_MAE', minimum_relative_gain=.02,
        bootstrap_interval_policy='PAIRED_GAME_IID_BOOTSTRAP_NOT_DEPENDENCE_ROBUST',
        production_model_changed=False)
    return result

"""Synthetic safety/mechanics fixtures, never claimed as real backtest observations."""
from copy import deepcopy
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import numpy as np

from core.team_identity import digest
from hybrid_engine.audit import known_fixture, source_audit
from hybrid_engine.data import STRICT, ASSUMED, Abstain, Cut, feature_cut
from hybrid_engine.distributions import Forecast, gaussian_forecast
from hybrid_engine.evaluation import v1_forecast
from hybrid_engine.markets import MarketCalibration, market_grid, render_research
from hybrid_engine.models import BoostedScores
from hybrid_engine.portable import PortableBoostedScores, export_portable
from hybrid_engine.statistics import calibration_curve, paired_cluster_interval
from hybrid_engine.walkforward import evaluate, rolling_folds, MODELS
from tests.test_hybrid_models import synthetic_cohort, example


def provenance(cohort, early=True):
    knowledge = [dict(league=r[0]['league'], fixture_id=r[0]['fixture_id'],
        season=r[0]['season'],
        fixture_start_utc=r[0]['fixture_start_utc'], home_team_id=r[0]['home_team_id'], away_team_id=r[0]['away_team_id'],
        provider='SYNTHETIC', observed_at_utc=r[0]['fixture_start_utc']+(-100 if early else 100),
        ingested_at_utc=r[0]['fixture_start_utc']+(-99 if early else 101), source_catalog_sha256='synthetic') for r in cohort]
    return dict(data_class='SYNTHETIC_TEST_ONLY', fixture_knowledge=knowledge)


def calibration_records():
    groups = []
    for prefix, start, role in [('fit', 1735689600, 'CALIBRATION'), ('audit', 1736000000, 'CALIBRATION_AUDIT')]:
        groups.append([dict(fixture_id=prefix+str(i), probabilities=[.9, .05, .05], outcome=0 if i % 5 else 2,
            market='TOTAL', line=200.5, model_digest='fixture-model', evidence_class=STRICT,
            data_class='REAL_HISTORICAL',  # Deliberately synthetic contract fixture; not real evidence.
            role=role, fixture_start_utc=start+i*1000, prediction_utc=start+i*1000-1,
            label_available_utc=start+i*1000+10, inputs_available_max=start+i*1000-2,
            model_fit_cutoff=1735000000, model_training_ids=[]) for i in range(200)])
    return groups


class StrictWalkForwardTests(TestCase):
    def test_fixture_knowledge_is_required_and_late_source_never_becomes_pit(self):
        c = synthetic_cohort(40); p = provenance(c, early=False)
        with self.assertRaises(Abstain): known_fixture(c[20][0], p['fixture_knowledge'], c[20][0]['fixture_start_utc']-1)
        with patch('hybrid_engine.walkforward.BoostedScores.fit', side_effect=AssertionError('No eligible data, no training')):
            report = evaluate(c, p)
        self.assertEqual(report['acceptance']['strict_test_games'], 0)
        self.assertEqual(report['abstentions']['NO_PRE_CUTOFF_FIXTURE_KNOWLEDGE'], 40)
        self.assertEqual(report['acceptance']['production_default'], 'FAZ13')

    def test_all_contributing_history_is_in_input_digest(self):
        c = synthetic_cohort(50); before = feature_cut(c, c[40][0])
        c[0][0]['periods']['home'][0] += 8
        after = feature_cut(c, c[40][0])
        self.assertNotEqual(before.features['home']['opponent_adjusted_for'], after.features['home']['opponent_adjusted_for'])
        self.assertNotEqual(before.inputs_digest, after.inputs_digest)

    def test_rolling_folds_freeze_training_and_validation_before_every_test_block(self):
        c = synthetic_cohort(60); examples = [example(c, i, 'UNASSIGNED') for i in range(10, 60)]
        folds = list(rolling_folds(examples)); self.assertGreaterEqual(len(folds), 3)
        seen = set()
        for fold in folds:
            self.assertTrue(all(e['label_available_utc'] <= fold['validation_cutoff'] for e in fold['train']))
            self.assertTrue(all(e['label_available_utc'] <= fold['test_cutoff'] for e in fold['validation']))
            ids = {e['cut'].target['fixture_id'] for e in fold['test']}
            self.assertFalse(seen&ids); seen |= ids

    def test_future_labels_cannot_change_earlier_walk_forward_predictions(self):
        c = synthetic_cohort(40); p = provenance(c)
        def deterministic(cut, bayes, ml, reasons):
            f = gaussian_forecast([cut.features[s]['points_for'] for s in ('home', 'away')], [10, 10], np.ones((4, 2)), method='ANALYTIC')
            f.metadata.pop('elapsed_seconds', None)
            return {n: f for n in MODELS}, {n: 0. for n in MODELS}
        with patch('hybrid_engine.walkforward.forecast_all', side_effect=deterministic):
            before = evaluate(c, p)
            c[-1][0]['periods']['home'][0] += 100
            after = evaluate(c, p)
        b = before['cohorts']['NBA SYNTHETIC']['model_rows']['FAZ13_MC']
        a = after['cohorts']['NBA SYNTHETIC']['model_rows']['FAZ13_MC']
        self.assertTrue(b)
        for left, right in zip(b, a):
            if left['fixture_id'] != c[-1][0]['fixture_id']:
                self.assertEqual(left['prediction'], right['prediction'])
                self.assertEqual(left['inputs_digest'], right['inputs_digest'])
        self.assertFalse(before['acceptance']['production_deploy_permitted'])

    def test_cluster_intervals_do_not_treat_team_rows_as_independent_games(self):
        c = synthetic_cohort(12)
        rows = [dict(fixture_id=str(i), start_utc=r[0]['fixture_start_utc'], actual=[100, 100],
            actual_quarters=[[25, 25]]*4, prediction=dict(home=110, away=110, total=220, margin=0, quarters=[[27.5, 27.5]]*4)) for i, r in enumerate(c)]
        result = paired_cluster_interval(rows, rows, iterations=100)
        self.assertEqual(result['n'], 12); self.assertEqual(result['day_clusters'], 12)
        self.assertEqual(result['metrics']['team_mae']['interval'], [0., 0.])
        self.assertEqual(paired_cluster_interval(rows[:2], rows[:2])['status'], 'INSUFFICIENT_DAY_CLUSTERS_FOR_CLAIM')
        different = deepcopy(rows); different[0]['actual'][0] += 1
        with self.assertRaises(ValueError): paired_cluster_interval(rows, different)


class CalibratedMarketTests(TestCase):
    def test_each_period_and_line_has_matching_analytic_and_sampled_probability_mass(self):
        weights = np.array([[22, 28], [30, 25], [28, 24], [25, 29]])
        analytic = gaussian_forecast([105, 106], [11, 12], weights, method='ANALYTIC')
        sampled = gaussian_forecast([105, 106], [11, 12], weights, method='MC')
        for kind, line in [('1Q', 50), ('1H', 105), ('TOTAL', 210), ('HOME', 105), ('AWAY', 106), ('MARGIN', 0)]:
            for offset in (-2.5, 0, 2.5):
                a = analytic.market(kind, line+offset); s = sampled.market(kind, line+offset)
                self.assertAlmostEqual(sum(a.values()), 1)
                np.testing.assert_allclose(list(a.values()), list(s.values()), atol=.025)
        c = synthetic_cohort(50); v1 = v1_forecast(feature_cut(c, c[40][0]))
        for kind, line in [('1Q', 50.5), ('1H', 100.5), ('TOTAL', 200.5), ('HOME', 100.5), ('AWAY', 100.5), ('MARGIN', -5.5)]:
            self.assertAlmostEqual(sum(v1.market(kind, line).values()), 1)
        self.assertEqual(v1.market('TOTAL', v1.law.line)['over'], v1.law.result.over_probability)

    def test_native_v1_research_traces_are_deterministic_and_restore_the_allocator(self):
        from concurrent.futures import ThreadPoolExecutor
        import prematch_monte_carlo
        original = prematch_monte_carlo._allocate_periods
        c = synthetic_cohort(50); cut = feature_cut(c, c[40][0])
        with ThreadPoolExecutor(max_workers=2) as pool:
            values = list(pool.map(lambda _: v1_forecast(cut), range(4)))
        self.assertIs(prematch_monte_carlo._allocate_periods, original)
        self.assertTrue(all(v.probabilities() == values[0].probabilities() for v in values))
        self.assertTrue(all(v.market('1Q', 50.5) == values[0].market('1Q', 50.5) for v in values))

    def test_home_handicap_sign_matches_home_margin_cover_threshold(self):
        f = gaussian_forecast([110, 100], [10, 10], np.ones((4, 2)), method='ANALYTIC')
        rows = market_grid(f, {'HOME_HANDICAP': [-5.5, 5.5]}, model_digest='fixture', prediction_utc=1736400000)
        self.assertEqual(rows[0]['raw_probabilities'], f.market('MARGIN', 5.5))
        self.assertEqual(rows[1]['raw_probabilities'], f.market('MARGIN', -5.5))
        self.assertGreater(rows[1]['raw_probabilities']['over'], rows[0]['raw_probabilities']['over'])

    def test_calibration_requires_disjoint_past_real_oos_and_scope_matches_exact_line(self):
        fit, audit = calibration_records()
        profile = MarketCalibration.fit(fit, audit, model_digest='fixture-model', market='TOTAL', line=200.5, cutoff_utc=1736300000)
        result = profile.apply([.9, .05, .05], model_digest='fixture-model', market='TOTAL', line=200.5, prediction_utc=1736400000)
        self.assertLess(result['confidence_index'], 80.)
        self.assertGreater(result['confidence_index'], 60.)
        with self.assertRaises(Abstain): profile.apply([.9, .05, .05], model_digest='fixture-model', market='TOTAL', line=201.5, prediction_utc=1736400000)
        with self.assertRaises(Abstain): profile.apply([.9, .05, .05], model_digest='fixture-model', market='TOTAL', line=200.5, prediction_utc=1736200000)
        poisoned = deepcopy(fit); poisoned[0]['model_training_ids'] = [poisoned[0]['fixture_id']]
        with self.assertRaises(ValueError): MarketCalibration.fit(poisoned, audit, model_digest='fixture-model', market='TOTAL', line=200.5, cutoff_utc=1736300000)
        late = deepcopy(fit); late[0]['inputs_available_max'] = late[0]['fixture_start_utc']+1
        with self.assertRaises(ValueError): MarketCalibration.fit(late, audit, model_digest='fixture-model', market='TOTAL', line=200.5, cutoff_utc=1736300000)

    def test_unknown_roster_missing_inputs_disagreement_and_no_profile_abstain(self):
        f = gaussian_forecast([110, 100], [10, 10], np.ones((4, 2)), method='MC')
        grid = market_grid(f, {'1Q': [45.5, 50.5], '1H': [95.5], 'TOTAL': [200.5, 210.5], 'HOME': [105.5], 'AWAY': [100.5], 'MARGIN': [0.]},
            model_digest='M', prediction_utc=1736400000, data_complete=False, model_disagreement=.4)
        self.assertEqual(len(grid), 8)
        for row in grid:
            self.assertAlmostEqual(sum(row['raw_probabilities'].values()), 1)
            self.assertEqual(row['status'], 'ABSTAIN'); self.assertIsNone(row['confidence_index'])
        message = render_research(grid, dict(model_version='<unsafe>', data_time_utc=100, prediction_utc=101, source='SYNTHETIC', inputs_digest='a'*64))
        self.assertNotIn('%', message); self.assertNotIn('Güven endeksi', message)
        self.assertIn('&lt;unsafe&gt;', message); self.assertLess(len(message), 4096)

    def test_curves_include_bin_counts_and_wilson_intervals(self):
        curve = calibration_curve([.8, .8], [1, 0])
        self.assertEqual(sum(b['n'] for b in curve), 2)
        cell = next(b for b in curve if b['n'])
        self.assertLess(cell['observed_wilson_95'][0], .5); self.assertGreater(cell['observed_wilson_95'][1], .5)


class PortableInferenceTests(TestCase):
    def test_saved_native_prediction_oracles_work_without_optional_ml_libraries(self):
        golden = json.loads((Path(__file__).parent/'fixtures/hybrid-portable-native-golden.json').read_text())
        self.assertEqual(golden['data_class'], 'SYNTHETIC_REGRESSION_NOT_PERFORMANCE')
        for name, artifact in golden['models'].items():
            portable = PortableBoostedScores.from_artifact(artifact, trusted_sha256=artifact['sha256'])
            for entry in golden['examples']:
                cut = Cut(**{k: v for k, v in entry.items() if k != 'expected'})
                np.testing.assert_allclose(portable._scores(cut), entry['expected'][name], rtol=0, atol=1e-6)

    def test_numeric_exports_match_native_predictions_and_never_train(self):
        c = synthetic_cohort(90); train = [example(c, i, 'TRAIN') for i in range(12, 42)]
        cut = feature_cut(c, c[70][0])
        for name, package in [('LIGHTGBM', 'lightgbm'), ('CATBOOST', 'catboost')]:
            if importlib.util.find_spec(package) is None: continue  # Optional-backend abstention is separately covered.
            native = BoostedScores(name, minimum_train=10, iterations=8).fit(train, cutoff_utc=c[42][0]['fixture_start_utc']-1)
            artifact = export_portable(native)
            portable = PortableBoostedScores.from_artifact(artifact, trusted_sha256=artifact['sha256'])
            np.testing.assert_allclose(portable._scores(cut), native._scores(cut), rtol=0, atol=1e-6)
            with self.assertRaises(ValueError): portable.fit(train, cutoff_utc=c[42][0]['fixture_start_utc']-1)
            tampered = deepcopy(artifact); tampered['payload']['fit_cutoff_utc'] += 1
            with self.assertRaisesRegex(ValueError, 'DIGEST'): PortableBoostedScores.from_artifact(tampered, trusted_sha256=artifact['sha256'])
            with self.assertRaises(ValueError): portable.predict(replace(cut, evaluation_class=ASSUMED))

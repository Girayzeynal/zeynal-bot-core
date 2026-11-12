"""Synthetic invariants and leakage tests; no real accuracy claims from these fixtures."""
from copy import deepcopy
from dataclasses import replace
import importlib.util
from unittest import TestCase
from unittest.mock import patch

import numpy as np

from hybrid_engine.data import ASSUMED, STRICT, Abstain, feature_cut, regulation
from hybrid_engine.distributions import Budget, Forecast
from hybrid_engine.evaluation import Ensemble, chronological_split, probability_metrics, v1_forecast
from hybrid_engine.models import BoostedScores, HierarchicalStrength
from hybrid_engine.possession import ContextTransitions, PossessionModel, Rates, _aggregate


def synthetic_cohort(n=100):
    cohort = []
    for i in range(n):
        start = 1735689600+i*172800
        teams = {}
        for side, base in [('home', 25), ('away', 23)]:
            made = base+2*((i+(side == 'away')) % 5)
            teams[side] = dict(fgm2=made, fga2=50, fgm3=10, fga3=25, ftm=20, fta=24,
                orb=10, drb=30, tov=12, fouls=18, points=2*made+50, possessions_estimate=87.56)
        scores = [teams[s]['points'] for s in ('home', 'away')]
        row = dict(league='NBA', season='SYNTHETIC', fixture_id=str(i), fixture_start_utc=start,
            home_team_id='A' if i % 2 else 'B', away_team_id='B' if i % 2 else 'A',
            final_scores=scores, periods={s: [scores[j]//4]*4 for j, s in enumerate(('home', 'away'))},
            observed_at_utc=start+10800, ingested_at_utc=start+10801, source_catalog_sha256='synthetic')
        row['box'] = dict(league='NBA', fixture_id=str(i), teams=teams, regulation_eligible=True,
            missing=['PREMATCH_LINEUP', 'INJURIES', 'CONTEXT_TRANSITION_ANNOTATIONS'],
            source=dict(observed_at_utc=start+10800, ingested_at_utc=start+10801))
        cohort.append([row])
    return cohort


def example(cohort, i, role):
    row = cohort[i][0]
    return dict(cut=feature_cut(cohort, row), label=regulation(row), row=row,
                role=role, label_available_utc=row['ingested_at_utc'])


class HybridPossessionTests(TestCase):
    def test_absorbing_reward_and_rebound_continuation(self):
        base = Rates((.1, .1, .5, .2, .1), .5, .35, .8, .2)
        reward = base.reward()
        self.assertAlmostEqual(reward.sum(), 1)
        more_rebounds = replace(base, offensive_rebound=.6).reward()
        self.assertGreater(np.dot(more_rebounds, range(4)), np.dot(reward, range(4)))
        self.assertEqual(Rates((1, 0, 0, 0, 0), .5, .3, .7, .2).reward().tolist(), [1., 0., 0., 0.])
        with self.assertRaises(Abstain): Rates((0, 0, 0, 0, 1), .5, .3, .7, .2).reward()

    def test_head_to_head_box_duplicates_do_not_change_transition_estimates(self):
        box = synthetic_cohort(1)[0][0]['box']
        entries = [(box, 'home', 'away')]
        self.assertEqual(_aggregate(entries), _aggregate(entries*3))

    def test_analytic_possession_matches_sampled_joint_law_and_all_period_sums(self):
        c = synthetic_cohort(); cut = feature_cut(c, c[80][0])
        model = PossessionModel(); analytic = model.predict(cut)
        sampled = model.predict(cut, method='MC')
        np.testing.assert_allclose(sampled.samples.sum(axis=1).mean(axis=0), analytic.scores, atol=.6)
        np.testing.assert_allclose(sampled.probabilities(), analytic.probabilities(), atol=.025)
        self.assertAlmostEqual(analytic.quarter_means.sum(), analytic.scores.sum())
        for kind, line in [('TOTAL', 200), ('MARGIN', 0), ('HOME', 100), ('AWAY', 100),
                           ('1Q', 50), ('2Q', 50), ('3Q', 50), ('4Q', 50), ('1H', 100), ('2H', 100)]:
            a = analytic.market(kind, line); b = sampled.market(kind, line)
            self.assertAlmostEqual(sum(a.values()), 1)
            np.testing.assert_allclose(list(a.values()), list(b.values()), atol=.025)
        missing = deepcopy(cut.features); missing['home']['boxes'] = []
        with self.assertRaises(Abstain): model.predict(replace(cut, features=missing))

    def test_semimarkov_requires_verified_complete_pre_cut_contexts(self):
        with self.assertRaises(Abstain): ContextTransitions().fit([], cutoff_utc=1750000000)
        records = []
        for q in range(1, 5):
            for gap in (-10, 0, 10):
                for remaining in ([300, 60] if q == 4 else [300]):
                    for i in range(5):
                        records.append(dict(provider='SYNTHETIC', fixture_id='g', possession_id=str(len(records)),
                            league='NBA', season='SYNTHETIC', annotation='VERIFIED_POSSESSION_BOUNDARY',
                            event_utc=1735689600, observed_at_utc=1735689601, ingested_at_utc=1735689602,
                            quarter=q, score_gap_before=gap, seconds_remaining_before=remaining,
                            points=i, duration_seconds=24.))
        model = ContextTransitions().fit(records, cutoff_utc=1750000000, minimum_per_context=5)
        c = synthetic_cohort(); cut = feature_cut(c, c[90][0])
        paths = model.simulate(cut)
        self.assertEqual(paths.shape, (10000, 4, 2))
        # At most 30 turns per 720-second quarter and maximum four-point reward.
        self.assertTrue(np.all(paths.sum(axis=2) <= 120))
        late = deepcopy(records); late[0]['ingested_at_utc'] = 1750000001
        with self.assertRaises(ValueError): ContextTransitions().fit(late, cutoff_utc=1750000000, minimum_per_context=5)
        with self.assertRaises(ValueError): ContextTransitions().fit(records+[records[0]], cutoff_utc=1750000000, minimum_per_context=5)


class HybridBayesTests(TestCase):
    def test_hierarchy_uncertainty_shrinkage_and_unseen_team_prior(self):
        c = synthetic_cohort(); cut = feature_cut(c, c[80][0]); cutoff = cut.cutoff_utc
        small = HierarchicalStrength(minimum_games=2).fit(cut.history[:10], cutoff_utc=cutoff, mode=STRICT)
        large = HierarchicalStrength().fit(cut.history, cutoff_utc=cutoff, mode=STRICT)
        v, _ = large._vector('A', 'B', True)
        self.assertLess(v@large.covariance@v, v@small.covariance@v)
        _, extra = large._vector('UNKNOWN', 'B', True)
        self.assertEqual(extra, 16.)
        f = large.predict(cut)
        self.assertAlmostEqual(sum(f.probabilities()), 1)
        self.assertEqual(f.metadata['player_effect'], 'NO_VERIFIED_PREMATCH_PLAYER_EXPOSURES')
        with self.assertRaises(ValueError): large.predict(replace(cut, evaluation_class=ASSUMED))
        poisoned = deepcopy(cut.history); poisoned[-1]['ingested_at_utc'] = cutoff+1
        with self.assertRaisesRegex(ValueError, 'LABEL'):
            HierarchicalStrength().fit(poisoned, cutoff_utc=cutoff, mode=STRICT)

    def test_postgame_minutes_cannot_fit_player_effects(self):
        c = synthetic_cohort(); cut = feature_cut(c, c[40][0])
        exposures = {}
        for r in cut.history:
            exposures[r['fixture_id']] = dict(observed_at_utc=r['fixture_start_utc']-3600,
                ingested_at_utc=r['fixture_start_utc']-3599,
                **{s: [dict(player_id=s+str(i), expected_minutes=48.) for i in range(5)] for s in ('home', 'away')})
        model = HierarchicalStrength().fit(cut.history, cutoff_utc=cut.cutoff_utc, mode=STRICT, projected_exposures=exposures)
        with self.assertRaises(Abstain): model.predict(cut)
        entry = deepcopy(next(iter(exposures.values())))
        f = model.predict(cut, projected_exposure=entry)
        self.assertEqual(f.metadata['player_effect'], 'PREMATCH_EXPOSURE_FITTED')
        exposures['0']['observed_at_utc'] = c[0][0]['fixture_start_utc']+1
        with self.assertRaisesRegex(ValueError, 'CLOCK'):
            HierarchicalStrength().fit(cut.history, cutoff_utc=cut.cutoff_utc, mode=STRICT, projected_exposures=exposures)


class HybridLearningTests(TestCase):
    def test_low_scoring_clipped_gaussian_mean_agrees_with_its_probability_law(self):
        from hybrid_engine.distributions import gaussian_forecast
        f = gaussian_forecast([1., 2.], [20., 20.], np.ones((4, 2)), method='ANALYTIC')
        for i, p in enumerate(f.law.pmf):
            self.assertAlmostEqual(f.scores[i], np.dot(np.arange(len(p)), p))
        self.assertGreater(f.scores[0], 1.)

    def test_v1_distribution_replay_equals_existing_engine_not_a_rewritten_sampler(self):
        from verified_analysis import project_scores
        c = synthetic_cohort(); cut = feature_cut(c, c[80][0])
        history = [dict(canonical_id=r['fixture_id'], start_ts_utc=r['fixture_start_utc'],
            home_team_id=r['home_team_id'], away_team_id=r['away_team_id'], periods=r['periods'],
            provider_fixture_ids=[r['fixture_id']]) for r in cut.history]
        expected, _ = project_scores(history, cut.target['home_team_id'], cut.target['away_team_id'])
        result = v1_forecast(cut)
        p = expected['simulation']
        self.assertEqual(result.probabilities(), [p['home_regulation_win_probability'],
            p['regulation_tie_probability'], p['away_regulation_win_probability']])

    def test_ml_backends_fit_only_train_and_residuals_only_past_heldout(self):
        c = synthetic_cohort(); train = [example(c, i, 'TRAIN') for i in range(12, 42)]
        validation = [example(c, i, 'VALIDATION') for i in range(42, 52)]
        for name, package in [('LIGHTGBM', 'lightgbm'), ('CATBOOST', 'catboost')]:
            model = BoostedScores(name, minimum_train=10, iterations=5)
            with self.assertRaisesRegex(ValueError, 'TRAIN_ROLE'):
                model.fit(validation, cutoff_utc=c[60][0]['fixture_start_utc']-1)
            cutoff = c[42][0]['fixture_start_utc']-1
            if importlib.util.find_spec(package) is None:
                with self.assertRaisesRegex(Abstain, 'NOT_INSTALLED'): model.fit(train, cutoff_utc=cutoff)
                continue
            model.fit(train, cutoff_utc=cutoff)
            self.assertIsNone(model.predict(validation[0]['cut']).probabilities())
            with self.assertRaises(ValueError): model.fit_residual_scale(train, cutoff_utc=c[60][0]['fixture_start_utc']-1, minimum=5)
            model.fit_residual_scale(validation, cutoff_utc=c[52][0]['fixture_start_utc']-1, minimum=5)
            with patch.object(model, 'fit', side_effect=AssertionError('inference must not train')):
                f = model.predict(example(c, 60, 'TEST')['cut'])
            self.assertAlmostEqual(sum(f.probabilities()), 1)

    def test_ensemble_cannot_see_test_labels_and_uses_common_coherent_weights(self):
        records = []
        for i in range(30):
            forecasts = dict(good=Forecast('good', np.full((4, 2), 25.)), bad=Forecast('bad', np.full((4, 2), 30.)))
            records.append(dict(fixture_id=str(i), role='VALIDATION', available_utc=100+i,
                                forecasts=forecasts, label=[100, 100]))
        model = Ensemble().fit(records, cutoff_utc=200)
        self.assertGreater(model.weights[model.names.index('good')], .999)
        f = model.predict(records[0]['forecasts'], cutoff_utc=201)
        np.testing.assert_allclose(f.scores, [100, 100], atol=.001)
        self.assertIsNone(f.probabilities())
        records[0]['role'] = 'TEST'
        with self.assertRaises(ValueError): Ensemble().fit(records, cutoff_utc=200)
        with self.assertRaises(ValueError): model.predict(records[0]['forecasts'], cutoff_utc=199)

    def test_split_groups_equal_kickoff_and_purges_unavailable_labels(self):
        c = synthetic_cohort(); examples = [example(c, i, 'UNASSIGNED') for i in range(12, 90)]
        examples[0]['label_available_utc'] = c[99][0]['fixture_start_utc']
        folds, split = chronological_split(examples)
        self.assertEqual(split['purged_labels'], 1)
        self.assertLess(max(e['cut'].cutoff_utc for e in folds['TRAIN']), min(e['cut'].cutoff_utc for e in folds['VALIDATION']))
        self.assertTrue(all(e['label_available_utc'] <= split['test_cutoff_utc'] for e in folds['VALIDATION']))

    def test_probability_metrics_count_draws_and_empty_calibration_bins(self):
        report = probability_metrics([[.8, .1, .1], [.1, .8, .1]], [0, 1])
        self.assertAlmostEqual(report['brier'], .06)
        self.assertAlmostEqual(report['log_loss'], -np.log(.8))
        self.assertEqual(sum(b['count'] for b in report['home_or_under_calibration']['bins']), 2)
        with self.assertRaises(ValueError): probability_metrics([[.9, .9, .9]], [0])

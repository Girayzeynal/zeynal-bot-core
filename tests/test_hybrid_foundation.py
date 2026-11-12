"""Synthetic regression fixtures; none of these are real model-performance observations."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import numpy as np

from core.team_identity import digest
from historical_research import historical_rows
from hybrid_engine.boxes import normalize_box, publish_json, seconds, url_for, collect_boxes
from hybrid_engine.data import ASSUMED, STRICT, Abstain, feature_cut, load_manifest, metadata, reference
from hybrid_engine.distributions import Budget, DiscreteNormalLaw, gaussian_forecast, halton_uniforms, periods_for_scores
from tests.test_historical_research import cohort


def box_fixture():
    row = dict(league='NBA', season='2026/2027', fixture_id='fixture', provider='ESPN',
        provider_fixture_ids=['401000001'], fixture_start_utc=1790877600,
        home_team_id='1', away_team_id='2', final_scores=[100, 90],
        periods=dict(home=[25]*4, away=[22, 23, 22, 23]))
    competitors, teams = [], []
    for side, tid, score, fg, threes in [('home', '1', 100, 40, 10), ('away', '2', 90, 36, 8)]:
        competitors.append(dict(team=dict(id=tid), homeAway=side, score=str(score),
            linescores=[dict(displayValue=str(x)) for x in row['periods'][side]]))
        stats = {'fieldGoalsMade-fieldGoalsAttempted': f'{fg}-75',
            'threePointFieldGoalsMade-threePointFieldGoalsAttempted': f'{threes}-25',
            'freeThrowsMade-freeThrowsAttempted': '10-12', 'offensiveRebounds': '10',
            'defensiveRebounds': '30', 'turnovers': '11', 'teamTurnovers': '1', 'totalTurnovers': '12', 'fouls': '20'}
        teams.append(dict(team=dict(id=tid), statistics=[dict(name=k, displayValue=v) for k, v in stats.items()]))
    doc = dict(header=dict(id='401000001', league=dict(slug='nba'), season=dict(year=2027, type=2),
        competitions=[dict(id='401000001', date='2026-10-01T18:00:00Z',
            status=dict(type=dict(state='post', completed=True)), competitors=competitors)]),
        boxscore=dict(teams=teams))
    r = dict(status='DOCUMENT_RECEIVED', http_status=200, provider='ESPN', source_url=url_for(row),
        observed_at_utc=1790888400, ingested_at_utc=1790888401, document=doc, document_sha256=digest(doc))
    return row, r


class HybridDataTests(TestCase):
    def test_strict_late_observations_abstain_and_research_never_claims_pit(self):
        c = historical_rows(cohort(late=True))
        with self.assertRaisesRegex(Abstain, 'PRE_CUTOFF'):
            feature_cut(c, c[-1][0], minimum=2)
        cut = feature_cut(c, c[-1][0], mode=ASSUMED, minimum=2)
        self.assertEqual(cut.evaluation_class, ASSUMED)
        self.assertNotIn('final_scores', cut.target)
        self.assertNotIn('periods', cut.target)
        self.assertLess(cut.cutoff_utc, cut.target['fixture_start_utc'])

    def test_target_and_future_labels_do_not_change_features_or_reference(self):
        c = historical_rows(cohort())
        before = feature_cut(c, c[-2][0], minimum=2)
        c[-2][0]['final_scores'] = [999, 999]
        c[-2][0]['periods'] = dict(home=[999]*4, away=[999]*4)
        c[-1][0]['periods'] = dict(home=[999]*4, away=[999]*4)
        after = feature_cut(c, c[-2][0], minimum=2)
        self.assertEqual(before.inputs_digest, after.inputs_digest)
        self.assertEqual(reference(before), reference(after))

    def test_late_box_source_is_not_available_even_if_score_source_was_early(self):
        c = historical_rows(cohort())
        for versions in c[:-1]:
            versions[0]['box'] = dict(source=dict(observed_at_utc=c[-1][0]['fixture_start_utc']+1,
                                                 ingested_at_utc=c[-1][0]['fixture_start_utc']+1))
        cut = feature_cut(c, c[-1][0], minimum=2)
        self.assertEqual(cut.features['home']['boxes'], [])
        cut = feature_cut(c, c[-1][0], minimum=2, mode=ASSUMED)
        self.assertGreater(len(cut.features['home']['boxes']), 0)

    def test_season_and_league_never_mix_and_reference_is_coherent(self):
        c = historical_rows(cohort())
        target = deepcopy(c[-1][0]); target['season'] = '2027/2028'
        with self.assertRaises(Abstain): feature_cut(c, target, minimum=2)
        target = deepcopy(c[-1][0]); target['league'] = 'EuroLeague'
        with self.assertRaises(Abstain): feature_cut(c, target, minimum=2)
        p = reference(feature_cut(c, c[-1][0], minimum=2))
        for s in ('home', 'away'):
            self.assertAlmostEqual(sum(p['quarters'][s]), p[s])
            self.assertAlmostEqual(sum(p['halves'][s]), p[s])

    def test_reused_reference_matches_actual_production_score_and_period_formula(self):
        from verified_analysis import project_scores
        c = historical_rows(cohort()); cut = feature_cut(c, c[-1][0])
        history = [dict(canonical_id=r['fixture_id'], start_ts_utc=r['fixture_start_utc'],
            home_team_id=r['home_team_id'], away_team_id=r['away_team_id'], periods=r['periods'],
            provider_fixture_ids=r['provider_fixture_ids']) for r in cut.history]
        current, _ = project_scores(history, cut.target['home_team_id'], cut.target['away_team_id'])
        reused = reference(cut)
        for field in ('home', 'away', 'total', 'margin', 'quarters', 'halves'):
            self.assertEqual(current[field], reused[field])

    def test_unpinned_input_and_production_paths_are_refused(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp); source = p/'data.json'; source.write_text('{}')
            m = p/'manifest.json'; m.write_text(json.dumps(dict(format='HYBRID_DATASET_MANIFEST_V1',
                files=[dict(path=str(source), sha256='0'*64, kind='CATALOG')])))
            with self.assertRaisesRegex(ValueError, 'TRUSTED_PIN'):
                load_manifest(m)
        with self.assertRaisesRegex(ValueError, 'ISOLATED'):
            load_manifest('/data/prediction_ledger.sqlite')


class HybridBoxTests(TestCase):
    def test_native_identity_arithmetic_and_total_turnovers(self):
        row, receipt = box_fixture()
        b = normalize_box(row, receipt)
        self.assertEqual(b['teams']['home']['tov'], 12)
        self.assertAlmostEqual(b['teams']['home']['possessions_estimate'], 75+.44*12-10+12)
        self.assertEqual(b['source']['observed_at_utc'], receipt['observed_at_utc'])
        self.assertIn('BOX_ESTIMATE', b['possession_measurement'])
        self.assertTrue(b['regulation_eligible'])

    def test_changed_team_score_period_or_source_binding_fails_closed(self):
        row, receipt = box_fixture()
        for change in ('team', 'score', 'period', 'source'):
            r = deepcopy(receipt)
            if change == 'team': r['document']['header']['competitions'][0]['competitors'][0]['team']['id'] = '999'
            elif change == 'score': r['document']['header']['competitions'][0]['competitors'][0]['score'] = '101'
            elif change == 'period': r['document']['header']['competitions'][0]['competitors'][0]['linescores'][0]['displayValue'] = '24'
            else: r['source_url'] += '&different=1'
            r['document_sha256'] = digest(r['document'])
            with self.subTest(change=change), self.assertRaises((ValueError, KeyError)):
                normalize_box(row, r)

    def test_nonfinite_player_seconds_and_conflicting_atomic_publication_refused(self):
        for value in (float('inf'), -1, 10000, True):
            with self.assertRaises(ValueError): seconds(value)
        with TemporaryDirectory() as tmp:
            p = Path(tmp)/'receipt.json'; publish_json(p, dict(original=True))
            first = p.read_bytes(); publish_json(p, dict(original=True))
            self.assertEqual(p.read_bytes(), first)
            with self.assertRaisesRegex(ValueError, 'CONTENT_CONFLICT'):
                publish_json(p, dict(original=False))
            self.assertEqual(p.read_bytes(), first)

    def test_429_opens_persisted_circuit_and_no_unbounded_retry(self):
        row, _ = box_fixture(); second = deepcopy(row)
        second.update(fixture_id='second', provider_fixture_ids=['401000002'])
        calls = []
        def blocked(provider, url):
            calls.append(url)
            return dict(status='SOURCE_RATE_LIMITED', http_status=429, retry_after_seconds=100)
        with TemporaryDirectory() as tmp:
            _, report = collect_boxes([[row], [second]], tmp, fetcher=blocked, workers=1)
            self.assertEqual(len(calls), 1)
            self.assertEqual([r['reason'] for r in report['failures']], ['SOURCE_RATE_LIMITED', 'SOURCE_COOLDOWN_ACTIVE'])
            collect_boxes([[row]], tmp, fetcher=blocked, workers=1)
            self.assertEqual(len(calls), 1)


class HybridDistributionTests(TestCase):
    def test_every_scenario_and_reported_mean_is_consistent(self):
        w = np.array([[20, 30], [25, 20], [30, 25], [25, 25]], dtype=float)
        f = gaussian_forecast([100, 105], [10, 12], w, budget=Budget(seconds=10))
        self.assertEqual(f.samples.shape, (10000, 4, 2))
        s = f.summary()
        self.assertAlmostEqual(sum(s['halves'][0])+sum(s['halves'][1]), s['total'])
        for side in (0, 1):
            self.assertAlmostEqual(sum(row[side] for row in s['quarters']), f.scores[side])
        scores = f.samples.sum(axis=1)
        self.assertTrue(np.array_equal(scores.sum(axis=1), f.samples.sum(axis=(1, 2))))

    def test_mc_and_qmc_reproducible_and_agree_with_analytic_law(self):
        w = np.ones((4, 2))
        a = gaussian_forecast([100, 105], [10, 12], w, method='ANALYTIC')
        for method in ('MC', 'RQMC_HALTON'):
            f = gaussian_forecast([100, 105], [10, 12], w, method=method, budget=Budget(seconds=10))
            g = gaussian_forecast([100, 105], [10, 12], w, method=method, budget=Budget(seconds=10))
            self.assertTrue(np.array_equal(f.samples, g.samples))
            self.assertAlmostEqual(sum(f.probabilities()), 1)
            self.assertLess(max(abs(x-y) for x, y in zip(f.probabilities(), a.probabilities())), .02)
            self.assertLess(abs(f.market('TOTAL', 205)['over']-a.market('TOTAL', 205)['over']), .02)

    def test_analytic_push_tie_symmetry_and_probability_mass(self):
        law = DiscreteNormalLaw([100, 100], [10, 10])
        h, tie, a = law.winner()
        self.assertAlmostEqual(h, a); self.assertGreater(tie, 0)
        for kind, line in [('TOTAL', 200), ('MARGIN', 0), ('HOME', 100), ('AWAY', 100.5)]:
            p = law.market(kind, line)
            self.assertAlmostEqual(sum(p.values()), 1)
            if line == int(line): self.assertGreater(p['push'], 0)
            else: self.assertEqual(p['push'], 0)

    def test_invalid_parameters_weights_and_large_scenario_requests_refused(self):
        for n in (9999, 1000000, True):
            with self.assertRaises(ValueError): Budget(scenarios=n).validate()
        for w in (np.zeros((4, 2)), np.full((4, 2), float('nan')), np.ones((2, 2))):
            with self.assertRaises(ValueError): gaussian_forecast([100, 100], [10, 10], w)
        with self.assertRaises(ValueError): DiscreteNormalLaw([100, float('inf')], [10, 10])
        with self.assertRaises(ValueError): DiscreteNormalLaw([100, 100], [0, 10])

    def test_runtime_and_memory_budget_fail_closed(self):
        with patch('hybrid_engine.distributions.time.perf_counter', side_effect=[0, 99]):
            with self.assertRaisesRegex(Abstain, 'RUNTIME_BUDGET'):
                gaussian_forecast([100, 100], [10, 10], np.ones((4, 2)))
        with patch('hybrid_engine.distributions.time.perf_counter', return_value=0):
            with self.assertRaisesRegex(Abstain, 'MEMORY_BUDGET'):
                Budget(array_bytes=1000000).check(0, (np.empty(200000),))

    def test_halton_range_and_period_allocation_edge_cases(self):
        u = halton_uniforms(10000, 12)
        self.assertTrue(np.all((u > 0) & (u < 1)))
        scores = np.array([[0, 1], [1, 0], [101, 103]])
        p = periods_for_scores(scores, np.ones((4, 2)))
        self.assertTrue(np.array_equal(p.sum(axis=1), scores))
        self.assertTrue(np.all(p >= 0))

    def test_correlated_sampler_and_unsupported_analytic_case_are_explicit(self):
        f = gaussian_forecast([100, 100], [10, 10], np.ones((4, 2)), correlation=.6, budget=Budget(seconds=10))
        scores = f.samples.sum(axis=1)
        self.assertAlmostEqual(float(np.corrcoef(scores.T)[0, 1]), .6, delta=.025)
        with self.assertRaisesRegex(Abstain, 'CORRELATED_ANALYTIC'):
            gaussian_forecast([100, 100], [10, 10], np.ones((4, 2)), method='ANALYTIC', correlation=.6)

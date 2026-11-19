"""Real receipt regression + synthetic counterexamples; never live accuracy evidence."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tarfile
from unittest import TestCase
from unittest.mock import patch

import numpy as np

from core.team_identity import digest
from historical_research import historical_rows
from hybrid_engine.adaptive_data import native_catalog
from hybrid_engine.chronological_engine_study import evaluate,_pace_kernels,_metrics,CORE_MODELS,PACE_MODELS
from hybrid_engine.data import STRICT,ASSUMED
from hybrid_engine.research_history_union import union
from tests.test_adaptive_research import cohort

ROOT=Path(__file__).resolve().parents[1]


class HistoryConsensusTests(TestCase):
    def test_real_scoreboard_summary_stats_do_not_create_false_result_conflict(self):
        packet=ROOT/'docs/evidence/nba-phase843-resource-inputs-20261113.tar.gz'
        before=hashlib.sha256(packet.read_bytes()).hexdigest();catalogs=[]
        with tarfile.open(packet) as tar:
            for member in tar:
                if member.isfile() and member.name.startswith('source-'):
                    r=json.load(tar.extractfile(member))
                    if not any(s in r['source_url'] for s in ('/scoreboard?','/summary?event=')):continue
                    c=native_catalog(r,'NBA',2026);catalogs.append((c,c['sha256']))
        with self.assertRaisesRegex(ValueError,'CONFLICTING_HISTORICAL_RESULT'):historical_rows(catalogs)
        rows=union(catalogs)
        self.assertEqual(len(rows),79)
        self.assertTrue(any(len(v)>1 for v in rows))
        self.assertEqual(before,hashlib.sha256(packet.read_bytes()).hexdigest())

    def row(self):
        r=cohort(1)[0][0];r['record_type']='HISTORICAL_DATA';return r

    def merged(self,rows):
        def decode(pair):return [[deepcopy(pair[0][0])]]
        with patch('hybrid_engine.research_history_union.historical_rows',side_effect=decode):
            return union([(r,str(i)) for i,r in enumerate(rows)])

    def test_optional_statistics_remain_at_their_actual_source_version_clock(self):
        early=self.row();early.pop('box',None);late=deepcopy(early)
        late['ingested_at_utc']+=100;late['team_statistics']={'late':True}
        rows=self.merged([early,late,early]);self.assertEqual(len(rows),1);self.assertEqual(len(rows[0]),2)
        self.assertNotIn('team_statistics',rows[0][0]);self.assertTrue(rows[0][1]['team_statistics']['late'])
        self.assertEqual(rows[0][0]['ingested_at_utc'],early['ingested_at_utc'])

    def test_actual_core_score_conflict_remains_fatal(self):
        a=self.row();b=deepcopy(a);b['final_scores'][0]+=1
        with self.assertRaisesRegex(ValueError,'CORE_RESULT_CONFLICT'):self.merged([a,b])

    def test_provider_id_cannot_point_to_another_fixture(self):
        a=self.row();b=deepcopy(a);b['fixture_id']='other'
        with self.assertRaisesRegex(ValueError,'PROVIDER_ID_CONFLICT'):self.merged([a,b])

    def test_team_cannot_play_two_fixtures_at_the_same_time(self):
        a=self.row();b=deepcopy(a);b.update(fixture_id='other',provider_fixture_ids=['999999999'])
        with self.assertRaisesRegex(ValueError,'TEAM_START_CONFLICT'):self.merged([a,b])


class ChronologicalStudyTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows=cohort(66)
        for v in cls.rows:
            r=v[0];r['box_versions']=[r.pop('box')]
        cls.report=evaluate(cls.rows,mode=STRICT)

    def test_disjoint_whole_day_training_and_test_boundary(self):
        r=self.report;self.assertIn('EXPLORATORY',r['status'])
        test=r['cases']['FAZ13_NATIVE'];test=[v for v in test if v['role']=='TEST']
        ids={v['fixture_id'] for v in test}
        self.assertFalse(ids & set(r['split']['development_ids']))
        for cases in r['cases'].values():
            for row in cases:
                if row['role']=='TEST':
                    self.assertFalse(ids & set(row['fit_ids']));self.assertFalse(ids & set(row['feature_ids']))
                    self.assertLess(row['raw_source_clock_max'],row['start_utc'])
        self.assertFalse(r['calibration_fit']);self.assertIsNone(r['confidence_index']);self.assertEqual(r['acceptance'],'NO_GO')
        self.assertEqual(r['observed_bookmaker_comparison']['n'],0)

    def test_test_outcome_mutation_changes_metrics_but_no_prediction_or_fit(self):
        changed=deepcopy(self.rows);boundary=self.report['split']['test_start_utc']
        for v in changed:
            r=v[0]
            if r['fixture_start_utc']>=boundary:
                r['periods']['home'][0]+=10;r['final_scores'][0]+=10
        after=evaluate(changed,mode=STRICT)
        for name in CORE_MODELS+PACE_MODELS:
            a=self.report['cases'][name];b=after['cases'][name]
            self.assertEqual([{k:v for k,v in x['prediction'].items() if k!='metadata'} for x in a],
                             [{k:v for k,v in x['prediction'].items() if k!='metadata'} for x in b])
            self.assertEqual([x.get('simulation_diagnostics',{}).get('sample_sha256') for x in a],
                             [x.get('simulation_diagnostics',{}).get('sample_sha256') for x in b])
            self.assertEqual([x['inputs_digest'] for x in a],[x['inputs_digest'] for x in b])
            self.assertEqual([x['fit_ids'] for x in a],[x['fit_ids'] for x in b])
        self.assertNotEqual(self.report['models']['FAZ13_NATIVE']['test']['total'],after['models']['FAZ13_NATIVE']['test']['total'])

    def test_late_sources_abstain_by_default_without_rewriting_clocks(self):
        changed=deepcopy(self.rows)
        for v in changed:
            v[0]['observed_at_utc']=2000000000;v[0]['ingested_at_utc']=2000000001
        before=digest(changed);r=evaluate(changed)
        self.assertEqual(r['status'],'ABSTAIN_INSUFFICIENT_PRE_ORIGIN_TRAINING');self.assertFalse(r['models'])
        self.assertEqual(digest(changed),before);self.assertFalse(r['native_source_clocks_rewritten'])

    def test_scenario_lines_are_identical_for_all_models_and_not_bookmaker_quotes(self):
        by_fixture={}
        for cases in self.report['cases'].values():
            for row in cases:
                line=row['markets']['TOTAL']['line']
                self.assertEqual(by_fixture.setdefault(row['fixture_id'],line),line)
                self.assertIn('NOT_BOOKMAKER',row['line_kind'])
        compare=self.report['matched_test_comparisons'][PACE_MODELS[0]]
        self.assertEqual(compare['baseline']['n'],compare['candidate']['n'])

    def test_strict_boxes_select_available_version_and_never_use_late_replacement(self):
        history=deepcopy([v[0] for v in self.rows[:40]]);target=self.rows[50][0]
        original=_pace_kernels(history,target,STRICT)
        for r in history:
            b=deepcopy(r['box_versions'][0]);b['source']['ingested_at_utc']=target['fixture_start_utc']+1
            b['teams']['home']['fga2']+=100;r['box_versions'].append(b)
        after=_pace_kernels(history,target,STRICT)
        for name in PACE_MODELS:np.testing.assert_array_equal(original[name].samples,after[name].samples)

    def test_pace_ablation_holds_efficiency_inputs_constant_and_labels_box_estimate(self):
        history=[v[0] for v in self.rows[:40]];f=_pace_kernels(history,self.rows[50][0],STRICT)
        a,b=[f[name] for name in PACE_MODELS]
        self.assertEqual(a.metadata['same_rate_fit_ids'],b.metadata['same_rate_fit_ids'])
        self.assertEqual(a.metadata['population_box_ids'],b.metadata['population_box_ids'])
        for value in f.values():
            self.assertFalse(value.metadata['measured_pbp']);self.assertEqual(value.samples.shape,(10000,4,2))
            self.assertTrue((value.samples>=0).all());self.assertAlmostEqual(sum(value.probabilities()),1)

    def test_period_totals_are_measured_separately_from_team_periods(self):
        row=deepcopy(self.report['cases']['FAZ13_NATIVE'][-1]);q=np.asarray(row['prediction']['quarters'])
        row['actual_quarters']=q.tolist();row['actual_quarters'][0][0]+=2;row['actual_quarters'][0][1]-=2
        m=_metrics([row]);self.assertAlmostEqual(m['period_totals']['1Q']['mae'],0)
        self.assertAlmostEqual(m['periods']['1Q']['mae'],2)

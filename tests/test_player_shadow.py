"""Synthetic inference/leakage contracts; not real accuracy evidence."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import numpy as np

from core.team_identity import digest
from hybrid_engine.data import Abstain,feature_cut
from hybrid_engine.models import HierarchicalStrength
from hybrid_engine.player_shadow import PreparedPlayerPair,fit_pair,capture_pair,readiness,performance
from tests import test_hybrid_models as models
from tests import test_player_minutes as minutes


def case_for(row):
    data=minutes.inputs(fixture=row['fixture_id'],start=row['fixture_start_utc'],now=row['fixture_start_utc']-1800)
    data['context']['season']='SYNTHETIC'
    for r in data['rosters'].values(): r['season']='SYNTHETIC'
    for b in data['boxes']: b['season']='SYNTHETIC'
    if row['home_team_id']=='2':
        data['context']['home']['provider_id']='2'; data['context']['away']['provider_id']='1'
        data['rosters']['home'],data['rosters']['away']=data['rosters']['away'],data['rosters']['home']
    return data


class PlayerShadowTests(TestCase):
    @classmethod
    def setUpClass(cls):
        tmp=TemporaryDirectory(); cls.addClassCleanup(tmp.cleanup); cls.root=Path(tmp.name)
        cls.cohort=models.synthetic_cohort(80)
        for versions in cls.cohort:
            for r in versions:
                for s in ('home','away'): r[s+'_team_id']='1' if r[s+'_team_id']=='A' else '2'
        cls.now=cls.cohort[70][0]['fixture_start_utc']-1800
        cls.cutoff=cls.cohort[50][0]['fixture_start_utc']
        cls.publications=[]
        for versions in cls.cohort[:40]:
            row=versions[0]
            with patch('time.time',return_value=row['fixture_start_utc']-1800):
                cls.publications.append(minutes.archive_inputs(cls.root,case_for(row)))
        with patch('time.time',return_value=cls.now):
            cls.artifact,cls.audit=fit_pair(cls.cohort,cls.publications,cls.root,cutoff_utc=cls.cutoff,minimum_games=30)

    def setUp(self):
        timer=patch('time.time',return_value=self.now); timer.start(); self.addCleanup(timer.stop)

    def pair(self):
        return PreparedPlayerPair(self.artifact,trusted_sha256=self.artifact['sha256'])

    def target(self):
        return replace(feature_cut(self.cohort,self.cohort[70][0]),cutoff_utc=self.now)

    def target_publication(self,root):
        return minutes.archive_inputs(root,case_for(self.cohort[70][0]))

    def test_missing_prospective_minutes_never_fits(self):
        with patch.object(HierarchicalStrength,'fit',side_effect=AssertionError('NO_FIT')):
            artifact,audit=fit_pair(self.cohort,[],self.root,cutoff_utc=self.cutoff)
        self.assertIsNone(artifact); self.assertEqual(audit['eligible_games'],0)
        self.assertGreater(audit['exclusions']['NO_PROSPECTIVE_MINUTES_PUBLICATION'],0)
        self.assertEqual(audit['status'],'INSUFFICIENT_PROSPECTIVE_PLAYER_INPUTS')

    def test_joint_pair_uses_same_training_games_and_exposes_limits(self):
        p=self.artifact['payload']
        self.assertEqual(p['baseline']['training_ids'],p['candidate']['training_ids'])
        self.assertEqual(len(p['candidate']['training_ids']),40)
        self.assertEqual(p['baseline']['players'],[]); self.assertTrue(p['candidate']['players'])
        for k in ('individual_defense_fitted','measured_pace_fitted','minute_uncertainty_calibrated','production_enabled'):
            self.assertFalse(p[k])

    def test_loaded_parameters_equal_the_pinned_artifact(self):
        p=self.pair()
        np.testing.assert_array_equal(p.candidate.coefficients,self.artifact['payload']['candidate']['coefficients'])
        self.assertEqual(p.candidate.training_ids,p.baseline.training_ids)

    def test_artifact_tampering_scope_future_label_and_bad_posterior_are_rejected(self):
        for kind in ('pin','code','training','nan','baseline_future','covariance'):
            a=deepcopy(self.artifact); p=a['payload']
            if kind=='pin': a['sha256']='0'*64
            elif kind=='code': p['source_code_pins']['models.py']='0'*64
            elif kind=='training': p['baseline']['training_ids'][0]='FOREIGN'
            elif kind=='nan': p['candidate']['coefficients'][0]=float('nan')
            elif kind=='baseline_future': p['baseline']['training_available_max']=self.now+1
            else: p['candidate']['covariance'][0][0]=-1
            with self.subTest(kind=kind),self.assertRaises(ValueError):
                if kind!='pin': a['sha256']=digest(p)
                PreparedPlayerPair(a,trusted_sha256=a['sha256'])

    def test_inference_does_not_fit_and_projections_are_coherent(self):
        with TemporaryDirectory() as tmp:
            publication=self.target_publication(tmp); pair=self.pair()
            with patch.object(HierarchicalStrength,'fit',side_effect=AssertionError('INFERENCE_MUST_NOT_FIT')):
                forecasts=pair.predict(self.target(),publication['projection'])
        self.assertEqual(set(forecasts),{'TEAM_BAYES','PLAYER_BAYES','FAZ13_REFERENCE'})
        for f in forecasts.values():
            self.assertAlmostEqual(f.quarter_means.sum(),f.scores.sum())
            self.assertAlmostEqual(sum(f.probabilities()),1)
        self.assertIsNone(forecasts['PLAYER_BAYES'].metadata['confidence_index'])

    def test_unseen_player_effect_is_not_invented(self):
        with TemporaryDirectory() as tmp:
            packet=deepcopy(self.target_publication(tmp)['projection'])
            packet['payload']['home'][0]['player_id']='999999'; packet['sha256']=digest(packet['payload'])
            with self.assertRaisesRegex(Abstain,'FIVE_PAST'): self.pair().predict(self.target(),packet)

    def test_future_cutoff_history_and_training_overlap_are_refused(self):
        with TemporaryDirectory() as tmp:
            packet=self.target_publication(tmp)['projection']; cut=self.target()
            bad_history=deepcopy(cut.history); bad_history[-1]['ingested_at_utc']=self.now+1
            cases=[replace(cut,cutoff_utc=self.now+1),replace(cut,history=bad_history),
                   replace(cut,target=dict(cut.target,fixture_id='0'))]
            for c in cases:
                with self.assertRaises(ValueError): self.pair().predict(c,packet)

    def test_repeated_capture_does_not_resimulate_or_rewrite_originals(self):
        with TemporaryDirectory() as tmp:
            publication=self.target_publication(tmp); before=deepcopy(publication); pair=self.pair()
            record,created=capture_pair(pair,self.target(),publication,tmp)
            self.assertTrue(created); self.assertEqual(publication,before)
            files={p:p.read_bytes() for p in Path(tmp).rglob('*') if p.is_file()}
            with patch.object(pair,'predict',side_effect=AssertionError('NO_RESIMULATION')):
                again,created=capture_pair(pair,self.target(),publication,tmp)
            self.assertFalse(created); self.assertEqual(again,record)
            self.assertEqual(files,{p:p.read_bytes() for p in files})

    def test_new_capture_after_tipoff_is_refused(self):
        with TemporaryDirectory() as tmp:
            publication=self.target_publication(tmp); pair=self.pair()
            with patch('time.time',return_value=self.cohort[70][0]['fixture_start_utc']):
                with self.assertRaises(ValueError): capture_pair(pair,self.target(),publication,tmp)

    def test_readiness_does_not_claim_real_training_or_calibration(self):
        with TemporaryDirectory() as tmp:
            self.assertEqual(readiness(tmp)['prospective_minutes_games'],0)
            self.target_publication(tmp); r=readiness(tmp)
            self.assertEqual(r['prospective_minutes_games'],1)
            self.assertEqual(r['minimum_fit_games'],100); self.assertEqual(r['prepared_artifacts'],0)
            self.assertFalse(r['production_enabled'])

    def test_old_ledger_results_without_published_shadow_pairs_are_not_counted(self):
        with TemporaryDirectory() as tmp,patch('ledger_reports.LedgerReports.read',return_value=dict(forecasts=[])):
            r=performance(tmp,Path(tmp)/'no-database-created.sqlite')
            self.assertEqual(r['n'],0); self.assertEqual(r['groups'],[])
            self.assertFalse(r['calibration_fit']); self.assertIsNone(r['confidence_index'])

    def test_native_final_metrics_are_paired_and_small_sample_remains_insufficient(self):
        with TemporaryDirectory() as tmp:
            publication=self.target_publication(tmp); capture_pair(self.pair(),self.target(),publication,tmp)
            start=self.cohort[70][0]['fixture_start_utc']
            label=dict(fixture_id=self.cohort[70][0]['fixture_id'],actual=[100,92],
                actual_periods=dict(home=[25]*4,away=[23]*4),fixture_start_utc=start,label_available_utc=start+10800)
            with patch('time.time',return_value=start+10800),patch('ledger_reports.LedgerReports.read',return_value=dict(forecasts=[label])):
                r=performance(tmp,Path(tmp)/'native.sqlite')
            self.assertEqual(r['n'],1); g=r['groups'][0]; self.assertEqual(g['status'],'INSUFFICIENT_FUTURE_AUDIT')
            for m in g['metrics'].values(): self.assertEqual(m['n'],1)
            self.assertEqual(g['paired_comparisons']['FAZ13_REFERENCE']['n'],1)

    def test_future_final_is_pending_and_not_performance(self):
        with TemporaryDirectory() as tmp:
            publication=self.target_publication(tmp); capture_pair(self.pair(),self.target(),publication,tmp)
            label=dict(fixture_id=self.cohort[70][0]['fixture_id'],actual=[100,92],label_available_utc=self.now+100000)
            with patch('ledger_reports.LedgerReports.read',return_value=dict(forecasts=[label])):
                r=performance(tmp,Path(tmp)/'native.sqlite')
            self.assertEqual(r['n'],0); self.assertEqual(r['pending'],1)

    def test_multiple_fit_versions_do_not_inflate_distinct_fixture_count(self):
        with TemporaryDirectory() as tmp:
            publication=self.target_publication(tmp)
            capture_pair(self.pair(),self.target(),publication,tmp)
            a=deepcopy(self.artifact)
            a['payload']['research_note']='SYNTHETIC_SECOND_BUILD'
            a['sha256']=digest(a['payload'])
            other=PreparedPlayerPair(a,trusted_sha256=a['sha256'])
            capture_pair(other,self.target(),publication,tmp)
            start=self.cohort[70][0]['fixture_start_utc']
            label=dict(fixture_id=self.cohort[70][0]['fixture_id'],actual=[100,92],
                actual_periods=dict(home=[25]*4,away=[23]*4),fixture_start_utc=start,label_available_utc=start+10800)
            with patch('time.time',return_value=start+10800),patch('ledger_reports.LedgerReports.read',return_value=dict(forecasts=[label])):
                r=performance(tmp,Path(tmp)/'native.sqlite')
            self.assertEqual(r['n'],1)
            self.assertEqual(r['paired_version_records'],2)
            self.assertEqual(len(r['groups']),2)
            self.assertTrue(r['versions_not_pooled'])

    def test_conflicting_offline_flags_are_refused_before_any_fit_or_writes(self):
        from contextlib import redirect_stderr
        from io import StringIO
        from hybrid_engine.player_shadow import main
        with TemporaryDirectory() as tmp:
            argv=['player_shadow','--directory',tmp,'--history-manifest','missing-fit.json',
                  '--capture-manifest','missing-capture.json','--fixture-id','future',
                  '--model-artifact','missing-model.json','--model-sha','a'*64]
            with patch('sys.argv',argv),patch('hybrid_engine.player_shadow.fit_pair') as fit:
                with redirect_stderr(StringIO()),self.assertRaises(SystemExit) as error:
                    main()
            self.assertEqual(error.exception.code,2)
            fit.assert_not_called()
            self.assertEqual(list(Path(tmp).iterdir()),[])

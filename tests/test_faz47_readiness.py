"""Mock/fake source protocols. No real model-performance or Cloud claims."""
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from prediction_inputs import digest
from faz41_evidence import REGISTRY
from faz44_inputs import make_bundle
from faz47_readiness import readiness_report,main
from tests.test_faz42_history import NOW,permitted_registry
from tests.test_faz42_prospective import test_model as synthetic_model
from tests.test_faz47_history_binding import pair


class ResearchReadinessTests(TestCase):
    def setUp(self):
        self.timer=patch('time.time',return_value=NOW);self.timer.start();self.addCleanup(self.timer.stop)
        self.records,self.proof=pair(REGISTRY)

    def test_unknown_policy_exposes_coverage_and_no_metrics_or_forecast(self):
        with patch('prematch_monte_carlo.PrematchMonteCarloEngine.simulate') as simulation:r=readiness_report(self.proof)
        simulation.assert_not_called();self.assertEqual(r['evaluated_prediction_result_pairs'],0);self.assertEqual(r['prospective_records_created'],0)
        nba=r['leagues']['NBA'];self.assertEqual(nba['input_games'],10);self.assertEqual(nba['latest_target']['status'],'ABSTAIN');self.assertIsNone(nba['latest_target']['prediction'])
        for cohort in nba['evaluation']['cohorts'].values():self.assertIsNone(cohort['metrics']);self.assertIsNone(cohort['period_metrics'])
        self.assertEqual(r['leagues']['EUROLEAGUE']['status'],'ABSTAIN_NO_SCORE_ARCHIVE')

    def test_split_is_chronological_and_never_uses_context_from_later_games(self):
        r=readiness_report(self.proof);evaluation=r['leagues']['NBA']['evaluation'];split=evaluation['split']
        self.assertLess(split['train_end_utc'],split['validation_end_utc']);self.assertTrue(split['ties_share_partition'])
        for fold in evaluation['folds']:
            start=fold['target']['start_utc'];self.assertLess(fold['cutoff_utc'],start)
            self.assertGreaterEqual(start,split['train_end_utc'] if fold['role']=='VALIDATION' else split['validation_end_utc'])
        self.assertEqual(r['leagues']['NBA']['latest_target']['context_observations'],0)

    def test_no_chronological_groups_does_not_force_train_validation_test(self):
        r=readiness_report(self.proof[:2]);nba=r['leagues']['NBA']
        self.assertEqual(nba['evaluation']['status'],'ABSTAIN_INSUFFICIENT_CHRONOLOGICAL_GROUPS');self.assertIsNone(nba['evaluation']['cohorts'])
        self.assertEqual(r['evaluated_prediction_result_pairs'],0)

    def test_mock_permitted_pit_sources_exercise_metrics_without_fitting_coefficients(self):
        registry=permitted_registry();records,proof=pair(registry)
        r=readiness_report(proof,minimum_team_games=2,minimum_evaluation_games=2,registry=registry,registry_pin=digest(registry))
        self.assertGreaterEqual(r['evaluated_prediction_result_pairs'],4);self.assertFalse(r['coefficients_fitted']);self.assertFalse(r['production_coefficients_changed'])
        self.assertEqual(r['calibration_status'],'NOT_ESTABLISHED');self.assertEqual(r['prospective_records_created'],0)

    def test_empty_universe_invalid_clock_settings_and_mixed_sidecar_are_fail_closed(self):
        r=readiness_report([]);self.assertEqual(r['evaluated_prediction_result_pairs'],0)
        for kw in [dict(asof_utc=NOW+1),dict(minimum_team_games=1),dict(simulations=9999),dict(minimum_evaluation_games=True)]:
            with self.subTest(kw=kw),self.assertRaises(ValueError):readiness_report(self.proof,**kw)
        bad=dict(payload=dict(usage='SYNTHETIC_TEST'))
        with self.assertRaisesRegex(ValueError,'MIXED_SYNTHETIC_REAL'):readiness_report(self.proof,roster_observations=[bad])

    def bundle(self):
        model=synthetic_model();model['payload']['purpose']='EXPERIMENTAL_DRY_RUN';model['sha256']=digest(model['payload'])
        return make_bundle(self.proof,[],model,days=['2026-11-06']),model

    def test_cli_is_readonly_locally_publishes_only_research_and_never_calls_network(self):
        bundle,model=self.bundle()
        with TemporaryDirectory() as folder:
            source=Path(folder)/'source.json';source.write_text(json.dumps(bundle));before=source.read_bytes();out=Path(folder)/'faz47-readiness-test.json';stream=StringIO()
            args=['faz47_readiness','--score-inputs',str(source),'--trusted-score-sha256',bundle['sha256'],'--output',str(out)]
            with patch('sys.argv',args),redirect_stdout(stream),patch('faz47_readiness.model_manifest',return_value=model),patch('faz47_readiness.verify_execution_manifest',return_value=True) as verify:
                self.assertEqual(main(),0)
            result=json.loads(stream.getvalue());self.assertEqual(result['network_requests'],0);self.assertEqual(result['evaluated_prediction_result_pairs'],0);self.assertEqual(verify.call_count,2)
            self.assertEqual(source.read_bytes(),before);self.assertEqual(out.stat().st_mode&0o777,0o600)
            self.assertEqual(json.loads(out.read_text())['payload']['prospective_records_created'],0)

    def test_git_change_after_evaluation_refuses_publication_and_preserves_inputs(self):
        bundle,model=self.bundle()
        with TemporaryDirectory() as folder:
            source=Path(folder)/'source.json';source.write_text(json.dumps(bundle));before=source.read_bytes();out=Path(folder)/'faz47-readiness-test.json'
            args=['faz47_readiness','--score-inputs',str(source),'--trusted-score-sha256',bundle['sha256'],'--output',str(out)]
            with patch('sys.argv',args),redirect_stdout(StringIO()),patch('faz47_readiness.model_manifest',return_value=model),patch('faz47_readiness.verify_execution_manifest',side_effect=[True,ValueError('CHANGED')]):
                self.assertEqual(main(),1)
            self.assertFalse(out.exists());self.assertEqual(source.read_bytes(),before)

    def test_wrong_pin_never_calls_the_research_model_or_publishes_output(self):
        bundle,model=self.bundle()
        with TemporaryDirectory() as folder:
            source=Path(folder)/'source.json';source.write_text(json.dumps(bundle));out=Path(folder)/'faz47-readiness-test.json'
            args=['faz47_readiness','--score-inputs',str(source),'--trusted-score-sha256','0'*64,'--output',str(out)]
            with patch('sys.argv',args),redirect_stdout(StringIO()),patch('faz47_readiness.readiness_report') as research:
                self.assertEqual(main(),1);research.assert_not_called()
            self.assertFalse(out.exists())

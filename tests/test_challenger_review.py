"""Real frozen inputs and explicit synthetic counterexamples, not Telegram E2E."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from core.team_identity import digest
from hybrid_engine.challenger_review import NAMES, predict_snapshot, run, summarize_cases, main
from hybrid_engine.data import Abstain
from tests import test_phase90 as native
ROOT=native.ROOT


def native_final():
    with tarfile.open(ROOT/'docs/evidence/phase924-append-only-official-nba-finals-20261116.tar.gz') as tar:
        member = next(m for m in tar if m.name.startswith('summary-401909985-'))
        return json.loads(tar.extractfile(member).read())


def outcome_row(p):
    receipt = native_final()
    competitors = receipt['document']['header']['competitions'][0]['competitors']
    periods = {r['homeAway']: [int(v['displayValue']) for v in r['linescores']] for r in competitors}
    return dict(fixture_id=p['fixture_id'], league=p['league'], season=p['season'],
        model_digest=p['model_digest'], model_version=p['model_version'],
        prediction=[p['prediction'][s] for s in ('home', 'away')],
        predicted_quarters=p['prediction']['quarters'], predicted_halves=p['prediction']['halves'],
        intervals=p['intervals'], winner=p['prediction']['winner'],
        actual=[sum(periods[s][:4]) for s in ('home', 'away')], actual_periods=periods,
        label_available_utc=receipt['ingested_at_utc'], fixture_start_utc=p['fixture_start_utc'],
        prediction_generated_at_utc=p['prediction_generated_at_utc'], created_utc=p['created_at_utc'],
        first_archived_at_utc=p['created_at_utc'], snapshot_sha256=digest(p),
        provider_fixture_ids=p['provider_fixture_ids'], home=p['home']['official_name'], away=p['away']['official_name'])


class NativeChallengerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.h = native.FrozenPhiladelphiaAudit('runTest'); cls.h.setUp()
        cls.addClassCleanup(cls.h.doCleanups)
        with patch('requests.get', side_effect=AssertionError('NO NETWORK')):
            cls.experiment = predict_snapshot(cls.h.p, cls.h.assets)
        cls.row = outcome_row(cls.h.p)

    def case(self): return dict(original=deepcopy(self.row), experiment=deepcopy(self.experiment))

    def test_real_inputs_reused_frozen_projection_not_replaced(self):
        self.assertEqual(self.experiment['snapshot_sha256'], digest(self.h.p))
        c = self.experiment['components']
        self.assertEqual(set(c), set(NAMES))
        self.assertEqual(c['FROZEN_ARCHIVED']['prediction'], self.h.p['prediction'])
        self.assertEqual(c['FROZEN_ARCHIVED']['intervals'], self.h.p['intervals'])
        self.assertEqual(self.row['actual'], [131,124])

    def test_refit_is_past_only_and_not_the_target_outcome(self):
        c = self.experiment['components']['UPDATED_BAYES_QMC']
        self.assertEqual(c['status'], 'AVAILABLE')
        self.assertEqual(c['parameter_fit_cutoff_utc'], self.h.p['feature_cutoff_utc'])
        self.assertLessEqual(self.experiment['history_available_max_utc'], c['parameter_fit_cutoff_utc'])
        self.assertNotIn(self.h.p['fixture_id'], self.experiment['training_ids'])
        self.assertNotEqual(c['fit_sha256'], self.h.p['prepared_artifact_sha256'])

    def test_missing_boxes_abstain_instead_of_inventing_pace_or_player_effect(self):
        for name in ('POSSESSION_MC','POSSESSION_ANALYTIC'):
            c = self.experiment['components'][name]
            self.assertEqual(c['status'], 'ABSTAIN')
            self.assertIn('INSUFFICIENT_PAST_BOXES', c['reason'])
        p = self.experiment['components']['UPDATED_BAYES_QMC']['prediction']
        self.assertEqual(p['metadata']['player_effect'], 'NO_VERIFIED_PREMATCH_PLAYER_EXPOSURES')
        self.assertEqual(p['calibration_status'], 'NOT_CALIBRATED')

    def test_stochastic_periods_preserve_full_game_means_and_bands(self):
        c = self.experiment['components']; a = c['UPDATED_BAYES_QMC']; b = c['UPDATED_BAYES_STOCHASTIC_PERIODS']
        self.assertEqual(a['prediction']['quarters'], b['prediction']['quarters'])
        for market in ('TOTAL','HOME','AWAY','MARGIN','HOME_HANDICAP'):
            self.assertEqual(a['intervals']['markets'][market], b['intervals']['markets'][market])
        self.assertNotEqual(a['intervals']['sample_sha256'], b['intervals']['sample_sha256'])
        self.assertNotEqual(a['intervals']['markets']['1Q'], b['intervals']['markets']['1Q'])

    def test_mc_and_qmc_use_identical_refitted_parameters(self):
        c = self.experiment['components']; a = c['UPDATED_BAYES_QMC']; b = c['UPDATED_BAYES_MC']
        self.assertEqual(a['fit_sha256'], b['fit_sha256'])
        self.assertEqual(a['prediction']['total'], b['prediction']['total'])
        self.assertNotEqual(a['intervals']['sample_sha256'], b['intervals']['sample_sha256'])

    def test_native_summary_contains_paired_faz13_and_small_cluster_abstention(self):
        group = summarize_cases([self.case()])[0]
        self.assertEqual(group['n'], 1); self.assertEqual(group['day_clusters'], 1)
        p = group['paired']['FAZ13_REFERENCE']['UPDATED_BAYES_QMC']
        self.assertEqual(p['n_common'], 1)
        self.assertEqual(p['points']['status'], 'INSUFFICIENT_DAY_CLUSTERS_FOR_CLAIM')
        self.assertIsNone(p['points']['metrics']['total_mae']['interval'])
        self.assertIsNone(group['confidence_index'])
        self.assertEqual(group['models']['FROZEN_ARCHIVED']['n'], 1)
        self.assertAlmostEqual(group['models']['FROZEN_ARCHIVED']['total']['mae'], 33.21108196198506)

    def test_changing_evaluation_result_cannot_change_predictor_output(self):
        case = self.case(); before = digest(case['experiment']); case['original']['actual'][0] += 4
        case['original']['actual_periods']['home'][0] += 4
        a = summarize_cases([self.case()])[0]; b = summarize_cases([case])[0]
        self.assertNotEqual(a['models']['UPDATED_BAYES_QMC']['total']['mae'], b['models']['UPDATED_BAYES_QMC']['total']['mae'])
        self.assertEqual(digest(case['experiment']), before)

    def test_failed_candidate_is_not_compared_on_another_cohort(self):
        case = self.case(); case['experiment']['components']['UPDATED_BAYES_MC'] = dict(status='ABSTAIN',reason='SYNTHETIC_TIMEOUT')
        group = summarize_cases([case])[0]
        self.assertEqual(group['models']['UPDATED_BAYES_MC']['n'], 0)
        self.assertEqual(group['paired']['FAZ13_REFERENCE']['UPDATED_BAYES_MC']['n_common'], 0)
        self.assertEqual(group['abstentions']['UPDATED_BAYES_MC:SYNTHETIC_TIMEOUT'], 1)

    def test_rehashed_future_history_receipt_is_rejected(self):
        p = deepcopy(self.h.p)
        cut = json.loads((self.h.assets/p['input_asset']['file']).read_text())
        cut['history'][0]['ingested_at_utc'] = p['prediction_generated_at_utc']+1
        p['input_asset'] = self.h.asset(cut)
        with self.assertRaisesRegex(ValueError,'AVAILABILITY_LEAKAGE'): predict_snapshot(p, self.h.assets)

    def test_insufficient_hierarchy_sample_is_explicit_not_synthetic_success(self):
        with patch('hybrid_engine.challenger_review.refresh', side_effect=Abstain('INSUFFICIENT_PAST_TRAINING')):
            result = predict_snapshot(self.h.p, self.h.assets)
        for name in NAMES[2:5]: self.assertEqual(result['components'][name]['reason'], 'INSUFFICIENT_PAST_TRAINING')
        self.assertEqual(result['components']['FAZ13_REFERENCE']['status'], 'AVAILABLE')


class ChallengerCLITests(unittest.TestCase):
    def test_missing_ledger_is_not_created(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'missing.sqlite'; assets=Path(tmp)/'assets'; assets.mkdir()
            with self.assertRaisesRegex(ValueError,'EXISTING_LEDGER'): run(path, assets)
            self.assertFalse(path.exists())

    def test_invalid_budgets_refused_before_opening(self):
        for maximum in (0,201,True):
            with self.subTest(maximum=maximum), self.assertRaises(ValueError): run('/no.sqlite','/no.assets',maximum=maximum)

    def test_missing_assets_report_blocked_without_mutating_real_synthetic_db(self):
        from tests.test_phase91 import ten_game_ledger,NOW
        with TemporaryDirectory() as tmp:
            root=Path(tmp); db=root/'nba.sqlite'; assets=root/'assets'; assets.mkdir()
            ten_game_ledger(db); before=db.read_bytes()
            with patch('time.time',return_value=NOW): result=run(db,assets)
            self.assertEqual(result['eligible'],1); self.assertEqual(result['reviewed'],0)
            self.assertEqual(result['blocked'],1); self.assertEqual(result['status'],'REVIEW_WITH_BLOCKS')
            self.assertEqual(db.read_bytes(),before); self.assertEqual(result['prematch_records_created'],0)
            self.assertFalse(result['acceptance']['superiority_proven'])

    def test_cli_refuses_report_output_into_input_directory_without_creating_it(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp); output=root/'assets'/'new'
            with patch('sys.argv',['challenger','--ledger',str(root/'nba.sqlite'),'--assets-directory',str(root/'assets'),
                '--output-directory',str(output)]), patch('hybrid_engine.challenger_review.run',side_effect=AssertionError('NO COMPUTE')):
                self.assertEqual(main(),2)
            self.assertFalse(output.exists())

    def test_actual_cli_safe_nonzero_failure_without_token_or_database_creation(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            p=subprocess.run([sys.executable,'-B','-m','hybrid_engine.challenger_review',
                '--ledger',str(root/'missing.sqlite'),'--assets-directory',str(root/'assets'),
                '--output-directory',str(root/'reports')],cwd=ROOT,capture_output=True,text=True,timeout=15)
            self.assertEqual(p.returncode,2); result=json.loads(p.stdout)
            self.assertEqual(result['status'],'BLOCKED'); self.assertNotIn('Traceback',p.stdout+p.stderr)
            self.assertFalse((root/'missing.sqlite').exists()); self.assertFalse((root/'reports').exists())

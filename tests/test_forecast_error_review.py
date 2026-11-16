"""Frozen real-input checks and manufactured errors; no invented live forecasts."""
from copy import deepcopy
import json
import hashlib
import os
import subprocess
import sys
import tarfile
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch,AsyncMock
from types import SimpleNamespace

from core.team_identity import digest
from hybrid_engine.forecast_error_review import input_profile,review,render_summary
from hybrid_engine.prediction_audit import audit_snapshot
from hybrid_engine.predictions_command import split_plain
from hybrid_engine.quality_report import report
from ledger_reports import accuracy_command
from tests import test_phase90 as frozen_tests
from tests.test_phase92 import row


class FrozenInputProfileTests(unittest.TestCase):
    def setUp(self):
        self.h=frozen_tests.FrozenPhiladelphiaAudit('runTest');self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.p=self.h.p;self.assets=self.h.assets

    def test_real_frozen_features_rebuild_and_scores_decompose_without_fitting(self):
        before=digest(self.p)
        with patch('hybrid_engine.models.HierarchicalStrength.fit',side_effect=AssertionError('NO FIT')):
            r=input_profile(self.p,self.assets)
        self.assertEqual(r['training_games'],170);self.assertEqual(r['snapshot_sha256'],before)
        self.assertEqual(digest(self.p),before);self.assertFalse(r['model_changed'])
        for side in ('home','away'):
            self.assertAlmostEqual(sum(r['score_contributions'][side].values()),self.p['prediction'][side],places=8)
            self.assertEqual(r['history'][side]['games'],10)
        self.assertAlmostEqual(r['retrospective_baseline']['total'],220.05)
        self.assertFalse(r['retrospective_baseline']['published_forecast'])
        self.assertFalse(r['retrospective_baseline']['eligible_for_live_performance'])

    def test_real_profile_discloses_fit_age_and_unmeasured_features(self):
        r=input_profile(self.p,self.assets)
        self.assertEqual(r['fit_age_seconds'],self.p['prediction_generated_at_utc']-self.p['parameter_fit_cutoff_utc'])
        self.assertFalse(r['feature_usage']['current_scoring_average_updates_full_game_mean'])
        self.assertFalse(r['feature_usage']['verified_pace']);self.assertFalse(r['feature_usage']['player_effects'])
        self.assertGreater(r['quarter_correlation'],.98);self.assertIsNone(r['confidence_index'])
        self.assertEqual(r['causal_explanation'],'NOT_IDENTIFIED_FROM_ONE_REALIZED_SCORE')

    def test_rehashed_feature_changes_cannot_bypass_history_reconstruction(self):
        raw=json.loads((self.assets/self.p['input_asset']['file']).read_text())
        raw['features']['home']['points_for']+=1;self.p['input_asset']=self.h.asset(raw)
        with self.assertRaisesRegex(ValueError,'HISTORY_FEATURE_RECONSTRUCTION'):input_profile(self.p,self.assets)

    def test_rehashed_wrong_inputs_digest_is_rejected(self):
        raw=json.loads((self.assets/self.p['input_asset']['file']).read_text())
        raw['inputs_digest']='f'*64;self.p['input_asset']=self.h.asset(raw)
        with self.assertRaisesRegex(ValueError,'HISTORY_FEATURE_RECONSTRUCTION'):input_profile(self.p,self.assets)

    def test_sources_after_prediction_still_cannot_enter_profile(self):
        raw=json.loads((self.assets/self.p['input_asset']['file']).read_text())
        raw['history'][0]['ingested_at_utc']=self.p['prediction_generated_at_utc']+1
        self.p['input_asset']=self.h.asset(raw)
        with self.assertRaisesRegex(ValueError,'AVAILABILITY_LEAKAGE'):input_profile(self.p,self.assets)

    def test_profile_is_bound_to_native_audit_and_snapshot(self):
        a=audit_snapshot(self.p,self.assets);a['snapshot_sha256']='f'*64
        with self.assertRaisesRegex(ValueError,'NATIVE_PROFILE_REQUIRED'):input_profile(self.p,self.assets,source_audit=a)

    def test_frozen_score_change_is_not_explained_away_as_a_new_model(self):
        # Supplying a matching audit reference is insufficient to change the
        # means encoded by the original coefficient artifact.
        a=audit_snapshot(self.p,self.assets);self.p['prediction']['home']+=1;a['snapshot_sha256']=digest(self.p)
        with self.assertRaisesRegex(ValueError,'FROZEN_SCORE_RECONSTRUCTION'):input_profile(self.p,self.assets,source_audit=a)

    def test_raw_variance_contains_parameter_and_residual_uncertainty(self):
        r=input_profile(self.p,self.assets)
        for side in ('home','away'):
            v=r['predictive_variance'][side]
            self.assertGreater(v['parameter_variance'],0);self.assertGreater(v['residual_variance'],0)
            self.assertAlmostEqual(v['raw_predictive_sd']**2,sum(v[k] for k in ('parameter_variance','residual_variance','unseen_team_variance')))


class ErrorReviewTests(unittest.TestCase):
    def rows(self):
        rows=[row(i) for i in range(3)]
        for r,error in zip(rows,(1.,2.,10.)):
            r['prediction']=[104+error,96.];r['home']='Synthetic Home';r['away']='Synthetic Away'
            r['provider_fixture_ids']=['401000123'];r['final_with_ot']=r['actual'][:]
        return rows

    def run_review(self,rows=None,**kw):
        rows=self.rows() if rows is None else rows
        return review(rows,asof_utc=kw.pop('asof_utc',rows[-1]['label_available_utc']),**kw)

    def test_error_shares_include_all_matches_without_deleting_outliers(self):
        r=self.run_review();g=r['groups'][0]
        self.assertEqual(g['n'],3);self.assertEqual(g['cases'][0]['signed_total_error'],10.)
        self.assertAlmostEqual(g['cases'][0]['cohort_squared_error_share'],100/105)
        self.assertAlmostEqual(sum(c['cohort_absolute_error_share'] for c in g['cases']),1)
        self.assertEqual(g['day_clusters'],3);self.assertFalse(r['automatic_tuning'])
        self.assertIsNone(r['confidence_index']);self.assertIn('güven yüzdesi değil',render_summary(r))

    def test_missing_native_assets_are_explicitly_blocked_not_invented(self):
        r=self.run_review()
        self.assertTrue(all(c['input_profile_status'].startswith('BLOCKED') for c in r['groups'][0]['cases']))
        self.assertEqual(r['groups'][0]['matched_input_baseline']['metrics']['retrospective_baseline']['n'],0)
        self.assertFalse(r['groups'][0]['matched_input_baseline']['superiority_claim'])

    def test_future_final_is_pending_at_the_requested_review_time(self):
        r=row();out=review([r],asof_utc=r['fixture_start_utc']+1)
        self.assertEqual(out['groups'][0]['n'],0);self.assertFalse(out['groups'][0]['cases'])

    def test_pending_forecast_does_not_become_a_zero_error_success(self):
        rows=self.rows();rows[0]['actual']=None
        r=self.run_review(rows);self.assertEqual(r['groups'][0]['n'],2)
        self.assertNotIn(rows[0]['fixture_id'],[c['fixture_id'] for c in r['groups'][0]['cases']])

    def test_repeated_rows_do_not_increase_sample_count(self):
        r=self.run_review(self.rows()*3);self.assertEqual(r['groups'][0]['n'],3)

    def test_later_revised_prediction_does_not_replace_first_issue(self):
        rows=self.rows();later=deepcopy(rows[0]);later['prediction']=later['actual'][:]
        later['first_archived_at_utc']+=1;later['snapshot_sha256']='f'*64
        r=self.run_review([later,*rows]);c=next(c for c in r['groups'][0]['cases'] if c['fixture_id']==rows[0]['fixture_id'])
        self.assertEqual(c['signed_total_error'],1)

    def test_conflicting_first_publications_are_excluded(self):
        rows=self.rows();other=dict(rows[0],snapshot_sha256='f'*64)
        r=self.run_review([other,*rows]);self.assertEqual(r['groups'][0]['n'],2)
        self.assertEqual(r['exclusions']['CONFLICTING_FIRST_PUBLICATION'],1)

    def test_posttipoff_first_archive_is_not_live_performance(self):
        rows=self.rows();rows[0]['first_archived_at_utc']=rows[0]['fixture_start_utc']
        self.assertEqual(self.run_review(rows)['groups'][0]['n'],2)

    def test_model_digest_and_season_cohorts_stay_separate(self):
        rows=self.rows();rows[1]['model_digest']='f'*64;rows[2]['season']='OTHER'
        r=self.run_review(rows);self.assertEqual(len(r['groups']),3)
        self.assertTrue(all(g['n']==1 for g in r['groups']))

    def test_ot_final_is_excluded_from_normal_time_error(self):
        r=row();r['prediction']=[109.2,109.73];r['actual']=[95,95]
        r['actual_periods']=dict(home=[17,26,31,21,13],away=[23,24,20,28,17]);r['final_with_ot']=[108,112]
        case=self.run_review([r])['groups'][0]['cases'][0]
        self.assertAlmostEqual(case['signed_total_error'],28.93)
        self.assertEqual(case['overtime_points_excluded'],30)

    def test_period_signed_errors_sum_to_regulation_total_error(self):
        rows=self.rows();r=rows[0];r['predicted_quarters']=[[26.25,24.]]*4
        case=next(c for c in self.run_review(rows)['groups'][0]['cases'] if c['fixture_id']==r['fixture_id'])
        self.assertAlmostEqual(sum(case['period_total_errors']),case['signed_total_error'])

    def test_profile_comparison_uses_only_the_same_verified_subset(self):
        rows=self.rows();r=rows[0]
        profile=dict(snapshot_sha256=r['snapshot_sha256'],model_digest=r['model_digest'],generated_at_utc=r['prediction_generated_at_utc'],
            history=dict(home=dict(new_games_since_fit=1),away=dict(new_games_since_fit=0)),quarter_correlation=.99,
            feature_usage=dict(verified_pace=False,player_effects=False),retrospective_baseline=dict(total=203.))
        g=self.run_review(rows,profiles=[profile])['groups'][0];b=g['matched_input_baseline']
        self.assertEqual(b['metrics']['frozen_model']['n'],1);self.assertEqual(b['metrics']['retrospective_baseline']['n'],1)
        self.assertEqual(b['metrics']['frozen_model']['mae'],1.);self.assertEqual(b['metrics']['retrospective_baseline']['mae'],3.)
        self.assertEqual(g['findings']['MEASURED_PACE_NOT_A_MODEL_INPUT'],1)
        self.assertEqual(g['findings']['NEW_HISTORY_DOES_NOT_REFIT_FROZEN_TEAM_STRENGTH'],1)

    def test_negative_ot_points_refused(self):
        rows=self.rows();rows[0]['final_with_ot']=[0,0]
        with self.assertRaisesRegex(ValueError,'NEGATIVE_OVERTIME'):self.run_review(rows)

    def test_no_mutation_of_inputs_and_no_retuning(self):
        rows=self.rows();before=deepcopy(rows);r=self.run_review(rows)
        self.assertEqual(rows,before);self.assertFalse(r['calibration_fit']);self.assertFalse(r['production_changed'])

    def test_zero_errors_do_not_divide_by_zero(self):
        rows=self.rows()
        for r in rows:r['prediction']=r['actual'][:]
        g=self.run_review(rows)['groups'][0];self.assertIsNone(g['top_three_squared_error_share'])

    def test_invalid_generation_and_snapshot_pin_excluded(self):
        for changes in (dict(prediction_generated_at_utc=True),dict(snapshot_sha256='not-sha')):
            rows=self.rows();rows[0].update(changes)
            with self.subTest(changes=changes):self.assertEqual(self.run_review(rows)['groups'][0]['n'],2)


class TelegramLineSplitTests(unittest.TestCase):
    def test_short_lines_and_tsi_are_not_split_between_messages(self):
        text=('x'*30+'\n')+'İlk kalıcı arşiv: 15.11.2026 15:34:22 TSİ\n'+'y'*30
        chunks=list(split_plain(text,limit=45))
        self.assertEqual(''.join(chunks),text)
        self.assertTrue(any('15:34:22 TSİ\n' in p for p in chunks))
        self.assertTrue(all(len(p.encode('utf-16-le'))//2<=45 for p in chunks))

    def test_long_emoji_line_roundtrips_with_crlf_and_blank_lines(self):
        text='🏀'*60+'\r\n\nMaç: NBA\n'
        chunks=list(split_plain(text,limit=21));self.assertEqual(''.join(chunks),text)
        self.assertTrue(all(len(p.encode('utf-16-le'))//2<=21 for p in chunks))

    def test_empty_input_and_invalid_limit(self):
        self.assertEqual(list(split_plain('')),[])
        with self.assertRaises(ValueError):list(split_plain('🏀',limit=1))


class NativeReportIntegrationTests(unittest.TestCase):
    def test_missing_assets_do_not_block_native_error_measurement_or_change_sqlite(self):
        from tests.test_phase91 import ten_game_ledger,NOW
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'nba.sqlite';ten_game_ledger(path);before=path.read_bytes()
            with patch('time.time',return_value=NOW):r=report(path)
            self.assertEqual(r['error_review']['groups'][0]['n'],1)
            self.assertEqual(r['error_review']['groups'][0]['cases'][0]['input_profile_status'],'BLOCKED_ORIGINAL_NATIVE_ASSETS_UNAVAILABLE')
            self.assertEqual(before,path.read_bytes());self.assertFalse(r['predictions_recomputed'])


class TelegramAccuracyIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_accuracy_command_shows_outliers_and_keeps_not_calibrated(self):
        from ledger_reports import LedgerReports
        from tests.test_phase91 import ten_game_ledger,NOW
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'nba.sqlite';ten_game_ledger(path);before=path.read_bytes();reply=AsyncMock()
            update=SimpleNamespace(effective_message=SimpleNamespace(reply_text=reply))
            context=SimpleNamespace(args=['NBA'],application=SimpleNamespace(bot_data={'ledger_reports':LedgerReports(path)}))
            with patch('time.time',return_value=NOW):await accuracy_command(update,context)
            text=''.join(c.args[0] for c in reply.call_args_list)
            self.assertIn('HATA İNCELEMESİ',text);self.assertIn('NOT_CALIBRATED',text)
            self.assertIn('Toplam hata',text);self.assertEqual(path.read_bytes(),before)


class CapturedResultEvidenceTests(unittest.TestCase):
    def payloads(self):
        path=Path(__file__).resolve().parents[1]/'docs/evidence/phase924-append-only-official-nba-finals-20261116.tar.gz'
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),'f505be5c72187f5dd1d983147feb9ca31e918a86e5185792d7daae0ce49a85d1')
        with tarfile.open(path,'r:gz') as tar:
            members=tar.getmembers();self.assertLessEqual(len(members),16)
            self.assertTrue(all(m.isfile() and Path(m.name).name==m.name and m.size<2*1024*1024 for m in members))
            return {m.name:tar.extractfile(m).read() for m in members}

    def test_ten_native_finals_and_transcript_comparison_are_pinned_and_separate(self):
        data=self.payloads();index=json.loads(next(v for k,v in data.items() if k.startswith('transcript-comparison-')))
        p=index['payload'];self.assertEqual(index['sha256'],digest(p));self.assertEqual(len(p['records']),10)
        self.assertEqual(len({r['espn_id'] for r in p['records']}),10)
        for row in p['records']:
            raw=data[row['source_file']];r=json.loads(raw)
            self.assertEqual(hashlib.sha256(raw).hexdigest(),row['file_sha256']);self.assertEqual(digest(r),row['receipt_sha256'])
            self.assertEqual(digest(r['document']),r['document_sha256'])
            h=r['document']['header'];self.assertEqual(h['id'],row['espn_id'])
            c=h['competitions'][0];self.assertTrue(c['status']['type']['completed'])
            by_side={v['homeAway']:v for v in c['competitors']}
            self.assertEqual([sum(int(v['displayValue']) for v in by_side[s]['linescores'][:4]) for s in ('home','away')],row['official_regulation'])
            self.assertFalse(row['user_reported_prediction']['independent_ledger_sha_verified'])
        tor=next(r for r in p['records'] if r['espn_id']=='401909990')
        self.assertEqual(tor['official_regulation'],[95,95]);self.assertEqual(tor['official_final_with_ot'],[108,112])
        self.assertEqual(p['descriptive_display_total_metrics']['top_three_ids'],['401909991','401909985','401909990'])

    def test_native_philadelphia_error_is_separate_from_phone_transcript(self):
        data=self.payloads();w=json.loads(next(v for k,v in data.items() if k.startswith('native-philadelphia-error-')))
        p=w['payload'];self.assertEqual(w['sha256'],digest(p));self.assertFalse(p['source_database_changed'])
        c=p['groups'][0]['cases'][0];self.assertEqual(c['snapshot_sha256'],'30e32e06461cc83123fcc99b46a79d9dbaf1be3b0f2c5ebc6448341ed25a5343')
        self.assertAlmostEqual(c['signed_total_error'],-33.21108196198506)
        self.assertEqual(c['input_profile_status'],'FROZEN_INPUTS_VERIFIED')
        self.assertAlmostEqual(c['input_profile']['retrospective_baseline']['total'],220.05)
        self.assertEqual(c['causal_explanation'],'NOT_ESTABLISHED')


class OfflineLauncherTests(unittest.TestCase):
    def test_error_review_mode_does_not_bootstrap_git_token_or_polling(self):
        root=Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as tmp:
            home=Path(tmp);checkout=home/'zeynal-hybrid-844';binary=checkout/'.venv/bin/python'
            binary.parent.mkdir(parents=True)
            binary.write_text('#!'+sys.executable+'\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n');binary.chmod(0o700)
            # HOME belongs only to the emulated child installation; the actual
            # process environment and real UserLAnd HOME are never modified.
            env=dict(os.environ,HOME=str(home))
            p=subprocess.run(['bash',str(root/'scripts/run_isolated_test_bot.sh'),'--error-review'],env=env,
                             capture_output=True,text=True,timeout=5,check=True)
            args=json.loads(p.stdout)
            self.assertEqual(args[:2],['-m','hybrid_engine.quality_report'])
            self.assertIn(str(home/'zeynal-test-isolated/data/live-nba/nba-hybrid.sqlite'),args)
            self.assertNotIn('hybrid_engine.test_bot',args);self.assertFalse((home/'.zeynal-elite-test-token').exists())
            plan=home/'zeynal-test-isolated/data/quality-phase92/calibration-plan';plan.mkdir(parents=True)
            (plan/('plan-'+'f'*64+'.json')).write_text('{}')
            again=subprocess.run(['bash',str(root/'scripts/run_isolated_test_bot.sh'),'--error-review'],env=env,
                                 capture_output=True,text=True,timeout=5,check=True)
            extra=json.loads(again.stdout);self.assertIn('--existing-calibration-plan-directory',extra)
            self.assertNotIn('--calibration-plan-directory',extra)


class ExistingCalibrationPlanTests(unittest.TestCase):
    def test_existing_plan_is_verified_without_any_write(self):
        from hybrid_engine.quality_report import read_existing_plan
        from hybrid_engine.calibration_guard import CalibrationPlan
        with TemporaryDirectory() as tmp:
            root=Path(tmp);plan=CalibrationPlan.register();file=root/('plan-'+plan.sha256+'.json')
            file.write_text(json.dumps(dict(payload=plan.payload,sha256=plan.sha256)));before=file.read_bytes()
            self.assertEqual(read_existing_plan(root).sha256,plan.sha256);self.assertEqual(before,file.read_bytes())

    def test_missing_plan_is_not_silently_created_or_backdated(self):
        from hybrid_engine.quality_report import read_existing_plan
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'missing'
            with self.assertRaisesRegex(ValueError,'EXISTING_CALIBRATION'):read_existing_plan(path)
            self.assertFalse(path.exists())

    def test_symlink_or_conflicting_plans_are_not_accepted(self):
        from hybrid_engine.quality_report import read_existing_plan
        with TemporaryDirectory() as tmp:
            root=Path(tmp);target=root/'target';target.mkdir();link=root/'link';link.symlink_to(target,target_is_directory=True)
            with self.assertRaises(ValueError):read_existing_plan(link)
            for pin in ('a','b'):(target/('plan-'+pin*64+'.json')).write_text('{}')
            with self.assertRaisesRegex(ValueError,'EXACTLY_ONE'):read_existing_plan(target)


if __name__=='__main__':unittest.main()

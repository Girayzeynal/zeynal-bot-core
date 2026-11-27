"""Synthetic decision boundaries + frozen real evidence; not real Telegram E2E."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase, IsolatedAsyncioTestCase
from unittest.mock import Mock, AsyncMock, patch

import numpy as np
from telegram.ext import ApplicationHandlerStop

from core.team_identity import digest
from hybrid_engine.data import feature_cut, ASSUMED
from hybrid_engine.health_card import build, render
from hybrid_engine.health_command import HealthCommand
from hybrid_engine.quality_monitor import monitor, render_monitor
from hybrid_engine.research_candidates import feature_readiness, run_candidates
from hybrid_engine.calibration_review import review
from hybrid_engine.calibration_guard import CalibrationPlan
from hybrid_engine.telegram_premium_ui import compact_summary
from tests.test_hybrid_models import synthetic_cohort

ROOT = Path(__file__).resolve().parents[1]


def row(i=0):
    tip = 1735689600+i*86400
    return dict(fixture_id=str(i), league='NBA', season='SYNTHETIC', model_version='TEST_ONLY',
        model_digest='a'*64, snapshot_sha256=f'{i:064x}', prediction=[100., 96.], actual=[104, 96],
        actual_periods=dict(home=[26]*4, away=[24]*4), winner=[.6, .02, .38],
        fixture_start_utc=tip, prediction_generated_at_utc=tip-3600, created_utc=tip-3599,
        first_archived_at_utc=tip-3598, label_available_utc=tip+10800)


def snapshot():
    p = json.loads(next((ROOT/'docs/prospective/handoff-20261115').glob('nba-30e*.json')).read_text())['payload']
    audit = dict(status='VERIFIED_WITH_LIMITATIONS', snapshot_sha256=digest(p), model_version=p['model_version'],
        verified_fixture_sources=[c['source_url'] for c in p['input_clocks'] if 'dates=20261115' in c['source_url']],
        measured_possession_pace_used=False, verified_rotation_or_player_impact_used=False,
        mean_off_diagonal_quarter_correlation=.988)
    return p, audit


class QualityPointInTimeTests(TestCase):
    def test_pending_games_do_not_count_as_accuracy_or_stability(self):
        r=row();r['actual']=None
        g=monitor([r],asof_utc=r['first_archived_at_utc'])['groups'][0]
        self.assertEqual((g['forecasts'],g['settled'],g['pending']),(1,0,1))
        self.assertEqual(g['drift']['status'],'INSUFFICIENT_DATA')
        self.assertNotIn('winner',g['metrics']);self.assertIsNone(g['confidence_index'])

    def test_today_result_cannot_leak_into_yesterday_health(self):
        r=row();report=monitor([r],asof_utc=r['fixture_start_utc']-1)
        self.assertEqual(report['groups'][0]['settled'],0)
        self.assertEqual(monitor([r],asof_utc=r['label_available_utc'])['groups'][0]['settled'],1)

    def test_unpublished_future_snapshot_excluded(self):
        r=row();self.assertFalse(monitor([r],asof_utc=r['first_archived_at_utc']-1)['groups'])

    def test_late_first_archive_is_not_retrospective_prematch_proof(self):
        r=row();r['first_archived_at_utc']=r['fixture_start_utc']
        report=monitor([r],asof_utc=r['label_available_utc'])
        self.assertFalse(report['groups']);self.assertIn('INVALID_PREMATCH_ORDER',report['exclusions'])

    def test_missing_generation_not_inferred_from_snapshot(self):
        r=row();r.pop('prediction_generated_at_utc')
        self.assertFalse(monitor([r],asof_utc=r['label_available_utc'])['groups'])

    def test_bool_or_float_clock_is_not_a_utc_integer(self):
        for value in (True,1735689599.,-1):
            r=row();r['created_utc']=value
            with self.subTest(value=value):self.assertFalse(monitor([r],asof_utc=r['label_available_utc'])['groups'])

    def test_first_issued_snapshot_not_latest_revision_is_measured(self):
        r=row();later=deepcopy(r);later['prediction']=[104.,96.];later['snapshot_sha256']='b'*64
        later['first_archived_at_utc']+=1
        g=monitor([later,r],asof_utc=r['label_available_utc'])['groups'][0]
        self.assertEqual(g['settled'],1);self.assertEqual(g['metrics']['total']['mae'],4.)

    def test_same_time_conflicting_publications_excluded_without_deletion(self):
        r=row();other=dict(r,snapshot_sha256='b'*64)
        report=monitor([r,other],asof_utc=r['label_available_utc'])
        self.assertFalse(report['groups']);self.assertIn('CONFLICTING_FIRST_PUBLICATION',report['exclusions'])

    def test_identical_repeat_cannot_inflate_sample_count(self):
        r=row();self.assertEqual(monitor([r,r,r],asof_utc=r['label_available_utc'])['groups'][0]['settled'],1)

    def test_fit_sha_season_league_version_are_not_pooled(self):
        original=row();values=[original]
        for key in ('league','season','model_version','model_digest'):
            values.append(dict(original,**{key:'OTHER'}))
        report=monitor(values,asof_utc=original['label_available_utc'])
        self.assertEqual(len(report['groups']),5)
        self.assertTrue(all(g['settled']==1 for g in report['groups']))

    def test_invalid_label_availability_downgrades_to_pending(self):
        r=row();r['label_available_utc']=r['fixture_start_utc']
        report=monitor([r],asof_utc=r['fixture_start_utc']+1)
        self.assertEqual(report['groups'][0]['pending'],1)
        self.assertIn('INVALID_RESULT_AVAILABILITY',report['exclusions'])

    def test_missing_model_digest_never_mixed_into_known_model(self):
        r=row();r.pop('model_digest')
        self.assertFalse(monitor([r],asof_utc=r['label_available_utc'])['groups'])

    def test_descriptive_metrics_are_correct_and_do_not_fit(self):
        r=row();out=monitor([r],asof_utc=r['label_available_utc'])
        m=out['groups'][0]['metrics']
        self.assertEqual(m['team_scores']['mae'],2.)
        self.assertAlmostEqual(m['winner']['brier'],.4**2+.02**2+.38**2)
        self.assertFalse(out['calibration_fit']);self.assertFalse(out['automatic_promotion'])

    def test_drift_only_uses_labels_available_before_recent_predictions(self):
        rows=[row(i) for i in range(200)]
        for r in rows[100:]:r['winner']=[.05,.02,.93]
        report=monitor(rows,asof_utc=rows[-1]['label_available_utc'])
        d=report['groups'][0]['drift']
        self.assertEqual(d['status'],'HEURISTIC_REVIEW_ONLY')
        self.assertLess(d['reference_available_max_utc'],d['current_prediction_min_utc'])
        self.assertIn('BRIER_DEGRADATION_REVIEW',d['alerts'])
        self.assertFalse(d['statistically_confirmed_change'])

    def test_future_known_reference_labels_cannot_support_drift(self):
        rows=[row(i) for i in range(200)]
        for r in rows[:100]:r['label_available_utc']=rows[110]['fixture_start_utc']
        d=monitor(rows,asof_utc=rows[-1]['label_available_utc'])['groups'][0]['drift']
        self.assertEqual(d['status'],'INSUFFICIENT_DISJOINT_PRIOR_LABELS_OR_DAY_CLUSTERS')

    def test_clustered_games_cannot_fake_eight_days(self):
        rows=[row(i) for i in range(200)]
        for i,r in enumerate(rows):
            shifted=row(i//100);r.update({k:v for k,v in shifted.items() if k.endswith('_utc')})
        d=monitor(rows,asof_utc=rows[-1]['label_available_utc'])['groups'][0]['drift']
        self.assertEqual(d['status'],'INSUFFICIENT_DISJOINT_PRIOR_LABELS_OR_DAY_CLUSTERS')

    def test_monitor_does_not_mutate_rows(self):
        rows=[row()];before=deepcopy(rows);monitor(rows,asof_utc=rows[0]['label_available_utc'])
        self.assertEqual(rows,before)

    def test_bounded_input_and_report(self):
        with self.assertRaisesRegex(ValueError,'BUDGET'):monitor([row()]*1001,asof_utc=1800000000)
        out=monitor([dict(row(i),model_digest=f'{i+1:064x}') for i in range(12)],asof_utc=1800000000)
        self.assertIn('İlk 10',render_monitor(out))


class ForecastHealthTests(TestCase):
    def test_unmodified_real_snapshot_has_limited_not_high_confidence_status(self):
        p,a=snapshot();before=digest(p);r=build(p,a)
        self.assertEqual(r['status'],'LIMITED_RESEARCH');self.assertTrue(r['publication_allowed'])
        self.assertIsNone(r['confidence_index']);self.assertEqual(digest(p),before)
        self.assertIn('QUARTER_UNCERTAINTY_ALLOCATION_LIMITATION',r['reasons'])
        self.assertIn('NOT_CALIBRATED',render(r))

    def test_forged_audit_for_another_snapshot_blocks_display(self):
        p,a=snapshot();p['prediction']['total']+=1
        self.assertEqual(build(p,a)['status'],'ABSTAIN')

    def test_no_native_source_audit_no_publication(self):
        p,_=snapshot();self.assertFalse(build(p,None)['publication_allowed'])

    def test_fresh_history_cannot_hide_stale_target_fixture(self):
        p,a=snapshot()
        for c in p['input_clocks']:
            if c['source_url'] in a['verified_fixture_sources']:c['ingested_at_utc']=p['prediction_generated_at_utc']-301
        a['snapshot_sha256']=digest(p)
        self.assertIn('STALE_PREMATCH_FIXTURE_SOURCE',build(p,a)['blockers'])

    def test_future_target_receipt_is_not_fresh_prematch_evidence(self):
        p,a=snapshot()
        for c in p['input_clocks']:
            if c['source_url'] in a['verified_fixture_sources']:c['ingested_at_utc']=p['prediction_generated_at_utc']+1
        a['snapshot_sha256']=digest(p)
        self.assertFalse(build(p,a)['publication_allowed'])

    def test_replay_age_is_measured_at_original_generation_not_today(self):
        p,a=snapshot();r=build(p,a)
        self.assertLessEqual(r['fixture_source_age_at_generation_seconds'],300)
        self.assertNotIn('STALE_PREMATCH_FIXTURE_SOURCE',r['blockers'])

    def test_post_tipoff_generation_is_blocked(self):
        p,a=snapshot();p['prediction_generated_at_utc']=p['fixture_start_utc'];a['snapshot_sha256']=digest(p)
        self.assertIn('INVALID_PREMATCH_SOURCE_CLOCKS',build(p,a)['blockers'])

    def test_response_time_performance_cannot_masquerade_as_prior_quality(self):
        p,a=snapshot();out=build(p,a,prior_quality=monitor([],asof_utc=p['prediction_generated_at_utc']+1))
        self.assertIn('PRIOR_QUALITY_POINT_IN_TIME_MISMATCH',out['blockers'])

    def test_no_other_fit_or_league_performance_on_health_card(self):
        p,a=snapshot();r=row();r['model_digest']='other'
        out=build(p,a,prior_quality=monitor([r],asof_utc=p['prediction_generated_at_utc']))
        self.assertIsNone(out['prior_validated_results']);self.assertIsNone(out['prior_metrics'])

    def test_exact_model_prior_drift_blocks_new_display(self):
        p,a=snapshot();g={k:p[k] for k in ('league','season','model_version','model_digest')}
        g.update(settled=200,metrics={},drift=dict(alerts=['BRIER_DEGRADATION_REVIEW']))
        out=build(p,a,prior_quality=dict(asof_utc=p['prediction_generated_at_utc'],groups=[g]))
        self.assertIn('PRIOR_MODEL_DRIFT_REVIEW_REQUIRED',out['blockers'])

    def test_telegram_summary_keeps_original_scores_and_fits_limit(self):
        p,a=snapshot();out=compact_summary(p,[],replayed=True,health=build(p,a))
        self.assertIn('112.5',out);self.assertIn('109.3',out);self.assertIn('221.8',out)
        self.assertNotIn('TAHMİN SAĞLIK KARTI',out)
        self.assertIn('TAHMİN SAĞLIK KARTI',render(build(p,a)))
        self.assertIn('NOT_CALIBRATED',out);self.assertLess(len(out.encode('utf-16-le'))//2,4096)

    def test_missing_feature_names_are_html_escaped(self):
        p,a=snapshot();p['missing_data']=['<bad>'];a['snapshot_sha256']=digest(p)
        self.assertIn('&lt;bad&gt;',render(build(p,a)))


class CalibrationBridgeTests(TestCase):
    def setUp(self):
        r=row();self.r=r
        self.evidence=dict(fixture_id=r['fixture_id'],model_digest=r['model_digest'],findings=[],
            source_audit=dict(status='VERIFIED_WITH_LIMITATIONS',snapshot_sha256=r['snapshot_sha256']),
            calibration_inputs=dict(inputs_available_max_utc=r['prediction_generated_at_utc']-1,
                model_fit_cutoff_utc=r['prediction_generated_at_utc']-1000,model_training_ids=['past-only']))
        self.audit=dict(rows=[self.evidence],performance=dict(forecasts=[r]),observed_at_utc=r['label_available_utc'])

    def test_no_plan_means_no_calibration(self):
        out=review(self.audit)
        self.assertEqual(out['groups'][0]['status'],'BLOCKED_NO_REGISTERED_FORWARD_CALIBRATION_PLAN')
        self.assertFalse(out['calibration_applied_to_forecasts'])
        self.assertEqual(out['groups'][0]['observed_raw_metrics']['n'],1)
        self.assertAlmostEqual(out['groups'][0]['observed_raw_metrics']['brier'],.3048)
        self.assertEqual(out['groups'][0]['observed_raw_metrics_scope'],'DESCRIPTIVE_ONLY_NOT_CALIBRATION')
        self.assertIsNone(out['confidence_index'])

    def test_new_plan_does_not_turn_old_observation_into_forward_test(self):
        out=review(self.audit,plan=CalibrationPlan.register())
        group=out['groups'][0]['shadow']['groups'][0]
        self.assertEqual(group['post_plan_target_count'],0)
        self.assertEqual(group['evaluated_count'],0)
        self.assertFalse(group['eligible_for_explicit_user_review'])

    def test_unverified_source_cannot_enter_calibration(self):
        self.evidence['source_audit']['status']='UNVERIFIED'
        self.assertFalse(review(self.audit)['groups'])

    def test_unavailable_result_or_late_archive_never_enters_calibration(self):
        for field,value in [('actual',None),('first_archived_at_utc',self.r['fixture_start_utc']),
                            ('label_available_utc',self.audit['observed_at_utc']+1)]:
            a=deepcopy(self.audit);a['performance']['forecasts'][0][field]=value
            with self.subTest(field=field):self.assertFalse(review(a)['groups'])

    def test_target_training_label_fails_sealed_guard(self):
        self.evidence['calibration_inputs']['model_training_ids']=[self.r['fixture_id']]
        with self.assertRaisesRegex(ValueError,'STRICT_PREMATCH_OOS'):
            review(self.audit,plan=CalibrationPlan.register())

    def test_fitted_models_stay_separate_before_coarser_legacy_guard(self):
        r=deepcopy(self.r);r['model_digest']='b'*64
        e=deepcopy(self.evidence);e['model_digest']=r['model_digest']
        self.audit['rows'].append(e);self.audit['performance']['forecasts'].append(r)
        out=review(self.audit,plan=CalibrationPlan.register())
        self.assertEqual(len(out['groups']),2)
        self.assertTrue(all(g['raw_records']==1 for g in out['groups']))


class ResearchCandidateGateTests(TestCase):
    def setUp(self):
        self.c=synthetic_cohort(25)
        for versions in self.c:
            r=versions[0];r['box']['source']['document_sha256']='a'*64
            for side in ('home','away'):
                remainder=r['box']['teams'][side]['points']-sum(r['periods'][side])
                r['periods'][side][-1]+=remainder
        self.cut=feature_cut(self.c,self.c[24][0])

    def test_box_estimates_not_renamed_measured_pace(self):
        r=feature_readiness(self.cut)
        self.assertEqual(r['possession_readiness'],'ELIGIBLE_FOR_OFFLINE_COMPARISON')
        self.assertAlmostEqual(r['sides']['home']['estimated_possessions_per_regulation_game'],87.56)
        self.assertIn('ESTIMATE_NOT_MEASURED_PBP',r['pace_definition'])
        self.assertFalse(r['production_enabled'])

    def test_points_only_history_abstains_without_inventing_possessions(self):
        f=deepcopy(self.cut.features)
        for side in ('home','away'):f[side]['boxes']=[]
        r=run_candidates(replace(self.cut,features=f))
        self.assertEqual(r['candidates']['POSSESSION']['status'],'ABSTAIN')

    def test_future_box_source_rejected(self):
        cut=deepcopy(self.cut);cut.features['home']['boxes'][0][1]['source']['ingested_at_utc']=cut.cutoff_utc+1
        with self.assertRaisesRegex(ValueError,'FUTURE_OR_OVERTIME'):feature_readiness(cut)

    def test_overtime_box_never_trains_regulation_candidate(self):
        cut=deepcopy(self.cut);cut.features['home']['boxes'][0][1]['regulation_eligible']=False
        with self.assertRaisesRegex(ValueError,'FUTURE_OR_OVERTIME'):feature_readiness(cut)

    def test_wrong_box_points_or_team_mapping_rejected(self):
        cut=deepcopy(self.cut);cut.features['home']['boxes'][0][1]['teams']['home']['points']+=1
        with self.assertRaises(ValueError):feature_readiness(cut)

    def test_stored_possession_estimate_must_match_native_counts(self):
        cut=deepcopy(self.cut);cut.features['home']['boxes'][0][1]['teams']['home']['possessions_estimate']+=10
        with self.assertRaisesRegex(ValueError,'ESTIMATE_CONFLICT'):feature_readiness(cut)

    def test_regulation_periods_must_match_verified_final(self):
        cut=deepcopy(self.cut);cut.features['home']['boxes'][0][0]['periods']['home'][0]+=1
        with self.assertRaisesRegex(ValueError,'PERIOD_TOTAL_CONFLICT'):feature_readiness(cut)

    def test_mc_and_analytic_wrappers_are_reproducible_and_honest_about_sampled_bands(self):
        first=run_candidates(self.cut);second=run_candidates(self.cut)
        a=first['candidates']['POSSESSION_ANALYTIC'];m=first['candidates']['POSSESSION_MC']
        self.assertEqual(a['status'],'RESEARCH_OUTPUT_NOT_VALIDATED')
        self.assertEqual(a['scenarios'],0);self.assertEqual(a['intervals']['status'],'UNSUPPORTED')
        self.assertEqual(m['scenarios'],10000)
        self.assertEqual(m['intervals']['sample_sha256'],second['candidates']['POSSESSION_MC']['intervals']['sample_sha256'])
        self.assertIsNone(m['intervals']['verified_coverage']);self.assertFalse(first['forecast_replaced'])

    def test_no_guessed_availability_allowed(self):
        with self.assertRaisesRegex(ValueError,'STRICT_PREMATCH'):feature_readiness(replace(self.cut,evaluation_class=ASSUMED))

    def test_target_result_cannot_be_in_training_history(self):
        r=deepcopy(self.cut.history[0]);r['fixture_id']=self.cut.target['fixture_id']
        with self.assertRaisesRegex(ValueError,'LEAKAGE'):feature_readiness(replace(self.cut,history=(r,)+self.cut.history))

    def test_duplicate_box_not_an_extra_game(self):
        cut=deepcopy(self.cut);cut.features['home']['boxes'].append(cut.features['home']['boxes'][0])
        with self.assertRaisesRegex(ValueError,'IDENTITY'):feature_readiness(cut)

    def test_source_pin_required_even_with_complete_numeric_box(self):
        cut=deepcopy(self.cut);cut.features['home']['boxes'][0][1]['source'].pop('document_sha256')
        with self.assertRaisesRegex(ValueError,'PIN_REQUIRED'):feature_readiness(cut)

    def test_existing_possession_samplers_are_used_instead_of_reimplemented(self):
        with patch('hybrid_engine.research_candidates.PossessionModel') as cls:
            cls.return_value.predict.side_effect=__import__('hybrid_engine.data',fromlist=['Abstain']).Abstain('RUNTIME_BUDGET_EXCEEDED')
            r=run_candidates(self.cut)
        self.assertEqual(cls.return_value.predict.call_count,2)
        self.assertTrue(all(v['status']=='ABSTAIN' for v in r['candidates'].values()))
        self.assertFalse(r['forecast_replaced'])


class HealthCommandTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.events=[]
        self.journal=Mock();self.journal.append=lambda key,event:self.events.append(event)
        self.reports=Mock();self.reports.read.return_value=dict(status='VERIFIED_LIVE_REPORT',forecasts=[row()])
        self.update=SimpleNamespace(update_id=12,effective_chat=SimpleNamespace(id=17),effective_message=SimpleNamespace(reply_text=AsyncMock()))
        self.context=SimpleNamespace(args=['NBA'])
        self.command=HealthCommand(self.reports,self.journal,17)

    async def invoke(self):
        with self.assertRaises(ApplicationHandlerStop):await self.command.handle(self.update,self.context)

    async def test_health_read_only_command_delivers_not_calibrated(self):
        await self.invoke();self.reports.read.assert_called_once_with('NBA')
        text=''.join(call.args[0] for call in self.update.effective_message.reply_text.call_args_list)
        self.assertIn('NOT_CALIBRATED',text);self.assertIn('HEALTH_READ_OK',[e['kind'] for e in self.events])

    async def test_health_query_failure_is_visible_and_does_not_leak_error(self):
        self.reports.read.side_effect=RuntimeError('TOKEN_MUST_NEVER_APPEAR')
        await self.invoke();text=self.update.effective_message.reply_text.call_args.args[0]
        self.assertIn('HEALTH_READ_FAILED',text);self.assertNotIn('TOKEN_MUST',text)

    async def test_wrong_chat_never_opens_archive(self):
        self.update.effective_chat.id=99;await self.invoke()
        self.reports.read.assert_not_called();self.update.effective_message.reply_text.assert_not_called()

    async def test_missing_archive_cannot_be_presented_as_healthy(self):
        self.command.reports=None;await self.invoke()
        self.assertIn('yapılandırılmadı',self.update.effective_message.reply_text.call_args.args[0])

    async def test_usage_error_never_queries_archive(self):
        self.context.args=['NBA','unexpected'];await self.invoke();self.reports.read.assert_not_called()

    async def test_unknown_native_schema_fails_closed(self):
        self.reports.read.return_value=dict(status='NO_VERIFIED_LIVE_SCHEMA',forecasts=[])
        await self.invoke();self.assertIn('HEALTH_READ_FAILED',self.update.effective_message.reply_text.call_args.args[0])

    async def test_registered_health_and_predictions_dispatch_use_same_read_only_archive(self):
        from tests.test_phase91 import DispatchTests
        harness=DispatchTests('runTest')
        sent,events,groups=await harness.exercise(['/predictions NBA','/health NBA'])
        self.assertIn(-50,groups)
        self.assertTrue(any('KAYITLI NBA TAHMİNLERİ' in text and 'Maç: 10' in text for text in sent))
        self.assertTrue(any('TAHMİN SAĞLIĞI | SALT OKUNUR' in text for text in sent))
        self.assertIn('HEALTH_READ_OK',[e['kind'] for e in events])

    async def test_timeout_is_an_explicit_health_error(self):
        self.command.read_timeout=.001
        import time
        self.reports.read.side_effect=lambda *args:(time.sleep(.03) or {})
        await self.invoke()
        self.assertIn('HEALTH_READ_TIMEOUT',self.update.effective_message.reply_text.call_args.args[0])

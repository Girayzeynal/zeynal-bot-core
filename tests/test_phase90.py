"""Frozen real-source audit plus manufactured counterexamples; no actual Telegram claim."""
from copy import deepcopy
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import tarfile
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch,Mock

import numpy as np

from core.team_identity import digest
from hybrid_engine.prediction_audit import audit_snapshot,render_source_annotation
from hybrid_engine.boxes import publish_json
from hybrid_engine.live_metrics import metrics
from hybrid_engine.observed_markets import observe_espn,evaluate_observation
from hybrid_engine.distributions import gaussian_forecast,Budget
from hybrid_engine.nba_ledger_settlement import settle
from live_analysis_ledger import LiveAnalysisLedger
from season_archive_inventory import archive_catalog
import tests.test_handoff_hardening as hardening
receipt=hardening.receipt
from tests.test_observed_markets import receipt as market_receipt
from tests.test_release_integration import live_payload
from tests.test_season_archive_audit import nba,NOW

ROOT=Path(__file__).resolve().parents[1]


class FrozenPhiladelphiaAudit(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.assets=Path(self.tmp.name)
        self.packet=ROOT/'docs/evidence/handoff-nba-prospective-20261115.tar.gz'
        self.original=json.loads(next((ROOT/'docs/prospective/handoff-20261115').glob('nba-*')).read_text())
        self.p=deepcopy(self.original['payload'])
        with tarfile.open(self.packet,'r:gz') as tar:
            for member in tar:
                if member.isfile() and member.name.startswith('live-nba/assets/'):
                    if member.size>4*1024*1024:raise AssertionError('bounded real fixture')
                    (self.assets/Path(member.name).name).write_bytes(tar.extractfile(member).read())

    def asset(self,payload):
        ref=dict(file='synthetic-'+digest(payload)+'.json',sha256=digest(payload))
        (self.assets/ref['file']).write_text(json.dumps(payload));return ref

    def test_correct_native_source_is_annotated_without_changing_original_prediction(self):
        before=digest(self.p);r=audit_snapshot(self.p,self.assets)
        self.assertTrue(r['source_annotation_required']);self.assertIn('dates=20261114',r['original_recorded_fixture_source'])
        self.assertTrue(all('dates=20261115' in u for u in r['verified_fixture_sources']))
        self.assertIn('eski alan değiştirilmedi',render_source_annotation(r))
        self.assertEqual(digest(self.p),before);self.assertEqual(before,self.original['sha256'])

    def test_frozen_mc_and_qmc_paths_reproduce_with_no_fit_or_download(self):
        before=hashlib.sha256(self.packet.read_bytes()).hexdigest()
        with patch('hybrid_engine.models.HierarchicalStrength.fit',side_effect=AssertionError('fit')),patch('requests.get',side_effect=AssertionError('download')):
            r=audit_snapshot(self.p,self.assets,replay=True)
        self.assertEqual(r['simulation']['status'],'EXACT_FROZEN_PATHS_REPRODUCED')
        self.assertEqual(r['simulation']['scenarios'],10000);self.assertFalse(r['simulation']['new_prediction_created'])
        self.assertTrue(r['simulation']['quantiles_are_not_additive'])
        self.assertGreater(r['mean_off_diagonal_quarter_correlation'],.98)
        self.assertIsNone(r['confidence_index']);self.assertEqual(hashlib.sha256(self.packet.read_bytes()).hexdigest(),before)
        self.assertGreater(r['bayesian_math']['predictive_covariance'][0][0],r['bayesian_math']['projected_parameter_covariance'][0][0])

    def test_source_receipt_after_prediction_cannot_be_backfilled_into_audit(self):
        ref=self.p['source_assets'][0];r=json.loads((self.assets/ref['file']).read_text())
        r['ingested_at_utc']=self.p['prediction_generated_at_utc']+1;self.p['source_assets'][0]=self.asset(r)
        with self.assertRaisesRegex(ValueError,'SOURCE_TIME_OR_PIN'):audit_snapshot(self.p,self.assets)

    def test_historical_label_observed_after_feature_cutoff_is_refused(self):
        r=json.loads((self.assets/self.p['input_asset']['file']).read_text());r['history'][0]['ingested_at_utc']=r['cutoff_utc']+1
        self.p['input_asset']=self.asset(r)
        with self.assertRaisesRegex(ValueError,'AVAILABILITY_LEAKAGE'):audit_snapshot(self.p,self.assets)

    def test_audit_cannot_substitute_current_or_wrong_native_fixture(self):
        refs=[]
        for ref in self.p['source_assets']:
            r=json.loads((self.assets/ref['file']).read_text())
            if 'dates=20261115' not in r.get('source_url',''):refs.append(ref)
        self.p['source_assets']=refs
        with self.assertRaisesRegex(ValueError,'TARGET_NATIVE_SOURCE_REQUIRED'):audit_snapshot(self.p,self.assets)

    def test_raw_half_score_mismatch_is_not_tolerated_as_display_rounding(self):
        self.p['prediction']['halves'][0][0]+=.01
        with self.assertRaisesRegex(ValueError,'ARITHMETIC_CONFLICT'):audit_snapshot(self.p,self.assets)

    def test_invalid_probabilities_counts_and_quantiles_fail_closed(self):
        original=deepcopy(self.p)
        for kind in ('probability','count','handicap','model'):
            self.p=deepcopy(original)
            if kind=='probability':self.p['prediction']['winner']=[.5,.5,.000001]
            elif kind=='count':self.p['intervals']['scenarios']=9999
            elif kind=='handicap':self.p['intervals']['markets']['HOME_HANDICAP']['p50']+=1
            else:self.p['model_digest']='0'*64
            with self.subTest(kind=kind),self.assertRaises(ValueError):audit_snapshot(self.p,self.assets)

    def test_tampered_sample_sha_fails_exact_replay(self):
        self.p['intervals']['sample_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'SAMPLE_MISMATCH'):audit_snapshot(self.p,self.assets,replay=True)


class CalibrationMeasurements(TestCase):
    def row(self):return hardening.LiveMetricTests().row()

    def test_total_period_error_is_not_silently_replaced_by_team_period_mae(self):
        r=metrics([self.row()])
        self.assertEqual(r['periods']['1Q']['mae'],1)
        self.assertEqual(r['period_totals']['1Q']['mae'],0)
        self.assertEqual(r['half_totals']['1H']['mae'],0)

    def test_all_three_reliability_classes_include_empty_bins_and_intervals(self):
        r=metrics([self.row()]);curves=r['winner']['reliability']
        self.assertEqual(set(curves),{'home','regulation_tie','away'})
        for bins in curves.values():self.assertEqual(sum(x['n'] for x in bins),1)
        self.assertEqual(curves['regulation_tie'][2]['observed_frequency'],1)
        self.assertIsNotNone(curves['regulation_tie'][2]['wilson_95'])
        self.assertEqual(r['winner']['class_order'],['HOME','REGULATION_TIE','AWAY'])
        self.assertFalse(r['calibration_fit']);self.assertIsNone(r['confidence_index'])

    def test_interval_score_penalizes_a_missed_narrow_band(self):
        row=self.row();q=dict(zip(('p05','p10','p25','p50','p75','p90','p95'),(195,198,199,200,201,202,205)))
        row['intervals']=dict(scope='REGULATION_ONLY',status='RAW_MODEL_QUANTILES_NOT_CALIBRATED',scenarios=10000,markets={'TOTAL':q})
        r=metrics([row]);self.assertEqual(r['interval_scores']['TOTAL']['P25_P75']['mean_interval_score'],2)
        row['actual']=[110,100];row['actual_periods']['home']=[25,25,30,30]
        r=metrics([row]);self.assertEqual(r['interval_scores']['TOTAL']['P25_P75']['mean_interval_score'],38)
        self.assertEqual(r['interval_scores']['TOTAL']['P05_P95']['mean_interval_score'],110)

    def test_half_mismatch_actual_period_conflict_and_probability_drift_fail_closed(self):
        cases=[dict(predicted_halves=[[50,50],[50,50]]),dict(winner=[.4,.2,.400001]),dict(actual_periods={'home':[25]*3,'away':[25]*4})]
        for changes in cases:
            with self.subTest(changes=changes),self.assertRaises(ValueError):metrics([dict(self.row(),**changes)])

    def test_fitted_model_versions_cannot_be_pooled_for_calibration(self):
        a=dict(self.row(),model_digest='a',model_version='V1');b=dict(self.row(),model_digest='b',model_version='V1')
        with self.assertRaisesRegex(ValueError,'SEPARATE_FITTED_MODEL_COHORTS'):metrics([a,b])

    def test_source_labels_before_tipoff_and_late_predictions_are_excluded(self):
        row=self.row()
        for changes in ({'label_available_utc':row['fixture_start_utc']},{'prediction_generated_at_utc':row['fixture_start_utc']}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):metrics([dict(row,**changes)])


class MathematicsAndMarkets(TestCase):
    def test_mc_and_qmc_match_independent_analytic_law_in_a_known_limiting_case(self):
        weights=np.ones((4,2));a=gaussian_forecast([110,100],[10,12],weights,method='ANALYTIC')
        for method,tolerance in [('RQMC_HALTON',.008),('MC',.025)]:
            f=gaussian_forecast([110,100],[10,12],weights,method=method,budget=Budget(seed=20261112))
            self.assertTrue(np.allclose(f.probabilities(),a.probabilities(),atol=tolerance,rtol=0))
            self.assertTrue(np.allclose([f.market('TOTAL',210.5)[k] for k in ('under','push','over')],
                [a.market('TOTAL',210.5)[k] for k in ('under','push','over')],atol=tolerance,rtol=0))
            self.assertTrue(np.all(f.samples>=0));self.assertTrue(np.issubdtype(f.samples.dtype,np.integer))

    def test_correlated_model_is_not_compared_to_an_independent_analytic_truth(self):
        from hybrid_engine.data import Abstain
        with self.assertRaises(Abstain):gaussian_forecast([110,100],[10,12],np.ones((4,2)),method='ANALYTIC',correlation=.1)

    def test_handicap_direction_uses_cover_labels_and_never_claims_actionable_edge(self):
        with patch('time.time',return_value=NOW):
            quote=next(q for q in observe_espn(market_receipt(),now_utc=NOW)['quotes'] if q['payload']['market']=='HOME_HANDICAP')
        for means,expected in [([130,90],'HOME_COVER'),([90,130],'AWAY_COVER')]:
            f=gaussian_forecast(means,[10,10],np.ones((4,2)),method='ANALYTIC')
            r=evaluate_observation(quote,f,trusted_sha256=quote['sha256'],model_digest='synthetic',prediction_utc=NOW)
            self.assertEqual(r['conditional_direction'],expected);self.assertEqual(r['status'],'ABSTAIN')
            self.assertIsNone(r['recommended_direction']);self.assertIsNone(r['comparable_model_market_edge'])


class MultiSeasonSettlement(TestCase):
    def test_old_season_forecasts_do_not_starve_current_season_finals(self):
        events=[]
        for year,pid in [(2025,'401000122'),(2026,'401000123')]:
            e=nba(pid);e['season']['year']=year+1;e['date']=f'{year}-10-25T23:00:00Z';events.append(e)
        with TemporaryDirectory() as tmp,patch('time.time',return_value=NOW):
            ledger=LiveAnalysisLedger(Path(tmp)/'nba.sqlite')
            for year,e in zip((2025,2026),events):
                c=archive_catalog({'events':[e]},provider='ESPN',season_start_year=year,observed_at_utc=NOW-1,ingested_at_utc=NOW)
                g=c['payload']['fixtures'][0];start=g['start_ts_utc'];p=live_payload(start)
                p.update(season=f'{year}/{year+1}',fixture_id=g['canonical_id'],model_digest=str(year)*16,
                    prediction_generated_at_utc=start-101,scope='REGULATION_ONLY',provider_fixture_ids=g['provider_fixture_ids'],
                    input_clocks=[dict(observed_at_utc=start-103,ingested_at_utc=start-102)])
                with patch('time.time',return_value=start-100):ledger.commit(p)
            r=settle(ledger,fetcher=lambda provider,url:receipt({'events':events},url))
            self.assertEqual(r['settled'],2);self.assertEqual(r['pending'],0)
            self.assertEqual(settle(ledger,fetcher=lambda provider,url:receipt({'events':events},url))['settled'],0)

class InjuryProvenance(TestCase):
    def setup_evidence(self):
        import tests.test_hybrid_nba_injury_verification as verification_tests
        case=verification_tests.NBAInjuryVerificationTests();case.setUp()
        return case

    def verify(self,c):
        from hybrid_engine.nba_injury_verification import verified_pdf_roster_evidence
        return verified_pdf_roster_evidence(c.extraction,capture_receipt=c.capture,verification=c.verification,
            fixture_matchup='AWY@HOM',team_ids=c.teams,player_ids=c.players,prediction_utc=c.prediction,fixture_start_utc=c.prediction+3600)

    def test_bound_pdf_rows_and_pre_prediction_verification_remain_partial_only(self):
        c=self.setup_evidence();r=self.verify(c)
        self.assertEqual(len(r['records']),1);self.assertFalse(r['minutes_adjustment_allowed']);self.assertFalse(r['rotation_verified'])

    def test_rows_from_another_pdf_or_changed_status_are_refused(self):
        for change in ('pdf','row','verification'):
            c=self.setup_evidence()
            if change=='pdf':c.extraction['source_pdf_sha256']='b'*64
            elif change=='row':c.extraction['rows'][0]['status']='Available'
            else:c.verification['rows_sha256']='b'*64
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'ROWS_OR_PUBLICATION_PIN'):self.verify(c)

    def test_late_download_verification_and_stale_report_cannot_enter_pregame_evidence(self):
        for change in ('download','verification','stale'):
            c=self.setup_evidence()
            if change=='download':c.capture['download_completed_at_utc']=c.prediction+1
            elif change=='verification':c.verification['verified_at_utc']=c.prediction+1
            else:c.prediction+=7*3600
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'UNAVAILABLE_OR_STALE'):self.verify(c)

    def test_capture_cannot_backdate_current_download_to_historical_prediction(self):
        from hybrid_engine.nba_injury_capture import capture_official_injury_pdf
        c=self.setup_evidence();opener=Mock(side_effect=AssertionError('network'))
        with patch('time.time',return_value=c.prediction+100),self.assertRaisesRegex(ValueError,'ACTUAL_REPORT_RETRIEVAL'):
            capture_official_injury_pdf(c.capture['source_url'],retrieved_at_utc=c.prediction-10,prediction_utc=c.prediction,opener=opener)
        opener.assert_not_called()

    def test_pdf_capture_rechecks_actual_completion_after_read(self):
        from hybrid_engine.nba_injury_capture import capture_official_injury_pdf
        from tests.test_hybrid_nba_injury_capture import Response
        c=self.setup_evidence();start=c.prediction-1
        with patch('time.time',side_effect=[start,c.prediction+1]),self.assertRaisesRegex(ValueError,'COMPLETED_AFTER_PREDICTION'):
            capture_official_injury_pdf(c.capture['source_url'],retrieved_at_utc=start,prediction_utc=c.prediction,
                opener=lambda req,timeout:Response(c.capture['source_url'],b'%PDF-1.7\nsynthetic'))

class SeasonCohortGuard(TestCase):
    def test_same_model_label_across_different_seasons_is_not_pooled(self):
        row=hardening.LiveMetricTests().row()
        a=dict(row,league='NBA',season='2025/2026',model_version='V1',model_digest='same')
        b=dict(row,league='NBA',season='2026/2027',model_version='V1',model_digest='same')
        with self.assertRaisesRegex(ValueError,'SEPARATE_FITTED_MODEL_COHORTS'):metrics([a,b])

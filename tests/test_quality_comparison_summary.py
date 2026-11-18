"""Visibility of existing frozen-input review; synthetic rows do not prove live accuracy."""
from copy import deepcopy
from unittest import TestCase
from unittest.mock import patch

from hybrid_engine.forecast_error_review import review
from hybrid_engine.quality_report import comparison_summary
from tests.test_phase92 import row


class ComparisonSummaryTests(TestCase):
    def result(self,*,with_profile=True):
        r=row();r['provider_fixture_ids']=['401000001'];r['final_with_ot']=r['actual']
        profile=dict(snapshot_sha256=r['snapshot_sha256'],model_digest=r['model_digest'],
            generated_at_utc=r['prediction_generated_at_utc'],fit_age_seconds=7200,
            history={'home':{'new_games_since_fit':1,'latest_game_utc':r['fixture_start_utc']-86400}},
            feature_usage=dict(verified_pace=False,player_effects=False),quarter_correlation=.99,
            retrospective_baseline=dict(total=198,published_forecast=False))
        asof=r['label_available_utc']+1
        er=review([r],asof_utc=asof,profiles=[profile] if with_profile else [])
        native=dict(snapshot_sha256=r['snapshot_sha256'],fixture_start_utc=r['fixture_start_utc'],
            prediction_generated_at_utc=r['prediction_generated_at_utc'],first_archived_at_utc=r['first_archived_at_utc'])
        return dict(error_review=er,archive_audit=dict(observed_at_utc=asof,rows=[native],performance={'forecasts':[r]}))

    def test_same_frozen_feature_baseline_errors_and_metrics_are_visible_without_fitting(self):
        r=self.result();before=deepcopy(r)
        with patch('hybrid_engine.models.HierarchicalStrength.fit',side_effect=AssertionError('NO_FIT')):
            summary=comparison_summary(r)
        g=summary['groups'][0];c=g['top_cases'][0]
        self.assertEqual(g['matched_metrics']['frozen_model']['mae'],4)
        self.assertEqual(g['matched_metrics']['retrospective_baseline']['mae'],2)
        self.assertEqual(c['frozen_model_error'],-4);self.assertEqual(c['unpublished_baseline_error'],-2)
        self.assertEqual(c['provider_fixture_ids'],['401000001']);self.assertIn('+03:00',c['fixture_start_istanbul'])
        self.assertEqual(c['scope'],'REGULATION_ONLY');self.assertEqual(c['fit_age_seconds'],7200)
        self.assertFalse(g['baseline_was_published']);self.assertFalse(g['superiority_claim']);self.assertEqual(r,before)

    def test_absent_native_profile_stays_unavailable_not_a_zero_baseline_error(self):
        g=comparison_summary(self.result(with_profile=False))['groups'][0]
        self.assertIsNone(g['top_cases'][0]['unpublished_baseline_error'])
        self.assertIsNone(g['matched_metrics']['retrospective_baseline']['mae'])
        self.assertEqual(g['matched_metrics']['retrospective_baseline']['n'],0)

    def test_started_pending_is_distinct_from_unplayed_and_unknown_clock(self):
        r=self.result();asof=r['archive_audit']['observed_at_utc'];forecasts=r['archive_audit']['performance']['forecasts']
        for clock in (asof-1,asof+1,None):forecasts.append(dict(actual=None,fixture_start_utc=clock))
        s=comparison_summary(r)
        self.assertEqual((s['pending_forecasts'],s['started_pending_forecasts'],s['not_started_pending_forecasts'],s['pending_with_unknown_start']),(3,1,1,1))
        self.assertTrue(s['pending_is_not_assumed_unplayed'])

    def test_blocked_archive_remains_empty_no_synthetic_success(self):
        r={'error_review':None,'archive_audit':{'observed_at_utc':1,'rows':[],'performance':None}}
        self.assertEqual(comparison_summary(r)['groups'],[])

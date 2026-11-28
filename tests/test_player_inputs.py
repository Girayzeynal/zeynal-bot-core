"""Collector tests use manufactured source replies, never external Telegram."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock,patch

from core.team_identity import digest
from hybrid_engine.boxes import publish_json
from hybrid_engine.player_inputs import collect,load_snapshot
from hybrid_engine.player_minutes import MinutesArchive
from tests import test_player_minutes as fixtures


class FakeReviewer:
    def __init__(self,data):
        self.data=data; self.calls=0

    def review(self,context):
        self.calls+=1
        result=deepcopy(self.data['review'])
        result['original_snapshot_sha256']=context['original_snapshot_sha256']
        return result

    def _get(self,url,deadline):
        team=url.split('/teams/')[1].split('/')[0]
        side='home' if team=='1' else 'away'
        document=dict(team=dict(id=team,displayName='TestHome' if team=='1' else 'TestAway'),
            season=dict(year=2027),athletes=[dict(id=p,displayName='Player '+p)
                for p in self.data['rosters'][side]['players']])
        body=json.dumps(document).encode()
        return dict(body=body,observed_at_utc=fixtures.NOW-10,
                    body_sha256=__import__('hashlib').sha256(body).hexdigest())


class PlayerInputTests(TestCase):
    def setUp(self):
        timer=patch('time.time',return_value=fixtures.NOW); timer.start(); self.addCleanup(timer.stop)
        tmp=TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name); self.assets=self.root/'assets'; self.assets.mkdir()
        self.data=fixtures.inputs()
        history=[dict(league=b['league'],season=b['season'],fixture_id=b['fixture_id'],
            home_team_id=b['home_team_id'],away_team_id=b['away_team_id'],
            fixture_start_utc=b['fixture_start_utc'],periods=dict(home=[25]*4,away=[24]*4),provider='ESPN')
            for b in self.data['boxes']]
        cut=dict(history=history)
        publish_json(self.assets/'input.json',cut)
        self.snapshot=dict(league='NBA',season='2026/2027',fixture_id='future',
            provider_fixture_ids=['401000001'],fixture_start_utc=fixtures.NOW+3600,
            prediction_generated_at_utc=fixtures.NOW-1800,model_digest='d'*64,
            home=dict(provider_id='1',official_name='TestHome'),away=dict(provider_id='2',official_name='TestAway'),
            input_asset=dict(file='input.json',sha256=digest(cut)),
            prediction=dict(home=100,away=90,total=190))
        self.reviewer=FakeReviewer(self.data)
        self.boxes=Mock(return_value=(self.root/'fake-box.json',dict(games=self.data['boxes'],failures=[])))

    def run_collect(self):
        with patch('hybrid_engine.player_inputs.audit_snapshot',return_value=dict(status='SYNTHETIC')):
            return collect(self.snapshot,self.assets,self.root/'player-shadow',
                reviewer=self.reviewer,box_collector=self.boxes)

    def test_default_collector_uses_bounded_official_public_source_policy(self):
        with patch('hybrid_engine.player_inputs.audit_snapshot',return_value=dict(status='SYNTHETIC')), \
             patch('hybrid_engine.player_inputs.CurrentRosterReview',return_value=self.reviewer) as factory:
            result=collect(self.snapshot,self.assets,self.root/'player-shadow',
                box_collector=self.boxes)
        factory.assert_called_once_with(
            self.root/'player-shadow/current-roster',
            report_archive=self.root/'official-reports',
            bounded_public_pdf_fallback=True)
        self.assertEqual(result['status'],'PROSPECTIVE_MINUTES_ARCHIVED')
        self.assertFalse(result['forecast_changed'])

    def test_collection_archives_inputs_and_preserves_original_forecast(self):
        before=deepcopy(self.snapshot); result=self.run_collect()
        self.assertEqual(result['status'],'PROSPECTIVE_MINUTES_ARCHIVED')
        self.assertEqual(self.snapshot,before)
        self.assertFalse(result['forecast_changed']); self.assertFalse(result['online_training'])
        self.assertEqual(self.boxes.call_args.kwargs['workers'],1)
        publications=MinutesArchive(self.root/'player-shadow/minutes').first()
        self.assertEqual(len(publications),1); self.assertIsNone(publications[0]['projection']['payload']['actual'])

    def test_existing_inputs_replay_without_download_or_reprojection(self):
        first=self.run_collect(); folder=self.root/'player-shadow'
        files={p:p.read_bytes() for p in folder.rglob('*') if p.is_file()}
        self.reviewer.review=Mock(side_effect=AssertionError('NO_NEW_SOURCE_CALL'))
        self.boxes.reset_mock()
        second=self.run_collect()
        self.assertEqual(second['status'],'EXISTING_MINUTES_REPLAY')
        self.assertEqual(first['projection'],second['projection'])
        self.boxes.assert_not_called()
        self.assertEqual(files,{p:p.read_bytes() for p in files})

    def test_started_fixture_is_blocked_before_source_calls(self):
        self.snapshot['fixture_start_utc']=fixtures.NOW
        result=self.run_collect()
        self.assertEqual(result['reason'],'MATCH_STARTED_NO_PLAYER_INPUT_BACKFILL')
        self.assertEqual(self.reviewer.calls,0); self.boxes.assert_not_called()

    def test_invalid_original_audit_and_asset_pin_fail_closed(self):
        result=collect(self.snapshot,self.assets,self.root/'player-shadow',
            reviewer=self.reviewer,box_collector=self.boxes)
        self.assertEqual(result['status'],'BLOCKED'); self.assertEqual(self.reviewer.calls,0)
        self.snapshot['input_asset']['sha256']='0'*64
        self.assertEqual(self.run_collect()['reason'],'PLAYER_INPUT_ASSET_PIN')

    def test_failed_current_review_and_incomplete_boxes_do_not_publish_minutes(self):
        self.data['review']['status']='UNAVAILABLE'
        self.assertEqual(self.run_collect()['reason'],'CURRENT_ROSTER_SOURCE_REVIEW_REQUIRED')
        self.data['review']['status']='CURRENT_SOURCE_OBSERVATIONS'
        self.boxes.return_value=(self.root/'fake-box.json',dict(games=[],failures=['source']))
        self.assertEqual(self.run_collect()['reason'],'INCOMPLETE_NATIVE_PAST_PLAYER_BOXES')
        self.assertEqual(list((self.root/'player-shadow').glob('minutes/minutes-*')),[])

    def test_unknown_current_roster_player_is_reported_without_guessed_minutes(self):
        # A current roster player absent from this team's six prior game boxes
        # is NOT automatically Out or a zero-minute projection.
        self.data['rosters']['home']['players'][0]='999'
        result=self.run_collect()
        self.assertEqual(result['status'],'BLOCKED')
        self.assertEqual(result['reason'],'CURRENT_PLAYER_WITHOUT_PRIOR_ROTATION_HISTORY')
        gap=result['rotation_diagnostics']
        self.assertEqual(gap['home']['past_regulation_games'],6)
        self.assertEqual(gap['home']['missing_history_player_ids'],['999'])
        self.assertEqual(gap['away']['missing_history_player_ids'],[])
        self.assertFalse(gap['home']['actual_minutes_assumed'])
        self.assertFalse(gap['home']['unverified_players_given_zero_minutes'])
        self.assertIsNone(result['projection'])
        self.assertEqual(list((self.root/'player-shadow').glob('minutes/minutes-*')),[])

    def official_only_review(self):
        url='https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-11-16_10_45AM.pdf'
        report_at=fixtures.NOW-900
        self.data['review'].update(official_pdf_clock_verified=True,
            official_stage='FIXTURE_ROWS',
            official_code='SOURCE_ROWS_MATCHED_NOT_MEDICALLY_VERIFIED',
            official_report=dict(source_url=url,report_timestamp_utc=report_at))
        self.data['review']['sources'].append(dict(url=url,observed_at_utc=fixtures.NOW-10))
        self.data['review']['records']=[dict(team_id='1',player_id='100',status='Out',
            source='NBA_OFFICIAL_PDF',identity_status='EXACT_ESPN_ROSTER_MATCH',
            status_updated_at_utc=report_at)]

    def test_official_only_scenario_identifies_downstream_rotation_gap_without_archive(self):
        self.official_only_review()
        self.data['rosters']['home']['players'][1]='999'
        result=self.run_collect()
        self.assertEqual(result['reason'],'ABSENCE_REQUIRES_BOTH_SOURCE_OBSERVATIONS')
        self.assertEqual(result['status'],'BLOCKED')
        self.assertEqual(result['official_only_diagnostic']['status'],'BLOCKED_NOT_ARCHIVED')
        self.assertEqual(result['official_only_diagnostic']['downstream_reason'],
                         'CURRENT_PLAYER_WITHOUT_PRIOR_ROTATION_HISTORY')
        self.assertEqual(result['rotation_diagnostics']['home']['missing_history_player_ids'],['999'])
        self.assertIsNone(result['projection'])
        self.assertFalse(result['official_only_diagnostic']['model_training_eligible'])
        self.assertEqual(list((self.root/'player-shadow').glob('minutes/minutes-*')),[])

    def test_official_only_diagnostic_full_rotation_does_not_publish_any_minutes(self):
        self.official_only_review()
        result=self.run_collect()
        self.assertEqual(result['reason'],'ABSENCE_REQUIRES_BOTH_SOURCE_OBSERVATIONS')
        probe=result['official_only_diagnostic']
        self.assertEqual(probe['status'],'PROVISIONAL_ROTATION_COMPUTED_NOT_ARCHIVED')
        self.assertEqual(probe['official_only_player_ids'],['100'])
        self.assertFalse(probe['scores_computed'])
        self.assertFalse(probe['model_training_eligible'])
        self.assertIsNone(result['projection'])
        self.assertEqual(list((self.root/'player-shadow').glob('minutes/minutes-*')),[])

    def test_missing_ledger_does_not_create_database(self):
        path=self.root/'missing.sqlite'
        with self.assertRaises((ValueError,FileNotFoundError)): load_snapshot(path,'401000001')
        self.assertFalse(path.exists())

    def test_blocked_absence_lists_player_and_missing_corroborating_source(self):
        self.data['review']['records']=[dict(team_id='1',player_id='100',player_name='Test Player',
            source='ESPN',status='Out',status_updated_at_utc=fixtures.NOW-10)]
        result=self.run_collect()
        self.assertEqual(result['reason'],'ABSENCE_REQUIRES_BOTH_SOURCE_OBSERVATIONS')
        d=result['roster_diagnostics']; self.assertEqual(d['missing_absence_count'],1)
        self.assertEqual(d['missing_absence_corroboration'][0]['missing_sources'],['NBA_OFFICIAL_PDF'])
        self.assertIsNone(result['projection'])

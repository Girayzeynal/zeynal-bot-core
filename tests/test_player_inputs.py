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

    def test_missing_ledger_does_not_create_database(self):
        path=self.root/'missing.sqlite'
        with self.assertRaises((ValueError,FileNotFoundError)): load_snapshot(path,'401000001')
        self.assertFalse(path.exists())

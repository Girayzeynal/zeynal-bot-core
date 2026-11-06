from copy import deepcopy
from unittest import TestCase
from unittest.mock import patch

import faz41_faz40 as b
import faz41_evidence as e
import faz41_adapters as a
from prediction_inputs import digest
from faz40_archive import seal_game
from faz40_research import project
from tests.test_faz41_adapters import espn,NOW
from tests.test_faz32 import summary

TARGET=e.fixture_identity(league='NBA',season_end_year=2027,start_utc=NOW+1000,home_team_id='19',away_team_id='2')


class ContextTests(TestCase):
    def setUp(self):
        self.clock=patch('time.time',return_value=NOW+1);self.clock.start();self.addCleanup(self.clock.stop)
        self.registry=deepcopy(e.REGISTRY)
        for p in self.registry.values():p.update(usage='PERMITTED',permission_ref='https://licence.example/synthetic-grant',reviewed_at_utc=NOW-100,expires_at_utc=NOW+1000)
        self.pin=digest(self.registry)

    def announcement(self,**updates):
        raw=dict(format='EXPLICIT_TEAM_ANNOUNCEMENT_V1',fixture=TARGET,provider_fixture_id='0022600099',
                 team_id='19',players=['1','2','3','4','5','6'],starting_five=['1','2','3','4','5'],status='CONFIRMED',published_at_utc=NOW-20)
        raw.update(updates)
        with patch('time.time',return_value=NOW):return b.capture_announcement(raw,provider='NBA',source_url='https://cdn.nba.com/static/json/test/announcement.json',
            observed_at_utc=NOW-10,ingested_at_utc=NOW-5,usage='SYNTHETIC_TEST',registry=self.registry,registry_pin=self.pin)

    def context(self,obs,**updates):
        args=dict(fixture=TARGET,cutoff_utc=NOW+1,registry=self.registry,registry_pin=self.pin);args.update(updates)
        return b.prematch_context(obs,**args)

    def minutes(self):
        with patch('time.time',return_value=NOW):return a.capture(espn(),provider='ESPN',league='NBA',season_end_year=2027,
            data_type='PLAYER_MINUTES',observed_at_utc=NOW-10,ingested_at_utc=NOW-5,
            usage='SYNTHETIC_TEST',registry=self.registry,registry_pin=self.pin)

    def test_source_bound_announcement_reuses_faz40_roster_gate(self):
        x=self.announcement();p=self.context([x])['payload']
        self.assertEqual(p['rosters']['19']['payload']['status'],'CONFIRMED')
        self.assertNotIn('HOME_CONFIRMED_LINEUP',p['missing']);self.assertIn('AWAY_CONFIRMED_LINEUP',p['missing'])
        self.assertEqual(p['evidence_sha256'],[x['sha256']]);self.assertFalse(p['production_coefficients_changed'])

    def test_duplicate_announcement_is_idempotent_and_input_is_unchanged(self):
        x=self.announcement();before=deepcopy(x)
        self.assertEqual(self.context([x]),self.context([x,x]));self.assertEqual(x,before)

    def test_conflicting_announcements_and_rehashed_five_fail_closed(self):
        x=self.announcement();y=self.announcement(starting_five=['2','3','4','5','6'])
        with self.assertRaisesRegex(ValueError,'CONFLICTING'):self.context([x,y])
        x['payload']['claims']['starting_five']=['2','3','4','5','6'];x['sha256']=digest(x['payload'])
        with self.assertRaisesRegex(ValueError,'CANNOT_REPLAY'):self.context([x])

    def test_unknown_permission_past_cutoff_and_poststart_context_refused(self):
        x=self.announcement()
        with self.assertRaises(ValueError):self.context([x],cutoff_utc=NOW)
        with self.assertRaisesRegex(ValueError,'PREMATCH'):self.context([],cutoff_utc=TARGET['start_utc'])
        with self.assertRaisesRegex(ValueError,'PIN'):self.context([],registry_pin='0'*64)
        self.registry['NBA']['usage']='UNKNOWN';self.pin=digest(self.registry)
        x=self.announcement()
        with self.assertRaisesRegex(ValueError,'USAGE_NOT_ESTABLISHED'):self.context([x])

    def test_wrong_team_invalid_five_and_missing_publication_refused(self):
        for changes in [dict(team_id='999'),dict(starting_five=['1']*5),dict(published_at_utc=None)]:
            with self.subTest(changes=changes),self.assertRaises((ValueError,TypeError)):self.announcement(**changes)

    def test_historical_minutes_dedup_and_no_future_roster_inference(self):
        o=self.minutes();x=b.historical_player_features([o,o],target=TARGET,cutoff_utc=NOW+1,registry=self.registry,registry_pin=self.pin)
        self.assertEqual(x['games'],1);self.assertEqual(x['target_roster_status'],'NOT_INFERRED');self.assertIsNone(x['rotation_effect'])
        with self.assertRaisesRegex(ValueError,'BINDING'):self.context([o])

    def test_historical_minutes_future_source_and_other_league_refused(self):
        o=self.minutes();target=deepcopy(TARGET);target['league']='EUROCUP';target['canonical_id']=digest({k:v for k,v in target.items() if k!='canonical_id'})
        with self.assertRaisesRegex(ValueError,'PARTITION'):b.historical_player_features([o],target=target,cutoff_utc=NOW+1,registry=self.registry,registry_pin=self.pin)
        with self.assertRaisesRegex(ValueError,'NOT_AVAILABLE'):b.historical_player_features([o],target=TARGET,cutoff_utc=NOW,registry=self.registry,registry_pin=self.pin)

    def test_research_context_does_not_change_reference_projection(self):
        records=[]
        for i in range(2):
            start=NOW-(i+2)*86400;raw=summary(401909900+i,start,reverse=bool(i));raw.pop('boxscore',None)
            for t in raw['header']['competitions'][0]['competitors']:
                t['score']=str(int(t['score'])+i)
                t['linescores'][0]['displayValue']=str(int(t['linescores'][0]['displayValue'])+i)
            records.append(seal_game(raw,league='NBA',season_end_year=2027,source_observed_utc=start+10000,
                ingested_utc=start+11000,team_ids=['19','2'],usage='SYNTHETIC_TEST'))
        args=dict(mode='ARCHIVED_SOURCE_CLOCK',minimum_team_games=2,simulations=10000)
        before=deepcopy(records);expected=project(records,TARGET,NOW+1,**args)
        self.assertEqual(expected['status'],'PROJECTED_RESEARCH')
        out=b.research_with_context(records,[self.announcement()],target=TARGET,cutoff_utc=NOW+1,
            registry=self.registry,registry_pin=self.pin,**args)['payload']
        self.assertEqual(out['reference'],expected);self.assertFalse(out['evidence_applied_to_coefficients'])
        self.assertEqual(records,before);self.assertEqual(out['prospective_records_created'],0)

    def test_same_team_same_start_with_different_fixture_id_cannot_inflate_player_history(self):
        first=self.minutes();raw=espn();h=raw['header'];h['id']=h['competitions'][0]['id']='401909904'
        for t in h['competitions'][0]['competitors']:
            if t['team']['id']=='2':t['team']['id']='8'
        for block in raw['boxscore']['players']:
            if block['team']['id']=='2':block['team']['id']='8'
        with patch('time.time',return_value=NOW):second=a.capture(raw,provider='ESPN',league='NBA',season_end_year=2027,
            data_type='PLAYER_MINUTES',observed_at_utc=NOW-10,ingested_at_utc=NOW-5,
            usage='SYNTHETIC_TEST',registry=self.registry,registry_pin=self.pin)
        with self.assertRaisesRegex(ValueError,'SAME_TEAM_START_CONFLICT'):
            b.historical_player_features([first,second],target=TARGET,cutoff_utc=NOW+1,registry=self.registry,registry_pin=self.pin)

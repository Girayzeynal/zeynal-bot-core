"""Synthetic event semantics and explicit-role arithmetic, not real accuracy."""
from copy import deepcopy
from unittest import TestCase
from unittest.mock import patch

from prediction_inputs import digest
import faz43_pbp as p
from tests.test_faz42_history import NOW,permitted_registry
from tests.test_faz32 import summary


def game():
    raw=summary(401900001,NOW-86400);raw.pop('boxscore',None);teams={t['homeAway']:t for t in raw['header']['competitions'][0]['competitors']}
    h=a=0;events=[]
    def add(period,clock,kind='110'):
        seq=len(events)+1;events.append(dict(id=str(seq),sequenceNumber=str(seq),period=dict(number=period),clock=dict(displayValue=clock),
                                           homeScore=h,awayScore=a,type=dict(id=kind)))
    for period in range(1,5):
        add(period,'12:00','615');add(period,'8:00','584')
        for side in ('home','away'):
            points=int(teams[side]['linescores'][period-1]['displayValue'])
            while points:
                step=min(points,3)
                if side=='home':h+=step
                else:a+=step
                points-=step;add(period,'6:00')
        add(period,'0.0','412' if period<4 else '402')
    raw['plays']=events;return raw


class PlayEvidenceTests(TestCase):
    def setUp(self):
        self.timer=patch('time.time',return_value=NOW+1);self.timer.start();self.addCleanup(self.timer.stop)
        self.registry=permitted_registry();self.pin=digest(self.registry)

    def seal(self,raw=None):
        with patch('time.time',return_value=NOW):return p.capture_espn_timeline(raw or game(),observed_at_utc=NOW-10,
            ingested_at_utc=NOW-5,usage='SYNTHETIC_TEST',registry=self.registry,registry_pin=self.pin)

    def replay(self,s,**updates):
        args=dict(fixture=s['payload']['fixture'],cutoff_utc=NOW+1,maximum_age_seconds=60,registry=self.registry,registry_pin=self.pin)
        args.update(updates);return p.replay_timeline(s,**args)

    def test_timeline_replays_periods_final_scope_and_missing_wallclock(self):
        q=self.replay(self.seal())['claims'];self.assertEqual(q['final_home'],97)
        self.assertEqual(q['final_away'],108);self.assertGreater(q['event_count'],50)
        self.assertEqual(q['missing_wallclock_events'],q['event_count'])
        self.assertEqual(q['rotation_status'],'ABSTAIN_SUBSTITUTION_ROLES_UNVERIFIED');self.assertIsNone(q['lineup_stints'])
        self.assertFalse(q['parameters_fitted'])

    def test_identical_duplicate_event_does_not_inflate_event_count(self):
        raw=game();count=len(raw['plays']);raw['plays'].insert(2,deepcopy(raw['plays'][1]))
        q=self.replay(self.seal(raw))['claims'];self.assertEqual(q['event_count'],count);self.assertEqual(q['duplicate_identical_events'],1)

    def test_conflicting_id_sequence_and_clock_are_rejected(self):
        for kind in ('id','sequence','clock','period'):
            raw=game()
            if kind=='id':raw['plays'][1]['id']=raw['plays'][0]['id']
            if kind=='sequence':raw['plays'][1]['sequenceNumber']=raw['plays'][0]['sequenceNumber']
            if kind=='clock':raw['plays'][3]['clock']['displayValue']='11:00'
            if kind=='period':raw['plays'][3]['period']['number']=True
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.seal(raw)

    def test_missing_period_end_start_or_score_is_not_complete_pbp(self):
        for kind in ('end','opening','score'):
            raw=game()
            if kind=='end':raw['plays'].pop()
            if kind=='opening':raw['plays'].pop(0)
            if kind=='score':raw['plays'][-1]['homeScore']+=1
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.seal(raw)

    def test_source_event_after_observation_and_wrong_team_are_rejected(self):
        raw=game();raw['plays'][0]['wallclock']='2026-11-06T23:00:00Z'
        with self.assertRaisesRegex(ValueError,'WALLCLOCK'):self.seal(raw)
        raw=game();raw['plays'][1]['team']={'id':'999'}
        with self.assertRaisesRegex(ValueError,'TEAM_MISMATCH'):self.seal(raw)

    def test_rehashed_inferred_rotation_and_url_cannot_bypass_replay(self):
        for kind in ('claim','url'):
            s=self.seal()
            if kind=='claim':s['payload']['claims']['rotation_status']='VERIFIED'
            else:s['payload']['source_url']='https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event=999'
            s['sha256']=digest(s['payload'])
            with self.subTest(kind=kind),self.assertRaisesRegex(ValueError,'CANNOT_REPLAY'):self.replay(s)

    def test_no_permission_or_future_materialization_never_enters_features(self):
        s=self.seal()
        with self.assertRaisesRegex(ValueError,'NOT_AVAILABLE'):self.replay(s,cutoff_utc=NOW)
        self.registry['ESPN']['usage']='UNKNOWN';self.pin=digest(self.registry);s=self.seal()
        with self.assertRaisesRegex(ValueError,'USAGE_NOT_ESTABLISHED'):self.replay(s)

    def test_clock_fraction_precision_and_invalid_minute_forms(self):
        self.assertEqual(p.clock_ms('0.1',720),100);self.assertEqual(p.clock_ms('11:59.250',720),719250)
        for value in ('12:60','13:00','-1','NaN','1:2',None):
            with self.subTest(value=value),self.assertRaises(ValueError):p.clock_ms(value,720)


    def test_late_allocated_sequence_number_is_not_used_to_resort_game_clock(self):
        raw=game();raw['plays'][4]['sequenceNumber']='9999'
        q=self.replay(self.seal(raw))['claims']
        self.assertEqual(q['source_sequence_reversals'],1)
        self.assertEqual([e['event_id'] for e in q['events']],[e['id'] for e in raw['plays']])


    def test_retrospective_score_corrections_are_not_repaired_into_training_data(self):
        for kind in ('decrease','both_teams'):
            raw=game()
            if kind=='decrease':raw['plays'][4]['homeScore']=0
            else:raw['plays'][4]['awayScore']=1
            with self.subTest(kind=kind),self.assertRaisesRegex(ValueError,'SCORE_CORRECTION_OR_MISSING_SCORING_EVENT'):
                self.seal(raw)


class ExplicitRotationTests(TestCase):
    def setUp(self):
        self.rosters={t:[t+str(i) for i in range(7)] for t in ('H','A')};self.starters={t:r[:5] for t,r in self.rosters.items()}

    def run_rotation(self,events=None,**updates):
        args=dict(starters=self.starters,rosters=self.rosters,total_ms=1000);args.update(updates)
        return p.explicit_rotation([dict(elapsed_ms=500,team_id='H',player_in='H5',player_out='H4')] if events is None else events,**args)

    def test_five_players_and_player_duration_are_conserved(self):
        before=deepcopy(self.rosters);r=self.run_rotation();self.assertEqual(r['player_ms']['H4'],500);self.assertEqual(r['player_ms']['H5'],500)
        self.assertEqual(sum(r['player_ms'].get(pid,0) for pid in self.rosters['H']),5000)
        self.assertTrue(all(len(s['players'])==5 for s in r['stints']));self.assertEqual(before,self.rosters)
        self.assertIsNone(r['causal_lineup_effect']);self.assertIsNone(r['possessions'])

    def test_simultaneous_subs_are_an_atomic_batch(self):
        r=self.run_rotation([dict(elapsed_ms=500,team_id='H',player_in='H5',player_out='H3'),dict(elapsed_ms=500,team_id='H',player_in='H6',player_out='H4')])
        self.assertEqual(r['stints'][-2]['players'],['H0','H1','H2','H5','H6'])

    def test_unverified_missing_roles_and_bad_roster_never_guess_a_lineup(self):
        for event in [dict(elapsed_ms=500,team_id='H',participants=['H5','H4']),dict(elapsed_ms=500,team_id='H',player_in='A0',player_out='H4')]:
            with self.subTest(event=event),self.assertRaises((ValueError,KeyError)):self.run_rotation([event])
        with self.assertRaisesRegex(ValueError,'FIVE_CONFIRMED'):self.run_rotation(starters={'H':['H0']*5,'A':self.starters['A']})

    def test_double_out_wrong_player_and_clock_reversal_are_rejected(self):
        for rows in [[dict(elapsed_ms=500,team_id='H',player_in='H5',player_out='H6')],
                     [dict(elapsed_ms=-1,team_id='H',player_in='H5',player_out='H4')],
                     [dict(elapsed_ms=500,team_id='H',player_in='H5',player_out='H4'),dict(elapsed_ms=500,team_id='H',player_in='H6',player_out='H4')]]:
            with self.subTest(rows=rows),self.assertRaises(ValueError):self.run_rotation(rows)

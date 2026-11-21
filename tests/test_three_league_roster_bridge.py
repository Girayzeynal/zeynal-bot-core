"""Synthetic fixture/roster receipts only. No real transfer or player prediction."""
import copy
import json
import time
import unittest

from hybrid_engine.three_league_roster_bridge import (
    LEAGUES, snapshot, verify, compare, europe_pair, fixture_gate, readiness
)

NOW=int(time.time())-120
SOURCE='a'*64


def reg(league,club,players=('p1','p2','p3','p4','p5','p6'),at=NOW):
    return snapshot(league=league,season='2026/2027',team_id=club,
        observed_at_utc=at,source_url='https://www.example.org/official/roster',
        source_body_sha256=SOURCE,
        players=[dict(player_id=p,name=p.upper()) for p in players],
        source_kind=('NBA_OFFICIAL_ROSTER_DIRECTORY' if league=='NBA'
                     else 'EUROPE_OFFICIAL_SEASON_REGISTRATION'))


def game(league='NBA'):
    return dict(league=league,season='2026/2027',fixture_id='forthcoming',
        home_team_id='H',away_team_id='A',decision_utc=NOW+10,tipoff_utc=NOW+6000)


def complete():
    fixture=game()
    h=reg('NBA','H',players=tuple('h'+str(i) for i in range(1,7)))
    a=reg('NBA','A',players=tuple('a'+str(i) for i in range(1,7)))
    availability=dict(fixture_id=fixture['fixture_id'],
        observed_at_utc=NOW+1,scope='PREGAME_NOT_BACKFILLED',
        home={f'h{i}':'AVAILABLE' for i in range(1,7)},
        away={f'a{i}':'AVAILABLE' for i in range(1,7)})
    exposures=dict(fixture_id=fixture['fixture_id'],
        observed_at_utc=NOW+2,scope='PREGAME_NOT_BACKFILLED',
        home={f'h{i}':48.0 for i in range(1,6)},
        away={f'a{i}':48.0 for i in range(1,6)})
    fit=dict(status='VERIFIED_HISTORICAL_PREFIT_EXPOSURE_MODEL',
        trained_until_utc=NOW-100,training_includes_target=False,
        source_attestation='INDEPENDENT_VERIFICATION_PENDING')
    return fixture,h,a,availability,exposures,fit


class ThreeLeagueRosterBridgeTests(unittest.TestCase):
    def test_nba_and_two_european_leagues_have_separate_snapshots(self):
        for league in LEAGUES:
            with self.subTest(league=league):
                w=reg(league,'H')
                self.assertEqual(verify(w)['league'],league)
                self.assertFalse(w['payload']['model_input_allowed'])
                self.assertFalse(w['payload']['match_availability_verified'])

    def test_registration_delta_is_not_a_transfer(self):
        original=reg('EUROCUP','H',at=NOW-90)
        later=reg('EUROCUP','H',players=('p1','p2','p3','p4','p5','new'),at=NOW)
        d=compare(original,later,decision_utc=NOW+3)
        self.assertEqual(d['newly_registered_player_ids'],['new'])
        self.assertEqual(d['no_longer_registered_player_ids'],['p6'])
        self.assertFalse(d['confirms_transfer_contract'])
        self.assertTrue(d['can_automatically_update_observed_roster'])
        self.assertFalse(d['changes_forecast'])

    def test_only_a_news_story_does_not_update_roster(self):
        a=reg('EUROLEAGUE','H',at=NOW-90)
        b=copy.deepcopy(a)
        # News URL/title never enters the signed official directory interface.
        self.assertEqual(compare(a,b,decision_utc=NOW+2)['newly_registered_player_ids'],[])
        with self.assertRaisesRegex(TypeError,'unexpected keyword'):
            snapshot(league='EUROLEAGUE',season='2026/2027',team_id='H',
                     observed_at_utc=NOW,source_url='https://example.org',
                     source_body_sha256=SOURCE,players=[dict(player_id='p1',name='P1')],
                     source_kind='EUROPE_OFFICIAL_SEASON_REGISTRATION',
                     rumour='star player signed')

    def test_same_identity_cross_team_or_scope_refused(self):
        a=reg('NBA','H')
        b=reg('NBA','A')
        with self.assertRaisesRegex(ValueError,'CROSS_TEAM'):
            compare(a,b,decision_utc=NOW+4)
        with self.assertRaisesRegex(ValueError,'DIRECTORY_LEAGUE'):
            snapshot(league='NBA',season='2026/2027',team_id='H',observed_at_utc=NOW,
                source_url='https://example.org',source_body_sha256=SOURCE,
                players=[dict(player_id='p1',name='P1')],
                source_kind='EUROPE_OFFICIAL_SEASON_REGISTRATION')

    def test_player_id_and_envelope_tampering_rejected(self):
        w=reg('NBA','H')
        w['payload']['players'].append(dict(player_id='bad',name='Bad'))
        with self.assertRaisesRegex(ValueError,'TAMPERED'):
            verify(w)
        with self.assertRaisesRegex(ValueError,'UNIQUE_PLAYER'):
            reg('NBA','H',players=('same','same','p3'))

    def test_no_late_or_reversed_roster_update(self):
        with self.assertRaisesRegex(ValueError,'POSTTIPOFF'):
            snapshot(league='NBA',season='2026/2027',team_id='H',
                observed_at_utc=NOW,source_url='https://example.org',
                source_body_sha256=SOURCE,
                players=[dict(player_id='p1',name='P1')],
                source_kind='NBA_OFFICIAL_ROSTER_DIRECTORY',fixture_tipoff_utc=NOW)
        with self.assertRaisesRegex(ValueError,'ASOF_CUTOFF'):
            compare(reg('NBA','H',at=NOW),reg('NBA','H',at=NOW-90),decision_utc=NOW+3)

    def test_europe_native_pair_uses_existing_official_player_source(self):
        import hashlib
        for league,comp in (('EUROLEAGUE','E'),('EUROCUP','U')):
            with self.subTest(league=league):
                ctx=dict(league=league,season='2026/2027',fixture_id='forthcoming',
                    fixture_start_utc=NOW+5000,
                    home=dict(provider_id='ZAL'),away=dict(provider_id='PAN'))
                def get(url):
                    team='ZAL' if url.endswith('/ZAL/people') else 'PAN'
                    entries=[dict(type='J',person=dict(name='P'+str(i),code=team+str(i)),
                        club=dict(code=team),season=dict(code=comp+'2026')) for i in range(6)]
                    return dict(status='RECEIVED',body=json.dumps(entries).encode(),
                                observed_at_utc=NOW)
                out=europe_pair(ctx,getter=get,clock=lambda:NOW+10)
                self.assertEqual(out['teams']['home']['status'],'REGISTRATION_SNAPSHOT_READY_NOT_LINEUP')
                self.assertEqual(len(verify(out['teams']['home']['roster'])['players']),6)
                self.assertFalse(out['model_input_allowed'])
                self.assertTrue(out['roster_season_not_match_availability'])

    def test_europe_native_source_failure_keeps_unknown(self):
        ctx=dict(league='EUROCUP',season='2026/2027',fixture_id='f',
            fixture_start_utc=NOW+5000,
            home=dict(provider_id='ZAL'),away=dict(provider_id='PAN'))
        out=europe_pair(ctx,getter=lambda url:dict(status='SOURCE_HTTP_ERROR',http_status=429),
                        clock=lambda:NOW+10)
        self.assertEqual(out['teams']['home']['status'],'SOURCE_UNAVAILABLE_OR_INCOMPLETE')
        self.assertIsNone(out['teams']['away']['roster'])

    def test_unverified_effect_artifact_blocks_all_three(self):
        for league in LEAGUES:
            with self.subTest(league=league):
                fix=game(league);h=reg(league,'H');a=reg(league,'A')
                out=fixture_gate(fixture=fix,home_roster=h,away_roster=a,
                                 availability=None,exposures=None,fit=None)
                self.assertEqual(out['status'],'BLOCKED_PLAYER_STATUS_MINUTES_OR_FIT_MISSING')
                self.assertFalse(out['production_model_changed'])

    def test_complete_declared_exposure_only_research_not_live(self):
        fix,h,a,status,minutes,fit=complete()
        out=fixture_gate(fixture=fix,home_roster=h,away_roster=a,
                         availability=status,exposures=minutes,fit=fit)
        self.assertEqual(out['status'],'RESEARCH_CONTEXT_PRECHECK_ONLY')
        self.assertFalse(out['source_attestation_independently_verified'])
        self.assertFalse(out['scoring_engine_connected'])
        self.assertFalse(out['numeric_effect_coefficients_applied'])
        self.assertEqual(out['model_player_input']['home']['expected_minutes']['h1'],48)

    def test_absent_registered_player_never_infers_playing_or_minutes(self):
        fix,h,a,status,minutes,fit=complete()
        minutes['home']['unknown']=minutes['home'].pop('p1')
        out=fixture_gate(fixture=fix,home_roster=h,away_roster=a,
                        availability=status,exposures=minutes,fit=fit)
        self.assertIn('BLOCKED_UNKNOWN_PLAYER_ID',out['status'])

    def test_injured_or_questionable_never_treated_as_available(self):
        for case in ('OUT','QUESTIONABLE'):
            with self.subTest(status=case):
                fix,h,a,status,minutes,fit=complete()
                status['home']['h1']=case
                out=fixture_gate(fixture=fix,home_roster=h,away_roster=a,
                                 availability=status,exposures=minutes,fit=fit)
                self.assertIn('UNAVAILABLE_OR_UNCERTAIN',out['status'])

    def test_50_minute_player_or_missing_team_minutes_blocks(self):
        fix,h,a,status,minutes,fit=complete()
        minutes['home']['h1']=52
        minutes['home']['h2']=44
        out=fixture_gate(fixture=fix,home_roster=h,away_roster=a,
                         availability=status,exposures=minutes,fit=fit)
        self.assertIn('BLOCKED_ROTATION',out['status'])

    def test_player_in_two_teams_must_be_rejected(self):
        fix,h,a,status,minutes,fit=complete()
        duplicated=reg('NBA','A',players=('h1','a2','a3','a4','a5','a6'))
        with self.assertRaisesRegex(ValueError,'DUPLICATED_ACROSS_TEAMS'):
            fixture_gate(fixture=fix,home_roster=h,away_roster=duplicated,
                         availability=status,exposures=minutes,fit=fit)

    def test_postdecision_status_cannot_rewrite_prematch(self):
        fix,h,a,status,minutes,fit=complete()
        status['observed_at_utc']=fix['decision_utc']+1
        out=fixture_gate(fixture=fix,home_roster=h,away_roster=a,
                         availability=status,exposures=minutes,fit=fit)
        self.assertEqual(out['status'],'BLOCKED_STATUS_PREGAME_EVIDENCE')

    def test_wrong_fixture_or_team_refused(self):
        fix,h,a,status,minutes,fit=complete()
        with self.assertRaisesRegex(ValueError,'ROSTER_FIXTURE'):
            fixture_gate(fixture=fix,home_roster=h,away_roster=reg('NBA','wrong'),
                         availability=status,exposures=minutes,fit=fit)

    def test_production_coverage_is_not_claimed(self):
        r=readiness()
        self.assertEqual(r['club_count'],82)
        self.assertEqual(r['observed_official_club_news_pilots'],6)
        self.assertFalse(r['production_score_model_player_inputs'])
        self.assertFalse(r['fully_automatic_transfer_news_to_current_roster'])
        self.assertFalse(r['production_changed'])

if __name__=='__main__':unittest.main()

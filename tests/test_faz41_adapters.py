"""Synthetic provider contract tests. Real access checks are separate."""
from copy import deepcopy
from datetime import datetime,timezone
from unittest import TestCase
from unittest.mock import patch

import faz41_adapters as a
import faz41_evidence as e
from prediction_inputs import digest
from tests.test_faz32 import summary
from tests.test_euroleague_live import source

NOW=1793960000


def espn():
    raw=summary(401909903,NOW-86400)
    raw['boxscore']['players']=[]
    for t in raw['header']['competitions'][0]['competitors']:
        tid=t['team']['id'];score=int(t['score'])
        raw['boxscore']['players'].append(dict(team={'id':tid},statistics=[dict(labels=['MIN','PTS'],athletes=[
            dict(athlete={'id':tid+str(i)},stats=['48',str(score if i==0 else 0)],starter=True,didNotPlay=False) for i in range(5)])]))
    return raw


def nba(raw=None):
    raw=raw or espn();c=raw['header']['competitions'][0];teams={t['homeAway']:t for t in c['competitors']}
    g=dict(gameId='0022600001',gameStatus=3,gameTimeUTC=c['date'])
    for side,t in teams.items():
        g[side+'Team']=dict(teamId=int(next(n for n,v in a.NBA_TO_ESPN.items() if v==t['team']['id'])),
            score=int(t['score']),periods=[dict(period=i+1,periodType='REGULAR',score=int(p['displayValue'])) for i,p in enumerate(t['linescores'])])
    return dict(game=g)


class ReplayAdapterTests(TestCase):
    def setUp(self):
        self.clock=patch('time.time',return_value=NOW+1);self.clock.start();self.addCleanup(self.clock.stop)

    def capture(self,raw=None,provider='ESPN',league='NBA',**opts):
        with patch('time.time',return_value=NOW):
            return a.capture(raw or espn(),provider=provider,league=league,season_end_year=2027,
                observed_at_utc=NOW-10,ingested_at_utc=NOW-5,usage='SYNTHETIC_TEST',**opts)

    def replay(self,o,**updates):
        params=dict(fixture=o['payload']['fixture'],cutoff_utc=NOW+1,maximum_age_seconds=60,require_permitted=False)
        params.update(updates);return a.replay(o,**params)

    def test_nba_and_espn_resolve_same_fixture_despite_different_ids(self):
        x=self.capture();y=self.capture(nba(),provider='NBA')
        self.assertEqual(x['payload']['fixture'],y['payload']['fixture'])
        self.assertNotEqual(x['payload']['provider_fixture_id'],y['payload']['provider_fixture_id'])
        out=e.compare_observations([x,y],fixture=x['payload']['fixture'],cutoff_utc=NOW+1,maximum_age_seconds=60,require_permitted=False)
        self.assertTrue(all(c['status']=='INDEPENDENT_OWNER_AGREEMENT' for c in out))
        self.assertTrue(all(c['usage_statuses']==['UNKNOWN'] for c in out))
        self.replay(x);self.replay(y)

    def test_nba_conflict_same_fixture_is_reported(self):
        x=self.capture();raw=nba();raw['game']['homeTeam']['score']+=1;raw['game']['homeTeam']['periods'][0]['score']+=1
        y=self.capture(raw,provider='NBA')
        rows=e.compare_observations([x,y],fixture=x['payload']['fixture'],cutoff_utc=NOW+1,maximum_age_seconds=60,require_permitted=False)
        self.assertIn('CONFLICT',{r['status'] for r in rows})

    def test_team_orientation_and_one_second_tipoff_conflict_cannot_match(self):
        x=self.capture()
        for change in ('teams','time'):
            raw=nba()
            if change=='teams':raw['game']['homeTeam'],raw['game']['awayTeam']=raw['game']['awayTeam'],raw['game']['homeTeam']
            else:raw['game']['gameTimeUTC']=datetime.fromtimestamp(NOW-86400+1,timezone.utc).isoformat()
            y=self.capture(raw,provider='NBA')
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'BINDING'):
                self.replay(y,fixture=x['payload']['fixture'])

    def test_rehashed_claim_and_source_url_cannot_bypass_raw_replay(self):
        for key,value in [('claims',{'final_home':999}),('provider_fixture_id','401909999'),('source_url','https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event=999')]:
            x=self.capture();x['payload'][key]=value;x['sha256']=digest(x['payload'])
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'CANNOT_REPLAY'):self.replay(x)

    def test_nba_final_status_season_period_and_date_only_fail_closed(self):
        for key,value in [('gameStatus',2),('gameId','0022500001'),('gameTimeUTC','2026-11-01')]:
            raw=nba();raw['game'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.capture(raw,provider='NBA')
        raw=nba();raw['game']['homeTeam']['periods'][0]['score']+=1
        with self.assertRaises(ValueError):self.capture(raw,provider='NBA')

    def test_nba_overtime_requires_preceding_tie_and_keeps_regulation_separate(self):
        raw=nba()
        for side in ('home','away'):
            team=raw['game'][side+'Team'];team['periods']=[dict(period=i+1,periodType='REGULAR',score=25) for i in range(4)]
            team['periods'].append(dict(period=5,periodType='OVERTIME',score=10 if side=='home' else 8));team['score']=110 if side=='home' else 108
        x=self.capture(raw,provider='NBA');p=self.replay(x)
        self.assertEqual(p['claims']['regulation_home'],100);self.assertEqual(p['claims']['final_home'],110)
        raw['game']['homeTeam']['periods'][0]['score']+=1;raw['game']['homeTeam']['score']+=1
        with self.assertRaisesRegex(ValueError,'OVERTIME'):self.capture(raw,provider='NBA')

    def test_el_ec_reuse_verified_period_parsers_without_cross_contamination(self):
        for league in ('EUROLEAGUE','EUROCUP'):
            raw=source(league)['game'];o=self.capture(raw,provider='EUROLEAGUE_LIVE',league=league)
            self.assertEqual(self.replay(o)['fixture']['league'],league)
        with self.assertRaises(ValueError):self.capture(source('EUROCUP')['game'],provider='EUROLEAGUE_LIVE',league='EUROLEAGUE')

    def test_historical_minutes_keep_provider_namespace_and_rounding_precision(self):
        x=self.capture(data_type='PLAYER_MINUTES');p=self.replay(x)
        self.assertEqual(p['claims']['role'],'HISTORICAL_BOXSCORE_NOT_FUTURE_ROSTER')
        row=next(iter(p['claims']['teams'].values()))[0]
        self.assertTrue(row['player_id'].startswith('ESPN:'));self.assertEqual(row['minutes_precision'],'WHOLE_MINUTE_DISPLAY')
        self.assertIsNone(p['claims']['rotation_stints'])

    def test_minutes_points_duplicate_and_team_membership_fail_closed(self):
        for kind in ('minutes','points','duplicate','team','labels'):
            raw=espn();block=raw['boxscore']['players'][0];row=block['statistics'][0]['athletes'][0]
            if kind=='minutes':row['stats'][0]='49'
            if kind=='points':row['stats'][1]='999'
            if kind=='duplicate':block['statistics'][0]['athletes'].append(deepcopy(row))
            if kind=='team':block['team']['id']='999'
            if kind=='labels':block['statistics'][0]['labels']=['MIN','MIN']
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.capture(raw,data_type='PLAYER_MINUTES')

    def test_missing_euro_player_seconds_is_missing_not_invented(self):
        raw=source('EUROLEAGUE');raw['stats']['local']['players'][0]['stats'].pop('timePlayed',None)
        with self.assertRaisesRegex(ValueError,'MALFORMED'):self.capture({'game':raw['game'],'stats':raw['stats']},provider='EUROLEAGUE_LIVE',league='EUROLEAGUE',data_type='PLAYER_MINUTES')

    def test_euro_integral_float_seconds_are_source_counts_not_missing_minutes(self):
        raw=source('EUROLEAGUE')
        for side in ('local','road'):
            players=raw['stats'][side]['players'];n=len(players)
            for i,p in enumerate(players):p['stats']['timePlayed']=float(12000//n+(i<12000%n))
        o=self.capture({'game':raw['game'],'stats':raw['stats']},provider='EUROLEAGUE_LIVE',league='EUROLEAGUE',data_type='PLAYER_MINUTES')
        p=self.replay(o)
        for rows in p['claims']['teams'].values():
            self.assertEqual(round(sum(r['minutes'] for r in rows)*60),12000)
        for value in [True,float('nan'),1.5,-1.0]:
            with self.subTest(value=value),self.assertRaises(ValueError):a._count(value)

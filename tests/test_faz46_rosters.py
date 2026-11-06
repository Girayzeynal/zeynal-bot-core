"""Known provider DTO shapes with synthetic clocks; no real lineup claim."""
from copy import deepcopy
from datetime import datetime,timezone
from unittest import TestCase
from unittest.mock import patch

from prediction_inputs import digest
from faz41_evidence import REGISTRY,fixture_identity
from faz41_faz40 import prematch_context
import faz46_rosters as r
from faz42_schedule import seal_schedule
from tests.test_euroleague_live import source
from tests.test_faz33 import event
from tests.test_faz42_history import NOW,permitted_registry

START=NOW+3600


def euro(league='EUROLEAGUE',empty=False):
    raw=source(league);g=raw['game'];g['played']=False;g['utcDate']=datetime.fromtimestamp(START,timezone.utc).isoformat()
    for side in ('local','road'):
        g[side]['score']=0;g[side]['partials']={**{'partials'+str(i):0 for i in range(1,5)},'extraPeriods':{}}
        for row in raw['stats'][side]['players']:row['stats']['timePlayed']=row['stats']['points']=0
        if empty:raw['stats'][side]['players']=[];raw['stats'][side]['team']=None
    f=fixture_identity(league=league,season_end_year=2027,start_utc=START,home_team_id=g['local']['club']['code'],away_team_id=g['road']['club']['code'])
    return dict(game=g,stats=raw['stats']),f,g['identifier']


class EndpointRosterTests(TestCase):
    def setUp(self):
        self.timer=patch('time.time',return_value=NOW);self.clock=self.timer.start();self.addCleanup(self.timer.stop)
        self.registry=permitted_registry();self.pin=digest(self.registry);self.raw,self.fixture,self.pid=euro()

    def capture(self,raw=None,fixture=None,pid=None,registry=None,**kw):
        registry=registry or self.registry;options=dict(provider='EUROLEAGUE_LIVE',fixture=fixture or self.fixture,pid=pid or self.pid,
            observed_at_utc=NOW-10,ingested_at_utc=NOW-5,usage='SYNTHETIC_TEST',registry=registry,registry_pin=digest(registry));options.update(kw)
        with patch('time.time',return_value=NOW-1):return r.capture_listings(self.raw if raw is None else raw,**options)

    def replay(self,o,**kw):
        options=dict(fixture=o['payload']['fixture'],cutoff_utc=NOW,maximum_age_seconds=300,registry=self.registry,registry_pin=self.pin);options.update(kw)
        return r.replay_listing(o,**options)

    def test_source_lists_are_namespaced_and_never_confirmed_lineups(self):
        rows,status=self.capture();self.assertEqual(len(rows),2);self.assertEqual(status,'UNCONFIRMED_SOURCE_LISTING_AVAILABLE')
        for row in rows:
            p=self.replay(row);self.assertEqual(p['data_type'],'ROSTER');self.assertIsNone(p['claims']['starting_five']);self.assertIsNone(p['claims']['active_for_target'])
            self.assertTrue(all(p.startswith('EUROLEAGUE_LIVE:') for p in p['claims']['players']))
        c=prematch_context(rows,fixture=self.fixture,cutoff_utc=NOW,registry=self.registry,registry_pin=self.pin)['payload']
        self.assertEqual(c['rosters'],{});self.assertEqual(len(c['unconfirmed_source_rosters']),2)
        self.assertIn('HOME_CONFIRMED_LINEUP',c['missing']);self.assertIn('AWAY_CONFIRMED_LINEUP',c['missing'])

    def test_eurocup_season_namespace_stays_separate(self):
        raw,f,pid=euro('EUROCUP');rows,_=self.capture(raw,fixture=f,pid=pid)
        self.assertTrue(all(self.replay(o)['fixture']['league']=='EUROCUP' for o in rows))
        with self.assertRaises(ValueError):self.capture(raw,fixture=self.fixture,pid=self.pid)

    def test_empty_future_stats_and_null_team_are_missing_not_an_exception(self):
        raw,f,pid=euro(empty=True);rows,status=self.capture(raw,fixture=f,pid=pid)
        self.assertEqual(rows,[]);self.assertEqual(status,'ABSTAIN_ROSTER_NOT_PUBLISHED')

    def test_start_five_and_active_flags_never_promote_roster_to_lineup(self):
        for group in self.raw['stats'].values():
            for row in group['players']:row['stats']['startFive']=True;row['player']['active']=True
        rows,_=self.capture()
        self.assertTrue(all(self.replay(o)['claims']['starting_five'] is None for o in rows))

    def test_historical_played_game_or_nonzero_stats_cannot_be_relabelled_pregame(self):
        for label in ('played','game_score','quarter_score','player_minutes','player_points'):
            raw=deepcopy(self.raw)
            if label=='played':raw['game']['played']=True
            elif label=='game_score':raw['game']['local']['score']=1
            elif label=='quarter_score':raw['game']['local']['partials']['partials1']=1
            else:raw['stats']['local']['players'][0]['stats']['timePlayed' if label=='player_minutes' else 'points']=1
            with self.subTest(label=label),self.assertRaises(ValueError):self.capture(raw)

    def test_duplicate_cross_team_player_wrong_club_or_season_fail_closed(self):
        for label in ('duplicate','cross_team','club','season','whitespace'):
            raw=deepcopy(self.raw);row=raw['stats']['local']['players'][0]
            if label=='duplicate':raw['stats']['local']['players'].append(deepcopy(row))
            if label=='cross_team':raw['stats']['road']['players'][0]['player']['person']['code']=row['player']['person']['code']
            if label=='club':row['player']['club']['code']='OTHER'
            if label=='season':row['player']['season']['code']='E2025'
            if label=='whitespace':row['player']['person']['code']=' '+row['player']['person']['code']
            with self.subTest(label=label),self.assertRaises(ValueError):self.capture(raw)

    def test_schedule_one_second_mismatch_is_refused(self):
        f=dict(self.fixture);f=fixture_identity(**{**{k:v for k,v in f.items() if k!='canonical_id'},'start_utc':START+1})
        with self.assertRaisesRegex(ValueError,'FIXTURE_MISMATCH'):self.capture(fixture=f)

    def test_unknown_permissions_allow_inventory_but_not_model_context(self):
        rows,_=self.capture(registry=REGISTRY);self.assertEqual(len(rows),2)
        for row in rows:
            with self.assertRaisesRegex(ValueError,'SOURCE_USAGE_NOT_ESTABLISHED'):
                r.replay_listing(row,fixture=self.fixture,cutoff_utc=NOW,maximum_age_seconds=300)
        with self.assertRaisesRegex(ValueError,'SOURCE_USAGE_NOT_ESTABLISHED'):prematch_context(rows,fixture=self.fixture,cutoff_utc=NOW)

    def test_future_observation_equal_cutoff_stale_and_posttip_capture_are_refused(self):
        with self.assertRaisesRegex(ValueError,'SOURCE_CHRONOLOGY'):self.capture(observed_at_utc=NOW+1,ingested_at_utc=NOW+1)
        row=self.capture()[0][0]
        with self.assertRaisesRegex(ValueError,'NOT_AVAILABLE'):self.replay(row,cutoff_utc=NOW-1)
        with self.assertRaisesRegex(ValueError,'STALE'):self.replay(row,maximum_age_seconds=5)
        self.clock.return_value=START
        with self.assertRaisesRegex(ValueError,'WINDOW_CLOSED'):
            r.capture_listings(self.raw,fixture=self.fixture,provider='EUROLEAGUE_LIVE',pid=self.pid,observed_at_utc=NOW-10,ingested_at_utc=NOW-5)

    def test_rehashed_fake_five_or_official_type_is_not_an_announcement(self):
        row=self.capture()[0][0];row['payload']['claims']['starting_five']=row['payload']['claims']['players'][:5];row['sha256']=digest(row['payload'])
        with self.assertRaisesRegex(ValueError,'CANNOT_REPLAY'):self.replay(row)
        row=self.capture()[0][0];row['payload']['data_type']='OFFICIAL_LINEUP';row['sha256']=digest(row['payload'])
        with self.assertRaisesRegex(ValueError,'EXPLICIT_TEAM_ANNOUNCEMENT_REQUIRED'):
            prematch_context([row],fixture=self.fixture,cutoff_utc=NOW,registry=self.registry,registry_pin=self.pin)

    def test_identical_replay_is_readonly_and_original_prematch_evidence_survives_tipoff(self):
        rows,_=self.capture(usage='PROSPECTIVE_EVIDENCE');before=deepcopy(rows)
        c1=prematch_context(rows,fixture=self.fixture,cutoff_utc=NOW,registry=self.registry,registry_pin=self.pin)
        self.clock.return_value=START+1000
        c2=prematch_context(rows,fixture=self.fixture,cutoff_utc=NOW,registry=self.registry,registry_pin=self.pin)
        self.assertEqual(c1,c2);self.assertEqual(rows,before)

    def test_espn_header_is_bound_but_historical_boxscore_or_unknown_schema_is_not_roster(self):
        e=event(START,'900000099')
        for team in e['competitions'][0]['competitors']:team['score']='0'
        f=fixture_identity(league='NBA',season_end_year=2027,start_utc=START,home_team_id='19',away_team_id='2')
        for extra,status in [({},'ABSTAIN_ROSTER_NOT_PUBLISHED'),({'boxscore':{'players':[{}]}},'ABSTAIN_BOXSCORE_IS_NOT_PREMATCH_ROSTER'),({'rosters':[{}]},'ABSTAIN_UNSUPPORTED_ROSTER_SCHEMA')]:
            rows,why=r.capture_listings(dict(header=e,**extra),fixture=f,provider='ESPN',pid='900000099',observed_at_utc=NOW-10,ingested_at_utc=NOW-5)
            self.assertEqual(rows,[]);self.assertEqual(why,status)

    def test_partial_capture_crossing_tipoff_returns_no_listings_to_caller(self):
        original=r.seal_observation;calls=[]
        def capture(**kw):
            row=original(**kw);calls.append(row)
            if len(calls)==2:self.clock.return_value=START
            return row
        with patch('faz46_rosters.seal_observation',side_effect=capture),self.assertRaisesRegex(ValueError,'WINDOW_CLOSED'):
            r.capture_listings(self.raw,fixture=self.fixture,provider='EUROLEAGUE_LIVE',pid=self.pid,observed_at_utc=NOW-10,ingested_at_utc=NOW-5)

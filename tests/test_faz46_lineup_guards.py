"""Synthetic normalized contracts, never real provider announcements."""
from copy import deepcopy
from unittest import TestCase
from unittest.mock import patch

from prediction_inputs import digest
from faz41_evidence import fixture_identity
from faz41_faz40 import capture_announcement,prematch_context
from tests.test_faz42_history import NOW,permitted_registry

TARGET=fixture_identity(league='NBA',season_end_year=2027,start_utc=NOW+3600,home_team_id='19',away_team_id='2')


class AnnouncementBindingTests(TestCase):
    def setUp(self):
        self.timer=patch('time.time',return_value=NOW);self.timer.start();self.addCleanup(self.timer.stop)
        self.registry=permitted_registry();self.pin=digest(self.registry)

    def announcement(self,team='19',players=None,provider='NBA',pid='0022600099',fixture=TARGET):
        players=players or [str(i) for i in range(1,7)]
        raw=dict(format='EXPLICIT_TEAM_ANNOUNCEMENT_V1',fixture=fixture,provider_fixture_id=pid,team_id=team,
                 players=players,starting_five=players[:5],status='CONFIRMED',published_at_utc=NOW-20)
        url='https://cdn.nba.com/static/json/test/announcement.json' if provider=='NBA' else 'https://api-live.euroleague.net/v2/competitions/E/seasons/E2026/games/99'
        with patch('time.time',return_value=NOW-1):return capture_announcement(raw,provider=provider,source_url=url,
            observed_at_utc=NOW-10,ingested_at_utc=NOW-5,usage='SYNTHETIC_TEST',registry=self.registry,registry_pin=self.pin)

    def context(self,rows):return prematch_context(rows,fixture=TARGET,cutoff_utc=NOW,registry=self.registry,registry_pin=self.pin)

    def test_same_provider_player_cannot_be_on_both_confirmed_teams(self):
        rows=[self.announcement(),self.announcement(team='2')]
        with self.assertRaisesRegex(ValueError,'CROSS_TEAM_PLAYER_ID_CONFLICT'):self.context(rows)

    def test_provider_prefix_does_not_hide_cross_team_duplicate_identity(self):
        rows=[self.announcement(),self.announcement(team='2',players=['NBA:'+str(i) for i in range(1,7)])]
        with self.assertRaisesRegex(ValueError,'CROSS_TEAM_PLAYER_ID_CONFLICT'):self.context(rows)

    def test_official_provider_cannot_announce_an_unrelated_league(self):
        with self.assertRaisesRegex(ValueError,'ANNOUNCEMENT_PROVIDER_LEAGUE_MISMATCH'):
            self.announcement(provider='EUROLEAGUE_LIVE',pid='E2026_99')

    def test_official_provider_fixture_id_must_match_season(self):
        with self.assertRaisesRegex(ValueError,'ANNOUNCEMENT_PROVIDER_SEASON_MISMATCH'):
            self.announcement(pid='0022500099')

    def test_disjoint_confirmed_teams_stay_valid_and_originals_are_immutable(self):
        rows=[self.announcement(),self.announcement(team='2',players=[str(i) for i in range(11,17)])];before=deepcopy(rows)
        r=self.context(rows);self.assertEqual(set(r['payload']['rosters']),{'19','2'});self.assertEqual(rows,before)

    def test_same_team_bare_and_prefixed_alias_cannot_count_as_two_starters(self):
        players=['1','NBA:1','2','3','4','5'];before=deepcopy(players)
        with self.assertRaisesRegex(ValueError,'ANNOUNCEMENT_PLAYER_ID_CONFLICT'):
            self.announcement(players=players)
        self.assertEqual(players,before)

    def test_alias_duplicate_outside_starting_five_is_also_refused(self):
        with self.assertRaisesRegex(ValueError,'ANNOUNCEMENT_PLAYER_ID_CONFLICT'):
            self.announcement(players=['1','2','3','4','5','NBA:1'])

    def test_foreign_repeated_and_empty_namespaces_are_not_player_ids(self):
        for player in ('ESPN:1','EUROLEAGUE_LIVE:1','NBA:NBA:1','nba:1','NBA:',':1'):
            with self.subTest(player=player),self.assertRaisesRegex(ValueError,'CANONICAL_PLAYER_IDS_REQUIRED'):
                self.announcement(players=[player,'2','3','4','5','6'])

    def test_internal_whitespace_or_invalid_characters_are_not_trimmed(self):
        for player in ('1 2','NBA: 1','NBA:1\t','1/2','1\n2','１'):
            with self.subTest(player=player),self.assertRaisesRegex(ValueError,'CANONICAL_PLAYER_IDS_REQUIRED'):
                self.announcement(players=[player,'2','3','4','5','6'])

    def test_valid_mixed_namespace_ids_keep_the_original_sealed_bytes(self):
        row=self.announcement(players=['1','NBA:2','3','NBA:4','5','NBA:6']);before=deepcopy(row)
        out=self.context([row,row]);roster=out['payload']['rosters']['19']['payload']
        self.assertEqual(roster['players'],row['payload']['raw']['players'])
        self.assertEqual(roster['starting_five'],row['payload']['raw']['starting_five'])
        self.assertEqual(out,self.context([row]));self.assertEqual(row,before)

    def test_rehashed_legacy_alias_announcement_is_refused_without_mutation(self):
        row=self.announcement();p=row['payload']
        for field in ('raw','claims'):
            p[field]['players'][1]='NBA:1';p[field]['starting_five'][1]='NBA:1'
        p['raw_sha256']=digest(p['raw']);row['sha256']=digest(p);before=deepcopy(row)
        with self.assertRaisesRegex(ValueError,'ANNOUNCEMENT_PLAYER_ID_CONFLICT'):self.context([row])
        self.assertEqual(row,before)

    def test_foreign_namespace_cannot_hide_a_cross_team_player_conflict(self):
        first=self.announcement();before=deepcopy(first)
        with self.assertRaisesRegex(ValueError,'CANONICAL_PLAYER_IDS_REQUIRED'):
            self.context([first,self.announcement(team='2',players=['ESPN:1','11','12','13','14','15'])])
        self.assertEqual(first,before)

    def test_european_leagues_use_their_bound_provider_namespace(self):
        for league,code in (('EUROLEAGUE','E'),('EUROCUP','U')):
            fixture=fixture_identity(league=league,season_end_year=2027,start_utc=NOW+3600,home_team_id='H',away_team_id='A')
            options=dict(provider='EUROLEAGUE_LIVE',pid=code+'2026_99',fixture=fixture,team='H')
            with self.subTest(league=league):
                for players in (['1','EUROLEAGUE_LIVE:1','2','3','4','5'],
                                ['1','2','3','4','5','EUROLEAGUE_LIVE:1']):
                    with self.assertRaisesRegex(ValueError,'ANNOUNCEMENT_PLAYER_ID_CONFLICT'):
                        self.announcement(players=players,**options)
                with self.assertRaisesRegex(ValueError,'CANONICAL_PLAYER_IDS_REQUIRED'):
                    self.announcement(players=['NBA:1','2','3','4','5','6'],**options)
                row=self.announcement(players=['p1','EUROLEAGUE_LIVE:p2','p-3','p_4','p5','p6'],**options)
                before=deepcopy(row)
                out=prematch_context([row],fixture=fixture,cutoff_utc=NOW,registry=self.registry,registry_pin=self.pin)
                self.assertEqual(out['payload']['rosters']['H']['payload']['starting_five'],row['payload']['claims']['starting_five'])
                self.assertEqual(row,before)

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

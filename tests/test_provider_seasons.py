"""Catalog-bound European provider seasons; no private keys or live API calls."""
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from urllib.parse import urlsplit,parse_qs

from core.team_identity import digest
from hybrid_engine.provider_seasons import select_season
from hybrid_engine.provider_access import ProviderAccess
from hybrid_engine.provider_bridge import ProviderBridge,render
from tests.test_season_archive_audit import NOW

SNAP=dict(league='EUROCUP',season='2026/2027',fixture_id='SYNTHETIC_EUROCUP',
          prediction_generated_at_utc=NOW-60,fixture_start_utc=NOW+4*3600,
          home=dict(official_name='Synthetic Home'),away=dict(official_name='Synthetic Away'))


def row(value='2026-2027',**extra):return dict(season=value,**extra)


class ProviderSeasonTests(TestCase):
    def select(self,rows):return select_season(dict(seasons=rows),SNAP)

    def test_exact_two_year_token_is_returned_without_reformatting(self):
        for token in ('2026-2027','2026/2027'):
            with self.subTest(token=token):
                r=self.select([row(token)]);self.assertEqual(r['status'],'VERIFIED_PROVIDER_SEASON')
                self.assertEqual(r['season_value'],token)

    def test_integer_year_requires_explicit_matching_date_bounds(self):
        r=self.select([row(2026,start='2026-09-01',end='2027-06-30')])
        self.assertEqual(r['season_value'],'2026')
        self.assertEqual(self.select([row(2026)])['status'],'REQUESTED_SEASON_NOT_LISTED')
        self.assertEqual(self.select([row(2023,start='2026-09-01',end='2027-06-30')])['status'],'REQUESTED_SEASON_NOT_LISTED')

    def test_end_year_label_can_only_be_selected_with_source_dates(self):
        r=self.select([row(2027,start='2026-09-01',end='2027-06-30')])
        self.assertEqual(r['season_value'],'2027')
        self.assertEqual(self.select([row(2027)])['status'],'REQUESTED_SEASON_NOT_LISTED')

    def test_old_seasons_are_not_used_as_an_account_workaround(self):
        r=self.select([row('2023-2024'),row('2024-2025')])
        self.assertEqual(r['status'],'REQUESTED_SEASON_NOT_LISTED');self.assertIsNone(r['season_value'])
        self.assertEqual(r['available_seasons'],['2023-2024','2024-2025'])

    def test_missing_and_oversized_catalogs_are_explicit(self):
        self.assertEqual(select_season({},SNAP)['status'],'SEASON_CATALOG_MISSING')
        self.assertEqual(self.select([row()]*129)['status'],'SEASON_CATALOG_BUDGET')

    def test_conflicting_current_labels_are_not_resolved_by_first_match(self):
        self.assertEqual(self.select([row('2026-2027'),row('2026/2027')])['status'],'AMBIGUOUS_PROVIDER_SEASON')

    def test_fixture_outside_declared_season_dates_is_refused(self):
        r=self.select([row(start='2026-12-01',end='2027-06-30')])
        self.assertEqual(r['status'],'REQUESTED_SEASON_NOT_LISTED')

    def test_invalid_or_nonconsecutive_season_never_becomes_a_query(self):
        for season in ('2026/2028','2026','not-a-season'):
            with self.subTest(season=season),self.assertRaises(ValueError):
                select_season(dict(seasons=[row()]),dict(SNAP,season=season))
        self.assertEqual(self.select([row(True),row('2026-2027',start='invalid',end='2027-06-30')])['status'],'REQUESTED_SEASON_NOT_LISTED')


class ProviderSeasonQueryTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.calls=[]
        self.seasons=[row(2026,start='2026-09-01',end='2027-06-30')];self.error=False
        timer=patch('time.time',return_value=NOW);timer.start();self.addCleanup(timer.stop)
        self.access=ProviderAccess({'API_BASKETBALL':'SYNTHETIC_ONLY'},getter=self.getter,clock=lambda:NOW)
        self.bridge=ProviderBridge(self.access,Path(self.tmp.name)/'provider',clock=lambda:NOW)

    def getter(self,provider,url,key,timeout):
        self.calls.append(url);u=urlsplit(url)
        if u.path=='/leagues':document=dict(errors=[],response=[dict(id=42,name='Eurocup',seasons=self.seasons)])
        else:document=dict(errors={'plan':'Free plan cannot access this season'} if self.error else [],response=[])
        return dict(provider=provider,status='DOCUMENT_RECEIVED',http_status=200,source_url=url,
                    document=document,document_sha256=digest(document),observed_at_utc=NOW,ingested_at_utc=NOW)

    def test_game_query_uses_the_catalog_value_and_exposes_its_proof(self):
        r=self.bridge.collect(SNAP)['providers']['API_BASKETBALL']
        url=next(u for u in self.calls if '/games?' in u)
        self.assertEqual(parse_qs(urlsplit(url).query)['season'],['2026'])
        self.assertEqual(r['requested_season'],'2026');self.assertEqual(r['season_selection']['status'],'VERIFIED_PROVIDER_SEASON')
        self.assertEqual(len(r['season_selection']['catalog_source_pin']),64)

    def test_missing_current_season_never_calls_games_or_changes_forecast(self):
        self.seasons=[row('2023-2024')];before=deepcopy(SNAP)
        r=self.bridge.collect(SNAP);self.assertEqual(r['providers']['API_BASKETBALL']['status'],'REQUESTED_SEASON_NOT_LISTED')
        self.assertFalse(any('/games?' in u for u in self.calls));self.assertEqual(SNAP,before);self.assertFalse(r['forecast_changed'])

    def test_real_plan_error_retains_verified_season_and_existing_cooldown(self):
        self.error=True;first=self.bridge.collect(SNAP);count=len(self.calls);second=self.bridge.collect(SNAP)
        self.assertEqual(count,len(self.calls));r=second['providers']['API_BASKETBALL']
        self.assertEqual(r['status'],'PROVIDER_REPORTED_ERROR');self.assertEqual(r['requested_season'],'2026')
        self.assertIn('kataloğundan doğrulandı',render(second));self.assertNotIn('SYNTHETIC_ONLY',render(first))

    def test_missing_odds_key_reports_catalog_codes_without_claiming_total_provider_absence(self):
        def getter(provider,url,key,timeout):
            doc=[dict(key='basketball_nba',title='NBA',active=True)]
            return dict(provider=provider,status='DOCUMENT_RECEIVED',http_status=200,source_url=url,
                document=doc,document_sha256=digest(doc),observed_at_utc=NOW,ingested_at_utc=NOW)
        bridge=ProviderBridge(ProviderAccess({'THE_ODDS_API':'SYNTHETIC_ONLY'},getter=getter,clock=lambda:NOW),Path(self.tmp.name)/'odds',clock=lambda:NOW)
        r=bridge.collect(SNAP)['providers']['THE_ODDS_API']
        self.assertEqual(r['status'],'LEAGUE_NOT_AVAILABLE_FROM_PROVIDER')
        self.assertEqual(r['expected_sport_key'],'basketball_eurocup')
        self.assertEqual(r['active_basketball_sports'],[dict(key='basketball_nba',title='NBA')])
        self.assertIn('Beklenen lig kodu',render(dict(status='CURRENT_OBSERVATIONS_NOT_HISTORICAL_FORECAST_INPUTS',
            configuration={'THE_ODDS_API':'CONFIGURED_NOT_TESTED'},providers={'THE_ODDS_API':r})))

    def test_malformed_odds_catalog_is_not_misreported_as_no_league_coverage(self):
        def getter(provider,url,key,timeout):
            doc={'unexpected':'catalog'}
            return dict(provider=provider,status='DOCUMENT_RECEIVED',http_status=200,source_url=url,
                document=doc,document_sha256=digest(doc),observed_at_utc=NOW,ingested_at_utc=NOW)
        bridge=ProviderBridge(ProviderAccess({'THE_ODDS_API':'SYNTHETIC_ONLY'},getter=getter,clock=lambda:NOW),Path(self.tmp.name)/'bad-odds',clock=lambda:NOW)
        r=bridge.collect(SNAP)['providers']['THE_ODDS_API']
        self.assertEqual(r['status'],'INVALID_PROVIDER_SCHEMA')

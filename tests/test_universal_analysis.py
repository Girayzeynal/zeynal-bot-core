"""End-to-end fake-provider tests; not real forecasts or calibration samples."""
from copy import deepcopy
from datetime import datetime,timezone
from types import SimpleNamespace
import time
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock,Mock,patch
import importlib
import os

from core.league_identity import league_catalog
from core.team_identity import digest
from providers.season_participants import SeasonParticipantProvider
from universal_analysis import UniversalAnalyzeService,render_preflight
from season_archive_inventory import archive_catalog,validate_catalog
from tests.test_season_archive_audit import NOW,euro,nba
from tests.test_team_identity import documents


def games(competition='E',day='2026-11-11'):
    rows=[]
    for n,(home,away) in enumerate([('PRS','ULK'),('PAR','BAS')]):
        for i in range(8):
            g=euro();g['identifier']=f'{competition}2026_{n*8+i+1}';g['gameCode']=n*8+i+1
            g['season'].update(code=competition+'2026',competitionCode=competition)
            g['local']['club']['code']=home;g['road']['club']['code']=away
            g['played']=i>0
            g['utcDate']=day+'T20:00:00Z' if i==0 else f'2026-11-{10-i:02d}T18:00:00Z'
            if i==0:
                for s in ('local','road'):g[s]['score']=0;g[s]['partials']={**{f'partials{q}':0 for q in range(1,5)},'extraPeriods':{}}
            rows.append(g)
    return {'data':rows,'total':len(rows)}


def response(provider,url,raw):
    return dict(provider=provider,source_url=url,http_status=200,status='DOCUMENT_RECEIVED',document=raw,
        document_sha256=digest(raw),observed_at_utc=NOW-2,ingested_at_utc=NOW-1)


def fetcher(league='EUROLEAGUE',fixture_day='2026-11-11',fixture_error=None):
    d=documents(league)
    def fetch(provider,url):
        for r in d.values():
            if r['source_url']==url:return deepcopy(r)
        if fixture_error:return dict(status=fixture_error)
        if league=='NBA':
            event=nba();event['date']='2026-11-11T20:00:00Z'
            status={'type':dict(state='pre',completed=False,name='STATUS_SCHEDULED')}
            event['status']=deepcopy(status);event['competitions'][0]['status']=status
            return response(provider,url,{'events':[]} if 'dates=20261110' in url else {'events':[event]})
        return response(provider,url,games('U' if league=='EUROCUP' else 'E',fixture_day))
    return Mock(side_effect=fetch)


class UniversalAnalyzeTests(IsolatedAsyncioTestCase):
    def setUp(self):
        timer=patch('time.time',return_value=NOW);timer.start();self.addCleanup(timer.stop)

    async def test_both_reported_commands_resolve_all_teams_without_espn_and_no_fake_pace(self):
        for home,away in [('Paris Basketball','Fenerbahce Beko'),('Partizan Belgrade','Baskonia')]:
            fetch=fetcher();s=UniversalAnalyzeService(fetcher=fetch)
            out=await s.preflight('EUROLEAGUE','2026-11-11',home,away)
            with self.subTest(home=home):
                self.assertEqual(out['stage'],'MODEL_INPUTS');self.assertEqual(out['status'],'ABSTAIN')
                self.assertEqual(out['provider'],'EUROLEAGUE_LIVE')
                self.assertEqual(out['history']['home']['n_games'],7)
                self.assertIsNone(out['history']['home']['pace']);self.assertIsNone(out['prediction'])
                self.assertEqual(out['prospective_records_created'],0)
                self.assertTrue(all(c.args[0]=='EUROLEAGUE_LIVE' for c in fetch.call_args_list))

    async def test_wrong_match_date_is_fixture_failure_not_missing_history(self):
        s=UniversalAnalyzeService(fetcher=fetcher(fixture_day='2026-11-12'))
        out=await s.preflight('EL','2026-11-11','Paris Basketball','Fenerbahçe Beko')
        self.assertEqual(out['stage'],'FIXTURE');self.assertEqual(out['reason'],'FIXTURE_NOT_UNIQUELY_VERIFIED')
        self.assertNotIn('history',out);self.assertNotIn('ESPN',render_preflight(out))

    async def test_all_unconfigured_leagues_abstain_before_provider_or_model_calls(self):
        fetch=Mock(side_effect=AssertionError('WRONG PROVIDER'))
        for code,spec in league_catalog().items():
            if spec.provider:continue
            out=await UniversalAnalyzeService(fetcher=fetch).preflight(code,'2026-11-11','Any Team','Other Team')
            with self.subTest(league=code):
                self.assertEqual(out['stage'],'PROVIDER');self.assertIsNone(out['participant_count'])
                self.assertEqual(out['reason'],'PARTICIPANT_ADAPTER_NOT_CONFIGURED')
        fetch.assert_not_called()

    async def test_eurocup_is_a_distinct_competition_and_no_profile_is_invented(self):
        fetch=fetcher('EUROCUP');out=await UniversalAnalyzeService(fetcher=fetch).preflight('EuroCup','2026-11-11','Partizan Belgrade','Baskonia')
        self.assertEqual(out['stage'],'MODEL_INPUTS');self.assertEqual(out['league'],'EUROCUP')
        self.assertTrue(all('/competitions/U/' in c.args[1] for c in fetch.call_args_list))
        self.assertIsNone(out['prediction'])

    async def test_nba_all_directory_names_and_abbreviations_keep_correct_fixture_ids(self):
        out=await UniversalAnalyzeService(fetcher=fetcher('NBA')).preflight('NBA','2026-11-11','SH','Synthetic Bears')
        self.assertEqual(out['status'],'VERIFIED_NBA_FIXTURE')
        self.assertEqual(out['home']['provider_id'],'1');self.assertEqual(out['fixture']['provider_fixture_ids'],['401000123'])

    async def test_unknown_alias_and_same_team_have_identity_not_source_missing_status(self):
        s=UniversalAnalyzeService(fetcher=fetcher())
        for home,away,reason in [('Paris Basketbal','Baskonia','TEAM_ALIAS_NOT_REGISTERED'),('Baskonia','Saski Baskonia','SAME_TEAM_BOTH_SIDES')]:
            out=await s.preflight('EUROLEAGUE','2026-11-11',home,away)
            with self.subTest(home=home):
                self.assertEqual(out['stage'],'TEAM_IDENTITY');self.assertEqual(out['reason'],reason)

    async def test_access_error_and_network_error_are_separate_from_no_team_data(self):
        s=UniversalAnalyzeService(fetcher=fetcher(fixture_error='SOURCE_ACCESS_DENIED'))
        out=await s.preflight('EL','2026-11-11','Paris Basketball','Fenerbahce Beko')
        self.assertEqual(out['stage'],'FIXTURE');self.assertEqual(out['reason'],'SOURCE_ACCESS_DENIED')
        s=UniversalAnalyzeService(fetcher=Mock(side_effect=OSError('offline')))
        out=await s.preflight('EL','2026-11-11','Paris Basketball','Baskonia')
        self.assertEqual(out['stage'],'SEASON_PARTICIPANTS');self.assertEqual(out['reason'],'SOURCE_NETWORK_ERROR')

    async def test_started_or_historical_match_never_reaches_model_or_archive(self):
        source=fetcher()
        def fresh_fetch(provider,url):
            r=source(provider,url)
            r.update(observed_at_utc=int(time.time())-2,ingested_at_utc=int(time.time())-1)
            return r
        s=UniversalAnalyzeService(fetcher=fresh_fetch)
        with patch('time.time',return_value=NOW+4*3600+60):
            out=await s.preflight('EL','2026-11-11','Paris Basketball','Fenerbahce Beko')
        self.assertEqual(out['reason'],'FIXTURE_ALREADY_STARTED_OR_COMPLETED')
        out=await s.preflight('EL','2026-11-10','Paris Basketball','Fenerbahce Beko')
        self.assertEqual(out['reason'],'HISTORICAL_PIT_SNAPSHOT_REQUIRED')
        self.assertEqual(out['prospective_records_created'],0)

    async def test_stale_participant_and_fixture_receipts_stop_at_the_correct_stage(self):
        for stale_stage in ('SEASON_PARTICIPANTS','FIXTURE'):
            source=fetcher()
            def fetch(provider,url):
                r=source(provider,url)
                if (url.endswith('/games'))==(stale_stage=='FIXTURE'):
                    r.update(observed_at_utc=NOW-301,ingested_at_utc=NOW-1)
                return r
            out=await UniversalAnalyzeService(fetcher=fetch).preflight('EL','2026-11-11','Paris Basketball','Fenerbahce Beko')
            with self.subTest(stage=stale_stage):
                self.assertEqual(out['stage'],stale_stage)
                self.assertEqual(out['reason'],'SOURCE_STALE_FOR_CURRENT_ANALYSIS')
                self.assertNotIn('history',out)

    async def test_fixture_freshness_boundary_and_future_clock_are_fail_closed(self):
        for age,expected in [(300,'VERIFIED_PACE_AND_PROSPECTIVE_MODEL_ARCHIVE_NOT_CONFIGURED'),
                             (301,'SOURCE_STALE_FOR_CURRENT_ANALYSIS'),(-1,'SOURCE_CLOCK_INVALID')]:
            source=fetcher()
            def fetch(provider,url):
                r=source(provider,url)
                if url.endswith('/games'):
                    r.update(observed_at_utc=NOW-age,ingested_at_utc=max(NOW-age,NOW-1))
                return r
            out=await UniversalAnalyzeService(fetcher=fetch).preflight('EL','2026-11-11','Paris Basketball','Fenerbahce Beko')
            with self.subTest(age=age):
                self.assertEqual(out['reason'],expected)
                self.assertIsNone(out['prediction'])

    async def test_fixture_team_not_in_participant_list_is_source_conflict(self):
        base=fetcher()
        def fetch(provider,url):
            r=base(provider,url)
            if url.endswith('/games'):
                r['document']['data'][0]['road']['club']['code']='UNKNOWN';r['document_sha256']=digest(r['document'])
            return r
        out=await UniversalAnalyzeService(fetcher=fetch).preflight('EL','2026-11-11','Paris Basketball','Fenerbahce Beko')
        self.assertEqual(out['reason'],'PARTICIPANT_FIXTURE_ID_CONFLICT')

    async def test_telegram_non_nba_route_never_bootstraps_espn_or_executes_models(self):
        with patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN':'SYNTHETIC_ONLY','API_SPORTS_KEY':'SYNTHETIC_ONLY'}):
            app=importlib.import_module('main')
        reply=AsyncMock();baseline=Mock();engine=Mock();service=UniversalAnalyzeService(fetcher=fetcher())
        ctx=SimpleNamespace(application=SimpleNamespace(bot_data={'team_identity_service':service,'baseline_bootstrapper':baseline,'faz13':engine}))
        for text in ('/analyze EUROLEAGUE 2026-11-11 Paris Basketball vs Fenerbahce Beko',
                     '/analyze EUROLEAGUE 2026-11-11 Partizan Belgrade vs Baskonia'):
            update=SimpleNamespace(message=SimpleNamespace(text=text,reply_text=reply))
            await app.analyze_command(update,ctx)
        self.assertEqual(reply.await_count,2);baseline.ensure_async.assert_not_called();engine.run_prematch.assert_not_called()
        self.assertTrue(all('EUROLEAGUE_LIVE' in c.args[0] for c in reply.call_args_list))

    async def test_legacy_euro_catalog_pins_still_replay_and_cup_is_not_cast_to_league(self):
        old=archive_catalog(games(),provider='EUROLEAGUE_LIVE',observed_at_utc=NOW-2,ingested_at_utc=NOW-1)
        self.assertNotIn('competition_code',old['payload'])
        self.assertEqual(validate_catalog(old,trusted_sha256=old['sha256']),old['payload'])
        with self.assertRaises(ValueError):archive_catalog(games('U'),provider='EUROLEAGUE_LIVE',observed_at_utc=NOW-2,ingested_at_utc=NOW-1)
        cup=archive_catalog(games('U'),provider='EUROLEAGUE_LIVE',competition_code='U',observed_at_utc=NOW-2,ingested_at_utc=NOW-1)
        self.assertEqual(validate_catalog(cup,trusted_sha256=cup['sha256'])['league'],'EuroCup')

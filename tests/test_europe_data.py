"""Synthetic European provider/source integration; never external Telegram E2E."""
import asyncio
import hashlib
import json
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit,parse_qs
from unittest import IsolatedAsyncioTestCase,TestCase
from unittest.mock import patch,Mock
from core.team_identity import digest
from hybrid_engine.europe_data import EuropeanDataReview,context,article_rows
from hybrid_engine.europe_models import prepare,season_url
from hybrid_engine.europe_live import EuropeanService
from hybrid_engine.europe_premium_ui import projection
from hybrid_engine.provider_access import ProviderAccess
from hybrid_engine.provider_bridge import ProviderBridge,SPORTS
from hybrid_engine.europe_source_probe import fetch,_COOLDOWN
from tests.test_europe_integration import Source
from tests.test_season_archive_audit import NOW


class EuropeanSourceTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.now=NOW;self.timer=patch('time.time',side_effect=lambda:self.now);self.timer.start();self.addCleanup(self.timer.stop)
        self.services={};self.contexts={};self.calls=[];self.available=True;self.offset=0;self.bad_team=False
        for code in ('EUROLEAGUE','EUROCUP'):
            source=Source(code,lambda:self.now);prepare(self.root/'models',code,2026,source('EUROLEAGUE_LIVE',season_url(code,2026)))
            service=EuropeanService(code,self.root/code,self.root/'models',source);self.services[code]=service
            report=await service.analyze(code,'2026-11-11','Paris Basketball','Fenerbahce Beko')
            self.contexts[code]=context(projection(report,code,service=service),code)
        self.now+=30;self.active='EUROLEAGUE'
        self.provider_home_alias=None;self.provider_away_alias=None
        self.access=ProviderAccess({'THE_ODDS_API':'SYNTHETIC_ODDS','API_BASKETBALL':'SYNTHETIC_STATS'},getter=self.getter,clock=lambda:self.now)
        bridge=ProviderBridge(self.access,self.root/'providers',clock=lambda:self.now)
        self.reviewer=EuropeanDataReview(self.services,bridge,self.root/'current',getter=self.news,clock=lambda:self.now)

    def getter(self,provider,url,key,timeout):
        self.calls.append((provider,url));u=urlsplit(url);qs=parse_qs(u.query);c=self.contexts[self.active]
        def iso(at):return datetime.fromtimestamp(at,timezone.utc).isoformat()
        event=dict(id='europe_native',sport_key=SPORTS[self.active],home_team=c['home']['official_name'],
                   away_team=c['away']['official_name'],commence_time=iso(c['fixture_start_utc']+self.offset))
        if self.provider_home_alias:event['home_team']=self.provider_home_alias
        if self.provider_away_alias:event['away_team']=self.provider_away_alias
        if self.bad_team:event['away_team']='Another Team'
        if provider=='THE_ODDS_API':
            if u.path=='/v4/sports/':document=[dict(key=k,active=True,title=k) for k in SPORTS.values()] if self.available else []
            elif u.path.endswith('/events'):document=[event]
            else:
                event['bookmakers']=[dict(key='native_book',title='Native Book',last_update=iso(self.now-1),
                    markets=[dict(key='totals',last_update=iso(self.now-1),outcomes=[
                        dict(name='Over',point=170.5,price=1.91),dict(name='Under',point=170.5,price=1.91)])])]
                document=event
        else:
            season=c['season'].replace('/','-')
            if u.path=='/leagues':data=[dict(id=42,name='Euroleague' if self.active=='EUROLEAGUE' else 'Eurocup',
                seasons=[dict(season=season,start='2026-09-01',end='2027-07-01')])]
            elif u.path=='/games':data=[dict(id=12,date=iso(c['fixture_start_utc']),league=dict(id=42,season=season),
                status=dict(short='NS'),teams={s:dict(id=101+i,name=c[s]['official_name']) for i,s in enumerate(('home','away'))})]
            else:data=dict(team=dict(id=int(qs['team'][0])),league=dict(id=42,season=season))
            document=dict(errors=[],response=data)
        self.assertNotIn(key,url)
        return dict(status='DOCUMENT_RECEIVED',provider=provider,source_url=url,http_status=200,
            observed_at_utc=self.now,ingested_at_utc=self.now,document=document,document_sha256=digest(document))

    def news(self,url,league,deadline):
        return dict(status='SOURCE_HTTP_ERROR',http_status=429,url=url,retry_after_seconds=300)

    def originals(self):
        return {str(p.relative_to(self.root)):p.read_bytes() for code in self.services for p in (self.root/code).rglob('*.json')}

    async def test_both_leagues_fetch_actual_native_shape_quotes_and_replay_original_sample_sha(self):
        for code in self.services:
            self.active=code;before=self.originals()
            r=self.reviewer.review(self.contexts[code],'market')
            self.assertEqual(r['details']['admitted_observations'],1,r['html'])
            self.assertIn('GÜNCEL PİYASA DEĞERLENDİRMESİ',r['html']);self.assertIn('Native Book',r['html'])
            self.assertIn('170.5',r['html']);self.assertIn('NOT_CALIBRATED',r['html'])
            self.assertFalse(r['forecast_changed']);self.assertFalse(r['eligible_for_original_forecast_metrics'])
            self.assertEqual(r['source_context']['current_team_identity']['status'],'OFFICIAL_CURRENT_TEAM_CATALOG_VERIFIED')
            self.assertEqual(before,self.originals())
            self.assertTrue(all('/injuries' not in u for _,u in self.calls))

    async def test_unavailable_eurocup_catalog_does_not_call_an_invented_event_endpoint(self):
        self.active='EUROCUP';self.available=False
        r=self.reviewer.review(self.contexts['EUROCUP'],'market')
        state=r['details']['provider_report']['providers']['THE_ODDS_API']['status']
        self.assertEqual(state,'LEAGUE_NOT_AVAILABLE_FROM_PROVIDER')
        self.assertFalse(any('/events' in url for p,url in self.calls if p=='THE_ODDS_API'))
        self.assertEqual(r['details']['admitted_observations'],0)

    async def test_current_price_clock_is_separate_and_repeat_is_cached(self):
        ctx=self.contexts['EUROLEAGUE'];r=self.reviewer.review(ctx,'market');n=len(self.calls)
        self.assertGreater(r['observed_at_utc'],ctx['prediction_generated_at_utc'])
        self.assertEqual(r['details']['quote_valid_until_utc'],min(self.now-1+300,ctx['fixture_start_utc']))
        self.assertGreater(r['details']['quote_valid_until_utc'],r['valid_until_utc'])
        self.assertIn('Temel sorgu: periyot',r['html'])
        self.assertIn('FULL/TOTAL',r['html'])
        self.assertEqual(self.reviewer.review(ctx,'market'),r);self.assertEqual(len(self.calls),n)

    async def test_current_official_aliases_reach_native_quote_admission_without_forecast_changes(self):
        ctx=self.contexts['EUROLEAGUE'];before=deepcopy(ctx);originals=self.originals()
        self.provider_home_alias='Paris';self.provider_away_alias='Fenerbahce'
        r=self.reviewer.review(ctx,'market');current=r['source_context']
        self.assertEqual(r['details']['admitted_observations'],1,r['html'])
        self.assertEqual(ctx,before);self.assertEqual(originals,self.originals())
        self.assertEqual(current['input_clocks'],ctx['input_clocks'])
        self.assertEqual(current['prediction_generated_at_utc'],ctx['prediction_generated_at_utc'])
        self.assertGreater(current['european_team_catalog']['documents']['clubs']['ingested_at_utc'],ctx['prediction_generated_at_utc'])
        binding=r['details']['provider_report']['providers']['THE_ODDS_API']['event_clock_binding']['payload']
        self.assertEqual(binding['mode'],'OFFICIAL_TEAM_ALIASES_EXACT_START')
        self.assertIn('ilk tahmin girdisi değildir',r['html'])

    async def test_failed_current_catalog_never_guesses_provider_alias(self):
        ctx=self.contexts['EUROLEAGUE'];self.services['EUROLEAGUE'].fetcher.offline=True
        self.provider_home_alias='Paris';self.provider_away_alias='Fenerbahce'
        r=self.reviewer.review(ctx,'market')
        self.assertEqual(r['source_context']['current_team_identity']['status'],'CURRENT_TEAM_CATALOG_UNAVAILABLE_EXACT_NAMES_ONLY')
        self.assertEqual(r['details']['admitted_observations'],0)
        self.assertIn('yalnız aynı takım adları',r['html'])

    async def test_european_ten_minute_offset_is_refused_instead_of_using_nba_offset_rule(self):
        self.offset=600;r=self.reviewer.review(self.contexts['EUROLEAGUE'],'market')
        self.assertEqual(r['details']['provider_report']['providers']['THE_ODDS_API']['status'],'EXACT_FIXTURE_MATCH_REQUIRED')
        self.assertEqual(r['details']['admitted_observations'],0)

    async def test_wrong_team_is_refused_and_original_context_cannot_be_retimed(self):
        self.bad_team=True;r=self.reviewer.review(self.contexts['EUROLEAGUE'],'market')
        self.assertEqual(r['details']['admitted_observations'],0)
        forged=deepcopy(self.contexts['EUROLEAGUE']);forged['prediction_generated_at_utc']+=1
        with self.assertRaisesRegex(ValueError,'CONTEXT_CONFLICT'):self.reviewer.review(forged,'roster')

    async def test_post_tipoff_makes_no_provider_or_official_source_calls(self):
        ctx=self.contexts['EUROLEAGUE'];self.now=ctx['fixture_start_utc']
        official_calls={k:len(s.fetcher.calls) for k,s in self.services.items()}
        self.reviewer.getter=Mock(side_effect=AssertionError('NO AFTER START FETCH'))
        for section in ('market','roster'):
            r=self.reviewer.review(ctx,section);self.assertEqual(r['status'],'POST_TIPOFF_NO_CURRENT_BACKFILL')
        self.assertEqual(self.calls,[]);self.reviewer.getter.assert_not_called()
        self.assertEqual(official_calls,{k:len(s.fetcher.calls) for k,s in self.services.items()})

    async def test_429_is_explicit_and_never_means_healthy_roster(self):
        r=self.reviewer.review(self.contexts['EUROLEAGUE'],'roster')
        self.assertIn('HTTP 429',r['html']);self.assertEqual(r['details']['verified_player_records'],[])
        self.assertIn('eksik oyuncu yok demek değildir',r['html']);self.assertEqual(len(r['details']['sources']),1)

    async def test_news_text_is_not_promoted_to_verified_player_or_lineup_data(self):
        ctx=self.contexts['EUROLEAGUE'];url='https://www.euroleaguebasketball.net/en/euroleague/news/injury-report-round-12/'
        date=datetime.fromtimestamp(self.now-30,timezone.utc).isoformat()
        body='<script type="application/ld+json">'+json.dumps(dict(**{'@type':'NewsArticle'},
            headline='Injury Report Round 12',datePublished=date,articleBody='<p>Paris Basketball: Player A is out.</p>'))+'</script>'
        receipt=dict(status='RECEIVED',url=url,body=body,body_sha256=hashlib.sha256(body.encode()).hexdigest(),
                     observed_at_utc=self.now,ingested_at_utc=self.now)
        rows=article_rows(receipt,ctx,self.now)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['status'],'OFFICIAL_NEWS_TEXT_NOT_VERIFIED_MATCH_AVAILABILITY')
        self.assertNotIn('player_id',rows[0]);self.assertIn('Player A',rows[0]['note'])
        bad=dict(receipt,body_sha256='0'*64)
        with self.assertRaises(ValueError):article_rows(bad,ctx,self.now)
        self.assertEqual(article_rows(receipt,ctx,self.now+3*86400),[])

    async def test_missing_credentials_are_reported_without_network_or_fake_data(self):
        self.reviewer.bridge.access=ProviderAccess({},getter=Mock(side_effect=AssertionError('NO KEY NO REQUEST')))
        official_calls={k:len(s.fetcher.calls) for k,s in self.services.items()}
        r=self.reviewer.review(self.contexts['EUROLEAGUE'],'market')
        self.assertEqual(r['details']['admitted_observations'],0)
        self.assertEqual(set(v['status'] for v in r['details']['provider_report']['providers'].values()),{'KEY_NOT_AVAILABLE_IN_TEST_PROCESS'})
        self.assertEqual(official_calls,{k:len(s.fetcher.calls) for k,s in self.services.items()})


class EuropeanCooldownTests(TestCase):
    def test_official_429_cooldown_is_shared_between_competitions(self):
        _COOLDOWN.clear();self.addCleanup(_COOLDOWN.clear)
        response=Mock();response.status_code=429;response.headers={'Retry-After':'120'}
        manager=Mock();manager.__enter__=Mock(return_value=response);manager.__exit__=Mock(return_value=False)
        with patch('requests.get',return_value=manager) as getter:
            import time
            deadline=time.monotonic()+10
            first=fetch('https://www.euroleaguebasketball.net/en/euroleague/injury-report/','EUROLEAGUE',deadline=deadline)
            second=fetch('https://www.euroleaguebasketball.net/en/eurocup/news/','EUROCUP',deadline=deadline)
        self.assertEqual(first['http_status'],429);self.assertEqual(second['status'],'SOURCE_COOLDOWN')
        self.assertEqual(getter.call_count,1)

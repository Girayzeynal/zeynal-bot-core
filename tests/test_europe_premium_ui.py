"""European presentation and real PTB callbacks with synthetic sources/Bot API.

Not external Telegram E2E. All original captures are immutable.
"""
import importlib
import os
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase,TestCase
from unittest.mock import AsyncMock,patch

from telegram import Update
from telegram.ext import Application,CommandHandler
from core.team_identity import digest
from hybrid_engine.frozen_archive import FrozenArchive
from hybrid_engine.europe_models import prepare,season_url
from hybrid_engine.europe_premium_ui import present,projection
from hybrid_engine.telegram_premium_ui import compact_summary,page_view
from hybrid_engine.test_bot import install_isolated_services
from tests.test_europe_integration import Source
from tests.test_phase91 import ten_game_ledger
from tests.test_current_roster_telegram import ReviewBotAPI
from tests.test_season_archive_audit import NOW

ROOT=Path(__file__).resolve().parents[1]


class EuropeanAPI(ReviewBotAPI):
    def __init__(self):
        super().__init__();self.markups=[]
    async def do_request(self,url,method,request_data=None,**kwargs):
        if url.endswith('/sendMessage'):self.markups.append(request_data.parameters.get('reply_markup'))
        return await super().do_request(url,method,request_data=request_data,**kwargs)


class EuropeanButtonTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        archive=FrozenArchive(ROOT/'docs/prospective/euroleague-20261112')
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.clock=NOW;self.timer=patch('time.time',side_effect=lambda:self.clock);self.timer.start();self.addCleanup(self.timer.stop)
        self.sources={c:Source(c,lambda:self.clock) for c in ('EUROLEAGUE','EUROCUP')}
        for code,source in self.sources.items():prepare(self.root/'europe/models',code,2026,source('EUROLEAGUE_LIVE',season_url(code,2026)))
        def fetch(provider,url):return self.sources['EUROCUP' if '/U/' in url else 'EUROLEAGUE'](provider,url)
        ledger,_=ten_game_ledger(self.root/'nba.sqlite',1)
        self.nba=SimpleNamespace(ledger=ledger,analyze=AsyncMock(return_value=dict(status='UNCHANGED_NBA_CONTROL',html='NBA original')))
        with patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN':'123456:SYNTHETIC_ONLY'}):self.main=importlib.import_module('main')
        self.api=EuropeanAPI();self.app=Application.builder().token('123456:SYNTHETIC_ONLY').request(self.api).build()
        install_isolated_services(self.app,archive,self.root/'isolated',chat_id=17,transport=fetch,nba_service=self.nba,europe_directory=self.root/'europe')
        self.app.add_handler(CommandHandler('analyze',self.main.analyze_command))
        await self.app.initialize();self.addAsyncCleanup(self.app.shutdown);self.seq=0

    def files(self):
        return {str(p.relative_to(self.root)):p.read_bytes() for p in (self.root/'europe').rglob('*.json')}

    async def open(self,code='EUROCUP'):
        return await self.app.bot_data['verified_analysis_service'].analyze(code,'2026-11-11','Paris Basketball','Fenerbahce Beko')

    async def click(self,token,section,page=0,chat=17):
        self.seq+=1
        update=Update.de_json(dict(update_id=self.seq,callback_query=dict(id=str(self.seq),chat_instance='synthetic',
            data=f'zui:{token}:{section}:{page}',**{'from':dict(id=23,is_bot=False,first_name='Synthetic')},
            message=dict(message_id=1,date=NOW,chat=dict(id=chat,type='private'),text='Summary'))),self.app.bot)
        await self.app.process_update(update)

    async def test_both_leagues_get_six_working_buttons_and_all_sections_without_resimulation(self):
        for code in ('EUROLEAGUE','EUROCUP'):
            report=await self.open(code);self.assertIn('reply_markup',report)
            self.assertIn(code+' ANALİZ',report['html']);self.assertIn('40 dk',report['html']);self.assertNotIn('NBA ANALİZ',report['html'])
            buttons=[b for row in report['reply_markup'].inline_keyboard for b in row]
            self.assertEqual(len(buttons),6);token=buttons[0].callback_data.split(':')[1]
            entry=self.app.bot_data['premium_reports'][token]
            before=self.files();calls=len(self.sources[code].calls)
            expected=dict(period='1Q',ranges='P50',market='Piyasa verisi doğrulanamadı',
                          audit='Tahmin SHA-256',roster='KADRO / SAKATLIK',summary=code+' ANALİZ')
            with patch('hybrid_engine.models.HierarchicalStrength.predict',side_effect=AssertionError('NO BUTTON INFERENCE')):
                for section,text in expected.items():
                    n=len(self.api.edits);await self.click(token,section)
                    self.assertEqual(len(self.api.edits),n+1);self.assertIn(text,self.api.edits[-1])
                    self.assertLessEqual(len(self.api.edits[-1].encode('utf-16-le'))//2,4096)
            self.assertEqual(calls,len(self.sources[code].calls));self.assertEqual(before,self.files())
            self.assertIsNone(entry['roster_context']);self.assertIn('NOT_CALIBRATED',entry['summary'])

    async def test_actual_analyze_handler_returns_keyboard_for_each_league(self):
        for code in ('EUROLEAGUE','EUROCUP'):
            command=f'/analyze {code} 2026-11-11 Paris Basketball vs Fenerbahce Beko'
            self.seq+=1
            update=Update.de_json(dict(update_id=self.seq,message=dict(message_id=self.seq,date=NOW,
                chat=dict(id=17,type='private'),**{'from':dict(id=23,is_bot=False,first_name='Synthetic')},
                text=command,entities=[dict(type='bot_command',offset=0,length=8)])),self.app.bot)
            await self.app.process_update(update)
            self.assertIn(code+' ANALİZ',self.api.sent[-1])
            self.assertIsNotNone(self.api.markups[-1]);self.assertIn('zui:',str(self.api.markups[-1]))
            self.assertTrue(any(e['league']==code for e in self.app.bot_data['premium_reports'].values()))

    async def test_forecast_repeat_and_post_tipoff_buttons_are_read_only(self):
        first=await self.open();before=self.files();self.clock=NOW+5*3600;self.sources['EUROCUP'].offline=True
        with patch('hybrid_engine.models.HierarchicalStrength.predict',side_effect=AssertionError('NO REPLAY INFERENCE')):
            # Full archived names give the existing inference service's offline replay path.
            service=self.app.bot_data['europe_services']['EUROCUP'];p=service.registry.independent_records()[0]['payload'];h,a=service.pair(p)
            report=await self.app.bot_data['verified_analysis_service'].analyze('EUROCUP','2026-11-11',h,a)
            self.assertFalse(report['new_record']);self.assertEqual(first['forecast_sha256'],report['forecast_sha256'])
            token=report['reply_markup'].inline_keyboard[0][0].callback_data.split(':')[1]
            await self.click(token,'market');self.assertIn('Maç başladı',self.api.edits[-1])
        self.assertEqual(before,self.files())

    async def test_cache_expiry_unauthorized_and_bad_page_have_explanatory_answers(self):
        report=await self.open();token=report['reply_markup'].inline_keyboard[0][0].callback_data.split(':')[1]
        await self.click(token,'audit',chat=99);self.assertEqual(self.api.edits,[])
        await self.click(token,'ranges',page=999);self.assertIn('Sayfa bulunamadı',self.api.answers[-1]['text'])
        del self.app.bot_data['premium_reports'][token]
        await self.click(token,'summary');self.assertIn('oturumu sona erdi',self.api.answers[-1]['text'])

    async def test_long_audit_pages_and_stored_prediction_binding(self):
        report=await self.open();token=report['reply_markup'].inline_keyboard[0][0].callback_data.split(':')[1]
        entry=self.app.bot_data['premium_reports'][token];before=self.files()
        from hybrid_engine.elite_render import split_blocks
        entry['sections']['audit']+='\n'+'\n'.join('Kaynak ayrıntısı '+str(i) for i in range(500))
        entry['section_pages']['audit']=split_blocks(entry['sections']['audit'].splitlines(),limit=3200)
        self.assertGreater(len(entry['section_pages']['audit']),1);await self.click(token,'audit',page=1)
        self.assertIn('Kaynak ayrıntısı',self.api.edits[-1]);self.assertEqual(before,self.files())
        self.assertEqual(entry['europe_forecast_sha256'],report['forecast_sha256'])

    async def test_corrupt_projection_binding_is_refused_and_presentation_error_keeps_plain_forecast(self):
        report=await self.open();service=self.app.bot_data['europe_services']['EUROCUP']
        bad=dict(report,forecast_sha256='0'*64)
        with self.assertRaisesRegex(ValueError,'PUBLICATION_PIN'):projection(bad,'EUROCUP',service=service)
        before=self.files()
        with patch('hybrid_engine.europe_premium_ui.present',side_effect=ValueError('synthetic')):
            r=await self.open()
        self.assertIn('EUROPE_UI_UNAVAILABLE',''.join(r['html_parts']));self.assertEqual(r['forecast_sha256'],report['forecast_sha256'])
        self.assertEqual(before,self.files())

    async def test_original_five_game_replay_gets_buttons_without_backfilled_clocks(self):
        service=self.app.bot_data['europe_services']['EUROLEAGUE'];record=next(iter(service.archive.records.values()))
        self.clock=NOW+8*86400;g=record['fixture']
        original={p:p.read_bytes() for p in service.archive.path.rglob('*') if p.is_file()}
        report=await self.app.bot_data['verified_analysis_service'].analyze('EUROLEAGUE',g['start_iso_utc'][:10],g['home_name'],g['away_name'])
        self.assertEqual(report['status'],'FROZEN_REPLAY_OK');self.assertIn('reply_markup',report)
        token=report['reply_markup'].inline_keyboard[0][0].callback_data.split(':')[1]
        with patch('hybrid_engine.models.HierarchicalStrength.predict',side_effect=AssertionError('NO BUTTON SIMULATION')):
            await self.click(token,'audit');self.assertIn('ayrı kaydedilmemiş',self.api.edits[-1])
            await self.click(token,'period');self.assertIn('1Q',self.api.edits[-1])
        self.assertTrue(all(p.read_bytes()==b for p,b in original.items()))

    async def test_nba_dispatch_output_is_unchanged(self):
        r=await self.app.bot_data['verified_analysis_service'].analyze('NBA','2026-11-11','A','B')
        self.assertEqual(r,dict(status='UNCHANGED_NBA_CONTROL',html='NBA original'))
        self.nba.analyze.assert_awaited_once()


class EuropeanTemplateTests(TestCase):
    def test_nba_default_template_still_has_48_minutes_and_europe_has_40(self):
        p=dict(home=100.,away=90.,total=190.,margin=10.)
        s=dict(prediction=p,home=dict(official_name='A'),away=dict(official_name='B'),fixture_start_utc=NOW+1000,
               prediction_generated_at_utc=NOW)
        self.assertIn('NBA ANALİZ',compact_summary(s,None,replayed=True))
        self.assertIn('48 dk',compact_summary(s,None,replayed=True))
        self.assertIn('40 dk',compact_summary(s,None,replayed=True,league='EUROLEAGUE'))
        with self.assertRaises(ValueError):compact_summary(s,None,replayed=True,league='UNKNOWN')

    def test_manual_market_evidence_is_preserved_and_not_misrepresented_as_live(self):
        from hybrid_engine.europe_premium_ui import market_view
        text=market_view(dict(html_parts=['<b>EUROLEAGUE | MANUEL PİYASA GÖZLEMİ</b>\nStored line 170.5']))
        self.assertIn('Stored line 170.5',text);self.assertIn('Yeniden sorgulanmadı',text)

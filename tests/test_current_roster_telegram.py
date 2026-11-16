"""PTB callback integration with manufactured sources and in-memory Bot API."""
from copy import deepcopy
import importlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from telegram import Update
from telegram.ext import Application
from core.team_identity import digest
from hybrid_engine.current_roster import CurrentRosterReview, context_for
from hybrid_engine.frozen_archive import FrozenArchive
from hybrid_engine.test_bot import install_isolated_services
from tests import test_analyze_input_guard as input_tests
from tests import test_current_roster as fixtures


class ReviewBotAPI(input_tests.BotAPIDouble):
    def __init__(self):
        super().__init__(); self.edits=[]; self.answers=[]

    async def do_request(self,url,method,request_data=None,**kwargs):
        name=url.rsplit('/',1)[-1]
        if name=='editMessageText':
            text=request_data.parameters['text']; self.edits.append(text)
            result=dict(message_id=1,date=fixtures.NOW,chat=dict(id=17,type='private'),text=text)
        elif name=='answerCallbackQuery':
            self.answers.append(request_data.parameters); result=True
        else:
            return await super().do_request(url,method,request_data=request_data,**kwargs)
        return 200,json.dumps(dict(ok=True,result=result)).encode()


class CurrentRosterTelegramTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        with patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN':'123456:SYNTHETIC_ONLY'}):
            importlib.import_module('main')
        self.api=ReviewBotAPI()
        self.app=Application.builder().token('123456:SYNTHETIC_ONLY').request(self.api).build()
        root=Path(__file__).resolve().parents[1]
        self.archive=root/'docs/prospective/euroleague-20261112'
        self.archive_before={p:p.read_bytes() for p in self.archive.rglob('*') if p.is_file()}
        install_isolated_services(self.app,FrozenArchive(self.archive),self.tmp.name,chat_id=17)
        self.source=fixtures.FixtureSources()
        self.reviewer=CurrentRosterReview(Path(self.tmp.name)/'current-roster', getter=self.source,
            extractor=lambda path,deadline:fixtures.extraction(),clock=lambda:self.source.now)
        self.app.bot_data['current_roster_review']=self.reviewer
        self.snapshot=fixtures.snapshot(); self.before=deepcopy(self.snapshot)
        self.entry=dict(summary='FROZEN SCORE 100–90',sections=dict(roster='ORIGINAL EVIDENCE'),
            section_pages=dict(roster=['ORIGINAL EVIDENCE']),chat_id=17,tipoff_utc=fixtures.START,
            original_roster_html='İLK TAHMİN ANINDAKİ KADRO KANITI\nORIGINAL EVIDENCE',
            roster_context=context_for(self.snapshot))
        self.app.bot_data['premium_reports']={'abcdef123456':self.entry}
        await self.app.initialize(); self.addAsyncCleanup(self.app.shutdown)

    async def click(self,section='roster',page=0,chat=17,number=1):
        callback=Update.de_json(dict(update_id=number,callback_query=dict(id='roster-'+str(number),chat_instance='synthetic',
            data=f'zui:abcdef123456:{section}:{page}',**{'from':dict(id=23,is_bot=False,first_name='Synthetic')},
            message=dict(message_id=1,date=fixtures.NOW,chat=dict(id=chat,type='private'),text='Frozen summary'))),self.app.bot)
        with patch('time.time',return_value=self.source.now):
            await self.app.process_update(callback)

    async def test_roster_callback_fetches_current_sources_separately_and_never_changes_original_prediction(self):
        await self.click()
        text='\n'.join(self.app.bot_data['premium_reports']['abcdef123456']['section_pages']['roster'])
        self.assertIn('İLK TAHMİN ANINDAKİ',text); self.assertIn('GÜNCEL KADRO',text)
        self.assertIn('Test Player',text); self.assertIn('NOT_CALIBRATED',text)
        self.assertEqual(self.snapshot,self.before); self.assertEqual(self.api.sent,[])
        self.assertEqual(len(self.api.edits),1); self.assertTrue(self.api.answers)
        self.assertTrue(all(p.read_bytes()==b for p,b in self.archive_before.items()))
        self.assertEqual(len(self.source.calls),5)

    async def test_repeat_click_is_cached_and_pagination_does_not_repeat_source_queries(self):
        original=self.source.document['injuries'][1]['injuries'][0]
        self.source.document['injuries'][1]['injuries']=[
            dict(deepcopy(original),athlete=dict(id=str(300+i),displayName='Generated Player '+str(i))) for i in range(25)]
        await self.click(); count=len(self.source.calls)
        entry=self.app.bot_data['premium_reports']['abcdef123456']
        self.assertGreater(len(entry['section_pages']['roster']),1)
        await self.click(page=1,number=2)
        await self.click(number=3)
        self.assertEqual(len(self.source.calls),count)
        self.assertEqual(len(list(self.reviewer.directory.glob('review-*'))),1)

    async def test_unauthorized_callback_never_downloads_or_displays_roster(self):
        await self.click(chat=99)
        self.assertEqual(self.source.calls,[]); self.assertEqual(self.api.edits,[])

    async def test_tipoff_callback_makes_no_current_requests_or_prematch_backfill(self):
        self.source.now=fixtures.START
        await self.click()
        self.assertEqual(self.source.calls,[])
        self.assertIn('Maç başladı',self.api.edits[0]); self.assertNotIn('Test Player',self.api.edits[0])

    async def test_timeout_has_explanatory_response_and_no_fake_empty_roster_success(self):
        with patch.object(self.reviewer,'review',side_effect=TimeoutError('synthetic')):
            await self.click()
        self.assertIn('süre aşıldı',self.api.edits[0]); self.assertIn('yok demek değildir',self.api.edits[0])
        self.assertEqual(self.snapshot,self.before)

    async def test_cross_snapshot_review_is_rejected_before_display(self):
        bad=self.reviewer.review(self.entry['roster_context']); bad['original_snapshot_sha256']='0'*64
        with patch.object(self.reviewer,'review',return_value=bad):
            await self.click()
        self.assertIn('denetlenemedi',self.api.edits[0]); self.assertNotIn('Test Player',self.api.edits[0])
        self.assertEqual(digest(self.snapshot),digest(self.before))

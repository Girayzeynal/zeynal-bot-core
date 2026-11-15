"""Actual PTB dispatch over loopback; manufactured ten-game ledger, NOT real E2E."""
import asyncio
from copy import deepcopy
from datetime import datetime,timezone
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase,TestCase
from unittest.mock import AsyncMock,Mock,patch

from aiohttp import web
from telegram import Update
from telegram.error import BadRequest,Forbidden,RetryAfter
from telegram.ext import Application,ApplicationHandlerStop

from core.team_identity import digest
from hybrid_engine.archive_audit import audit_ledger
from hybrid_engine.frozen_archive import FrozenArchive
from hybrid_engine.predictions_command import PredictionsCommand,render_predictions,split_plain,stamp
from hybrid_engine.test_bot import install_isolated_services,AuditedRequest
from ledger_reports import LedgerReports
from live_analysis_ledger import LiveAnalysisLedger
from season_archive_inventory import archive_catalog
from telegram_delivery import DeliveryJournal
from tests.test_release_integration import live_payload
from tests.test_season_archive_audit import nba,NOW,START

ROOT=Path(__file__).resolve().parents[1]


def ten_game_ledger(path,count=10):
    ledger=LiveAnalysisLedger(path);games=[]
    for i in range(count):
        start=START if i==0 else NOW+i*86400
        e=nba(str(401000123+i));e['date']=datetime.fromtimestamp(start,timezone.utc).isoformat()
        if i:
            for status in (e['status']['type'],e['competitions'][0]['status']['type']):status.update(state='pre',completed=False,name='STATUS_SCHEDULED')
        with patch('time.time',return_value=NOW):
            catalog=archive_catalog({'events':[e]},provider='ESPN',season_start_year=2026,observed_at_utc=NOW-1,ingested_at_utc=NOW)
        g=catalog['payload']['fixtures'][0];games.append(g)
        at=min(start-100,NOW-100);p=live_payload(start)
        p.update(fixture_id=g['canonical_id'],provider_fixture_ids=g['provider_fixture_ids'],model_digest='a'*64,
            model_version='SYNTHETIC_PHASE91_ONLY',prediction_generated_at_utc=at-1,scope='REGULATION_ONLY',
            input_clocks=[dict(observed_at_utc=at-3,ingested_at_utc=at-2)])
        p['home']['official_name']='Synthetic Home '+str(i);p['away']['official_name']='Synthetic Away '+str(i)
        p['prediction'].update(quarters=[[27.5,25.]]*4,halves=[[55.,50.]]*2,winner=[.6,.1,.3])
        with patch('time.time',return_value=at):ledger.commit(p)
        if i==0:
            with patch('time.time',return_value=NOW):ledger.reconcile(catalog,trusted_sha256=catalog['sha256'])
    return ledger,games


class FormattingTests(TestCase):
    def test_unix_seconds_and_unknown_generation_are_distinct(self):
        self.assertEqual(stamp(1794765600),'15.11.2026 21:00:00 TSİ')
        self.assertIn('ayrı kaydedilmemiş',stamp(None))
        for value in ('2026-11-15T18:00:00Z',True,-1):
            with self.subTest(value=value),self.assertRaises(ValueError):stamp(value)

    def test_utf16_split_preserves_all_text_with_many_non_bmp_characters(self):
        value=('🏀'*3000)+'\nNBA'
        parts=list(split_plain(value));self.assertGreater(len(parts),1)
        self.assertEqual(''.join(parts),value)
        self.assertTrue(all(len(s.encode('utf-16-le'))//2<=3500 for s in parts))

    def test_ten_records_render_all_required_fields_and_do_not_mutate_database(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'nba.sqlite';ledger,_=ten_game_ledger(path);before=path.read_bytes()
            r=LedgerReports(path).read('NBA');parts=render_predictions(r);text=''.join(parts)
            self.assertIn('Maç: 10 | Tahmin: 10 | Sonuç bekleyen: 9',text)
            self.assertEqual(text.count('ESPN kimliği:'),10);self.assertEqual(text.count('/compare NBA '),10)
            self.assertIn('İlk üretim:',text);self.assertIn('İlk kalıcı arşiv:',text)
            self.assertIn('Toplam: 210.00',text);self.assertIn('115 – 109',text)
            self.assertIn('SYNTHETIC_PHASE91_ONLY',text);self.assertEqual(before,path.read_bytes())
            self.assertGreater(len(parts),1)
            self.assertEqual(r['groups'][0]['n'],1);d=r['groups'][0]['details']
            self.assertEqual(r['groups'][0]['team_mae'],7);self.assertAlmostEqual(r['groups'][0]['team_rmse'],math.sqrt(53))
            self.assertAlmostEqual(d['winner']['brier'],.26);self.assertAlmostEqual(d['winner']['log_loss'],-math.log(.6))
            self.assertEqual(d['period_totals']['1Q']['mae'],2.5)
            self.assertIsNone(d['confidence_index']);self.assertFalse(d['calibration_fit'])

    def test_pagination_is_explicit_and_no_records_are_silently_dropped(self):
        with TemporaryDirectory() as tmp:
            ledger,_=ten_game_ledger(Path(tmp)/'nba.sqlite',26);r=LedgerReports(ledger.path).read('NBA')
            a=''.join(render_predictions(r,1));b=''.join(render_predictions(r,2))
            self.assertEqual(a.count('ESPN kimliği:'),25);self.assertEqual(b.count('ESPN kimliği:'),1)
            self.assertIn('/predictions NBA 2',a);self.assertIn('Sayfa bulunamadı',''.join(render_predictions(r,3)))


class DispatchTests(IsolatedAsyncioTestCase):
    async def exercise(self,commands,*,live=True,chat=17,count=10):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);ledger,games=ten_game_ledger(root/'nba.sqlite',count);before=(root/'nba.sqlite').read_bytes()
            sent=[]
            async def api(request):
                name=request.path.rsplit('/',1)[-1]
                if name=='getMe':result=dict(id=123456,is_bot=True,first_name='Synthetic',username='zeynal_test_bot')
                elif name=='sendMessage':
                    p=dict(await request.post());sent.append(p['text']);result=dict(message_id=100+len(sent),date=int(time.time()),chat=dict(id=17,type='private'),text=p['text'])
                else:result=True
                return web.json_response(dict(ok=True,result=result))
            server=web.Application();server.router.add_route('*','/{path:.*}',api);runner=web.AppRunner(server);await runner.setup()
            site=web.TCPSite(runner,'127.0.0.1',0);await site.start();port=site._server.sockets[0].getsockname()[1]
            journal=DeliveryJournal(root/'isolated-delivery.sqlite')
            with patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN':'123456:SYNTHETIC_LOCAL_ONLY','API_SPORTS_KEY':'','ZEYNAL_HYBRID_NBA_RESEARCH':'0'}):
                main=importlib.import_module('main');engine=main.Faz23Engine
                class Local:
                    @staticmethod
                    def builder():return Application.builder().base_url(f'http://127.0.0.1:{port}/bot').request(AuditedRequest(journal))
                with patch.object(main,'Application',Local),patch.object(main,'Faz23Engine',lambda:engine(str(root/'faz23.sqlite'))):app=main.build_app()
            archive=FrozenArchive(ROOT/'docs/prospective/euroleague-20261112')
            installed,_=install_isolated_services(app,archive,root/'isolated',chat_id=17,nba_service=SimpleNamespace(ledger=ledger) if live else None)
            app.bot_data['nba_fixture_loader']=AsyncMock(return_value=[dict(id='401000124',home='Synthetic Home 1',away='Synthetic Away 1',start=datetime.fromtimestamp(NOW+86400,timezone.utc),status='Başlamadı')])
            groups=[g for g,hs in app.handlers.items() for h in hs if 'predictions' in getattr(h,'commands',[])]
            await app.initialize()
            try:
                for i,command in enumerate(commands):
                    update=Update.de_json(dict(update_id=i+1,message=dict(message_id=i+1,date=NOW,chat=dict(id=chat,type='private'),
                        **{'from':dict(id=23,is_bot=False,first_name='Synthetic input')},text=command,
                        entities=[dict(type='bot_command',offset=0,length=len(command.split()[0]))])),app.bot)
                    await app.process_update(update)
                self.assertEqual(before,(root/'nba.sqlite').read_bytes())
                events=installed.read();self.assertFalse(any(e.get('kind')=='HANDLER_ERROR' for e in events))
                return sent,events,groups
            finally:await app.shutdown();await runner.cleanup()

    async def test_actual_dispatch_ten_record_command_starts_and_sends(self):
        sent,events,groups=await self.exercise(['/predictions NBA'])
        self.assertEqual(groups,[-50]);self.assertIn('Maç: 10',''.join(sent))
        self.assertTrue(any(e['kind']=='PREDICTIONS_STARTED' for e in events))
        self.assertTrue(any(e['kind']=='PREDICTIONS_SENT' for e in events))
        self.assertTrue(all(len(s.encode('utf-16-le'))//2<=3500 for s in sent))

    async def test_requested_start_nba_predictions_accuracy_compare_sequence(self):
        sent,events,_=await self.exercise(['/start','/nba','/predictions NBA','/accuracy NBA','/compare NBA 401000123','/test nba'])
        text='\n'.join(sent)
        for expected in ('Zeynal Bot Core aktif','NBA |','KAYITLI NBA TAHMİNLERİ','MAE 7.00','Gerçek 115 – 109'):self.assertIn(expected,text)
        self.assertEqual(sum(e['kind']=='COMMAND_RECEIVED' for e in events),6)
        self.assertIn('/predictions handler grupları: [-50]',text);self.assertIn('PHASE91_PREDICTIONS_V1',text)

    async def test_unknown_mode_is_a_reply_instead_of_an_unregistered_silent_command(self):
        sent,events,groups=await self.exercise(['/predictions NBA'],live=False)
        self.assertEqual(groups,[-50]);self.assertIn('bu modda kullanılamıyor',''.join(sent))

    async def test_unauthorized_chat_is_stopped_before_archive_listing(self):
        sent,events,_=await self.exercise(['/predictions NBA'],chat=999)
        self.assertEqual(sent,[]);self.assertFalse(any(e['kind']=='PREDICTIONS_STARTED' for e in events))

    async def test_bad_arguments_and_bot_suffix_are_routed_explicitly(self):
        sent,_,_=await self.exercise(['/predictions@zeynal_test_bot NBA','/predictions EUROCUP','/predictions NBA zero'])
        self.assertIn('KAYITLI NBA TAHMİNLERİ',''.join(sent));self.assertEqual(sum('Kullanım:' in s for s in sent),2)


class FailureAndIntegrityTests(IsolatedAsyncioTestCase):
    async def call(self,source,*,args=None,send=None,read_timeout=.02):
        journal=SimpleNamespace(append=Mock());reply=send or AsyncMock()
        update=SimpleNamespace(update_id=1,effective_chat=SimpleNamespace(id=17),effective_message=SimpleNamespace(reply_text=reply))
        handler=PredictionsCommand(source,journal,17,read_timeout=read_timeout,send_timeout=.05)
        with self.assertRaises(ApplicationHandlerStop):await handler.handle(update,SimpleNamespace(args=['NBA'] if args is None else args))
        return reply,journal

    async def test_locked_corrupt_and_unexpected_reader_failures_all_reply_safely(self):
        for error in (sqlite3.OperationalError('database locked'),ValueError('bad archive'),AttributeError('private token SECRET')):
            with self.subTest(error=type(error).__name__):
                reply,journal=await self.call(SimpleNamespace(read=Mock(side_effect=error)))
                self.assertIn('PREDICTIONS_ARCHIVE_UNAVAILABLE',reply.call_args.args[0]);self.assertNotIn('SECRET',str(reply.call_args))
                self.assertNotIn('SECRET',str(journal.append.call_args_list))

    async def test_reader_timeout_is_an_actionable_reply(self):
        def slow(*args):time.sleep(.05);return {}
        reply,journal=await self.call(SimpleNamespace(read=slow),read_timeout=.005)
        self.assertIn('PREDICTIONS_READ_TIMEOUT',reply.call_args.args[0])

    async def test_send_failure_has_safe_notice_and_logged_stage(self):
        reply=AsyncMock(side_effect=[BadRequest('secret-token'),None])
        result,journal=await self.call(None,send=reply)
        self.assertEqual(result.call_count,2);self.assertIn('PREDICTIONS_SEND_FAILED',result.call_args.args[0])
        self.assertNotIn('secret-token',str(journal.append.call_args_list))

    async def test_rate_limited_and_forbidden_sends_are_not_retried(self):
        for exc in (RetryAfter(30),Forbidden('secret')):
            reply=AsyncMock(side_effect=exc);_,journal=await self.call(None,send=reply)
            self.assertEqual(reply.call_count,1)
            self.assertTrue(any(c.args[1]['kind']=='PREDICTIONS_SEND_FAILED' for c in journal.append.call_args_list))

    async def test_ten_record_offline_audit_is_read_only_and_not_real_user_archive(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'nba.sqlite';ten_game_ledger(path);before=path.read_bytes();r=await asyncio.to_thread(audit_ledger,path)
            self.assertEqual(r['snapshots_examined'],10);self.assertEqual(r['issues'],[])
            self.assertTrue(all(not x['findings'] for x in r['rows']))
            self.assertEqual(r['performance']['pending'],9);self.assertEqual(r['performance']['groups'][0]['n'],1)
            self.assertEqual(before,path.read_bytes());self.assertTrue(r['database_bytes_unchanged'])

    async def test_rehashed_generation_after_tipoff_is_flagged_not_deleted_or_reported_live(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'nba.sqlite';ten_game_ledger(path,1)
            with sqlite3.connect(path) as db:
                db.execute('DROP TRIGGER live_analysis_no_update')
                raw=db.execute('SELECT payload FROM live_analysis_snapshots').fetchone()[0];p=json.loads(raw);p['prediction_generated_at_utc']=p['fixture_start_utc']+1
                pin=digest(p);db.execute('UPDATE live_analysis_snapshots SET payload=?,sha256=?',(json.dumps(p),pin))
                db.execute('DROP TRIGGER live_receipt_no_update');db.execute('UPDATE live_analysis_commit_receipts SET snapshot_sha256=?',(pin,))
            before=path.read_bytes();r=audit_ledger(path)
            self.assertIn('INVALID_OR_POSTTIPOFF_GENERATION',r['rows'][0]['findings'])
            self.assertEqual(r['performance_status'],'BLOCKED_INVALID_ARCHIVE_OR_NATIVE_RESULT');self.assertEqual(path.read_bytes(),before)

class AdditionalArchiveTests(TestCase):
    def test_empty_ledger_and_unknown_generation_are_not_fabricated(self):
        with TemporaryDirectory() as tmp:
            ledger,_=ten_game_ledger(Path(tmp)/'nba.sqlite',0)
            r=LedgerReports(ledger.path).read('NBA')
            self.assertIn('tahmini bulunamadı',''.join(render_predictions(r)))
            ledger,_=ten_game_ledger(Path(tmp)/'one.sqlite',1)
            r=LedgerReports(ledger.path).read('NBA');r['forecasts'][0]['prediction_generated_at_utc']=None
            text=''.join(render_predictions(r))
            self.assertIn('İlk üretim: ayrı kaydedilmemiş / bilinmiyor',text)
            self.assertIn('İlk kalıcı arşiv:',text)

    def test_missing_database_is_not_created_and_symlink_is_refused(self):
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/'missing.sqlite'
            with self.assertRaises(ValueError):audit_ledger(p)
            self.assertFalse(p.exists());ten_game_ledger(p,1)
            link=Path(tmp)/'link.sqlite';link.symlink_to(p)
            with self.assertRaises(ValueError):audit_ledger(link)

    def test_duplicate_provider_id_across_fixtures_is_reported_without_deletion(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'nba.sqlite';ten_game_ledger(path,2)
            with sqlite3.connect(path) as db:
                db.execute('DROP TRIGGER live_analysis_no_update');db.execute('DROP TRIGGER live_receipt_no_update')
                fid,model,raw=db.execute('SELECT fixture_id,model_digest,payload FROM live_analysis_snapshots ORDER BY created_utc DESC LIMIT 1').fetchone()
                p=json.loads(raw);p['provider_fixture_ids']=['401000123'];pin=digest(p)
                db.execute('UPDATE live_analysis_snapshots SET payload=?,sha256=? WHERE fixture_id=?',(json.dumps(p),pin,fid))
                db.execute('UPDATE live_analysis_commit_receipts SET snapshot_sha256=? WHERE fixture_id=?',(pin,fid))
            before=path.read_bytes();r=audit_ledger(path)
            self.assertTrue(any(i['code']=='ESPN_ID_BOUND_TO_MULTIPLE_FIXTURES' for i in r['issues']))
            self.assertEqual(r['snapshots_examined'],2);self.assertEqual(path.read_bytes(),before)

    def test_unconfirmed_snapshot_is_visible_in_audit_but_excluded_from_live_metrics(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'nba.sqlite';ten_game_ledger(path,2)
            with sqlite3.connect(path) as db:
                db.execute('DROP TRIGGER live_receipt_no_delete')
                db.execute('DELETE FROM live_analysis_commit_receipts WHERE completed_utc=(SELECT MAX(completed_utc) FROM live_analysis_commit_receipts)')
            before=path.read_bytes();r=audit_ledger(path)
            self.assertEqual(r['snapshots_examined'],2)
            self.assertEqual(sum('UNCONFIRMED_SNAPSHOT_EXCLUDED_FROM_LIVE_REPORTS' in row['findings'] for row in r['rows']),1)
            self.assertEqual(r['performance']['unique_fixtures'],1);self.assertEqual(path.read_bytes(),before)

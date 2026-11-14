"""Opt-in isolated Telegram test bot. No production token or user account is used."""
import argparse
import asyncio
from contextvars import ContextVar
import json
import logging
import os
from pathlib import Path
import time

from telegram import Update
from telegram.ext import Application,ApplicationHandlerStop,TypeHandler
from telegram.request import HTTPXRequest

from core.team_identity import digest
from hybrid_engine.data import local_path
from hybrid_engine.frozen_archive import FrozenArchive,FrozenHybridService
from hybrid_engine.prospective_results import ProspectiveResults,ResearchReports,OFFICIAL
from hybrid_engine.source_policy import ControlledTransport
from season_archive_collect import fetch_document
from telegram_delivery import DeliveryJournal
from verified_analysis import VerifiedAnalyzeService

_update=ContextVar('isolated_test_update_id',default=None)
REQUIRED=('ZEYNAL_TEST_BOT_TOKEN','ZEYNAL_TEST_BOT_ID','ZEYNAL_TEST_BOT_USERNAME','ZEYNAL_TEST_CHAT_ID')
SAFE_FAILURE_CODES=frozenset(('TEST_BOT_SERVER_IDENTITY_MISMATCH','TEST_BOT_HAS_WEBHOOK_POLLING_NOT_STARTED',
    'DEDICATED_TEST_BOT_IDENTITY_REQUIRED','EXPLICIT_TEST_IDENTITY_REQUIRED','ISOLATED_DIRECTORIES_REQUIRED',
    'REPLAY_ONLY_FORBIDS_LIVE_MODELS_AND_RESULT_COLLECTION','BOUNDED_RESULT_POLL_INTERVAL_REQUIRED',
    'NBA_REPLAY_PACKET_REQUIRED_OR_TOO_LARGE','NBA_REPLAY_PACKET_SHA256','NBA_REPLAY_CAPTURE_PIN_OR_COUNT',
    'NBA_REPLAY_NATIVE_FIXTURE_IDENTITY'))


def failure_report(exc):
    # Only fixed internal codes may leave the process. API exception strings can
    # contain credential-bearing URLs; never echo them as diagnostic detail.
    text=str(exc)
    return dict(status='FAILED',error_type=type(exc).__name__,
        reason=text if text in SAFE_FAILURE_CODES else 'ISOLATED_TEST_BOT_FAILED',actual_telegram_delivery_verified=False)


def configuration(env):
    missing=[n for n in REQUIRED if not env.get(n)]
    if missing:return dict(status='NOT_CONFIGURED',missing=missing,actual_telegram_delivery_verified=False)
    token=env['ZEYNAL_TEST_BOT_TOKEN'];bid=int(env['ZEYNAL_TEST_BOT_ID']);chat=int(env['ZEYNAL_TEST_CHAT_ID'])
    username=env['ZEYNAL_TEST_BOT_USERNAME'].lstrip('@')
    if token.split(':',1)[0]!=str(bid) or not any(s in username.lower() for s in ('test','sandbox','research')):
        raise ValueError('DEDICATED_TEST_BOT_IDENTITY_REQUIRED')
    if bid<=0 or chat==0:raise ValueError('EXPLICIT_TEST_IDENTITY_REQUIRED')
    return dict(status='CONFIGURED_NOT_TESTED',bot_id=bid,username=username,chat_id=chat,actual_telegram_delivery_verified=False)


class AuditedRequest(HTTPXRequest):
    def __init__(self,journal,*,expected_identity=None,**kwargs):
        super().__init__(**kwargs);self.journal=journal;self.expected_identity=expected_identity;self.identity_verified=False
        # HTTPX INFO request lines contain the Bot API token in the URL path.
        logging.getLogger('httpx').setLevel(logging.ERROR)
        logging.getLogger('httpcore').setLevel(logging.ERROR)
    async def do_request(self,url,method,**kwargs):
        name=url.rsplit('/',1)[-1]
        try:status,body=await super().do_request(url,method,**kwargs)
        except Exception as exc:
            if name=='sendMessage':
                await asyncio.to_thread(self.journal.append,digest(dict(update=_update.get(),kind='SEND_UNCONFIRMED')),
                    dict(kind='SEND_UNCONFIRMED',update_id=_update.get(),error_type=type(exc).__name__,observed_at_utc=int(time.time())))
            raise
        from hybrid_engine.telegram_evidence import official_endpoint,plaintext
        identity=self.expected_identity or {}
        official=official_endpoint(url,identity.get('bot_id'),name)
        if name=='getMe' and official:
            data=json.loads(body);r=data.get('result',{})
            self.identity_verified=bool(status==200 and data.get('ok') is True and r.get('id')==identity.get('bot_id') and
                r.get('username')==identity.get('username') and r.get('is_bot') is True)
        if name=='sendMessage':
            data=json.loads(body)
            if status==200 and data.get('ok'):
                r=data['result'];event=dict(kind='DELIVERY_ACCEPTED',update_id=_update.get(),telegram_sent_at_utc=r['date'],
                    telegram_reply_at_utc=r['date'],
                    telegram_message_id=r['message_id'],chat_id=r['chat']['id'],ack_at_utc=int(time.time()),
                    message_sha256=digest(r.get('text','')))
                request_data=kwargs.get('request_data');parameters=getattr(request_data,'parameters',{}) or {}
                event.update(transport='OFFICIAL_TELEGRAM_BOT_API' if official else 'MOCK_OR_UNATTESTED_ENDPOINT',
                    dedicated_bot_identity_verified=self.identity_verified and official,
                    expected_chat_matches=r['chat']['id']==identity.get('chat_id'),
                    response_content_matches_request=(type(parameters.get('text')) is str and
                        plaintext(parameters['text'],parameters.get('parse_mode'))==r.get('text')),
                    response_sha256=digest(data),request_text_sha256=digest(parameters.get('text','')))
                await asyncio.to_thread(self.journal.append,digest(dict(chat=event['chat_id'],message=event['telegram_message_id'])),event)
        return status,body


class NBAReplayReadOnlyReports:
    """Read-only research view of verified, frozen NBA replay snapshots.

    Does not fetch results, modify archives, or claim retrospective accuracy.
    """
    def __init__(self,replay,fallback):
        self.replay=replay
        self.fallback=fallback

    def read(self,league=None,fixture_id=None):
        if league is not None and league.upper()!='NBA':
            return dict(source='fallback',report=self.fallback.read(league,fixture_id))
        cases=self.replay.cases()
        rows=[]
        for case in cases:
            snap=case['snapshot']
            ids={str(snap['fixture_id']),*(str(x) for x in snap['provider_fixture_ids'])}
            if fixture_id is not None and str(fixture_id) not in ids:
                continue
            prediction=snap['prediction']
            rows.append(dict(fixture_id=str(snap['fixture_id']),
                provider_ids=sorted(ids-{str(snap['fixture_id'])}),
                home=case['home'],away=case['away'],
                home_score=prediction['home'],away_score=prediction['away'],
                snapshot_sha256=case['snapshot_sha256']))
        if fixture_id is not None and len(rows)>1:
            raise ValueError('REPORT_AMBIGUOUS_FIXTURE')
        return dict(source='nba_replay',rows=rows,total_archived=len(cases),
            verified_finals=0,finals_status='NOT_INGESTED')

    def render_accuracy(self,r):
        if r['source']=='fallback':
            return self.fallback.render_accuracy(r['report'])
        header=('ZEYNAL | NBA ARŞİV REPLAY DENETİMİ | ÜRETİM DEĞİL\n'
            f"Arşiv tahmini: {r['total_archived']} | Doğrulanmış final: 0\n"
            'Final sonuçları bu izole replay modunda toplanmıyor. '
            'Bekleyen/sonuçlanan canlı tahmin sayısı ve başarı oranı hesaplanmadı.\n'
            'Arşiv replay kayıtları ileriye dönük doğrulanmış performans değildir.\n'
            'Karşılaştırma için doğrulanmış maç kimlikleri:\n')
        commands='\n'.join(
            f"{row['home']} – {row['away']}: /compare NBA {row['fixture_id']}"
            for row in r['rows'])
        return header+commands

    def render_compare(self,r):
        if r['source']=='fallback':
            return self.fallback.render_compare(r['report'])
        if not r['rows']:
            return 'Bu kimlik için doğrulanmış NBA replay tahmini bulunamadı.'
        row=r['rows'][0]
        return ('ZEYNAL | NBA ARŞİV REPLAY KARŞILAŞTIRMASI | ÜRETİM DEĞİL\n'
            f"{row['home']} – {row['away']}\n"
            f"Maç kimliği: {row['fixture_id']}\n"
            f"Orijinal skor: {row['home_score']:.2f} – {row['away_score']:.2f}\n"
            'Gerçek final: doğrulanmadı / bu replay moduna aktarılmadı.\n'
            'MAE, RMSE ve başarı yüzdesi hesaplanmadı. '
            'Orijinal arşiv kaydı değiştirilmedi.')


def install_isolated_services(app,archive,data_directory,*,chat_id,transport=None,nba_service=None,decision_layer=False,audit_report=None,nba_replay=None,replay_only=False):
    if replay_only and nba_service is not None:raise ValueError('REPLAY_ONLY_FORBIDS_LIVE_NBA_SERVICE')
    if nba_replay is None and nba_service is None:
        from hybrid_engine.nba_replay import NBAReplayArchive
        nba_replay=NBAReplayArchive()
    root=local_path(data_directory);root.mkdir(parents=True,exist_ok=True)
    journal=DeliveryJournal(root/'telegram-delivery.sqlite');results=ProspectiveResults(archive,root/'official-results')
    frozen=FrozenHybridService(archive)
    if nba_service is not None:
        from ledger_reports import LedgerReports,render_accuracy,render_compare
        class Dispatch:
            ledger=nba_service.ledger
            async def analyze(self,league,*args):
                return await (nba_service if league.upper()=='NBA' else frozen).analyze(league,*args)
        class Reports:
            def __init__(self):self.live=LedgerReports(nba_service.ledger.path);self.frozen=ResearchReports(results)
            def read(self,league=None,fixture_id=None):
                live=league is None or league.upper()=='NBA'
                return dict(live=live,report=(self.live if live else self.frozen).read('NBA' if live else league,fixture_id))
            def render_accuracy(self,r):
                return ('İZOLE NBA HİBRİT ARAŞTIRMA — ÜRETİM DEĞİL\n'+render_accuracy(r['report'])) if r['live'] else self.frozen.render_accuracy(r['report'])
            def render_compare(self,r):
                return ('İZOLE NBA HİBRİT ARAŞTIRMA — ÜRETİM DEĞİL\n'+render_compare(r['report'])) if r['live'] else self.frozen.render_compare(r['report'])
        app.bot_data['verified_analysis_service']=Dispatch();app.bot_data['ledger_reports']=Reports()
    else:
        app.bot_data['verified_analysis_service']=frozen
        app.bot_data['ledger_reports']=(NBAReplayReadOnlyReports(nba_replay,ResearchReports(results))
            if replay_only and nba_replay is not None else ResearchReports(results))
    app.bot_data['delivery_journal']=journal
    if decision_layer:
        from hybrid_engine.decision_integration import DecisionJournal,DecisionService,DecisionReports
        decisions=DecisionJournal(root/'decision-audit.sqlite')
        app.bot_data['verified_analysis_service']=DecisionService(app.bot_data['verified_analysis_service'],archive,decisions,nba_service=nba_service)
        app.bot_data['ledger_reports']=DecisionReports(app.bot_data['ledger_reports'],decisions,audit_report=audit_report)
        app.bot_data['decision_journal']=decisions
    if nba_replay is not None:
        base=app.bot_data['verified_analysis_service']
        class ReplayDispatch:
            ledger=getattr(base,'ledger',None)
            async def analyze(self,league,day,home,away):
                if league.upper()=='NBA' and (replay_only or nba_service is None or nba_replay.has_pair(home,away)):
                    return await nba_replay.analyze(league,day,home,away)
                return await base.analyze(league,day,home,away)
        app.bot_data['verified_analysis_service']=ReplayDispatch()
    fetch=transport or ControlledTransport(fetch_document)
    app.bot_data['nba_fixture_loader']=nba_replay.list_nba_games if replay_only else VerifiedAnalyzeService(None,fetcher=fetch).list_nba_games
    async def authorized(update,context):
        if update.effective_chat is None or update.effective_chat.id!=chat_id:raise ApplicationHandlerStop
        _update.set(update.update_id)
        message=update.effective_message
        if message and message.text:
            await asyncio.to_thread(journal.append,'received:'+str(update.update_id),dict(kind='COMMAND_RECEIVED',update_id=update.update_id,
                command=message.text.split()[0].split('@')[0],chat_id=update.effective_chat.id,
                is_bot=getattr(update.effective_user,'is_bot',None),
                user_message_at_utc=int(message.date.timestamp()),received_at_utc=int(time.time())))
    async def error(update,context):
        await asyncio.to_thread(journal.append,digest(dict(update=getattr(update,'update_id',None),kind='HANDLER_ERROR')),
            dict(kind='HANDLER_ERROR',update_id=getattr(update,'update_id',None),error_type=type(context.error).__name__,observed_at_utc=int(time.time())))
    async def self_test(update,context):
        """Read-only diagnostics, available only in the authorized test chat."""
        if update.effective_chat is None or update.effective_chat.id!=chat_id:
            return
        message=update.effective_message
        if message is None:
            return
        args=(message.text or '').split()
        mode=args[1].lower() if len(args)>1 else 'all'
        if mode not in ('all','nba','euroleague'):
            await message.reply_text('Kullanım: /test, /test nba, /test euroleague, /test all')
            raise ApplicationHandlerStop
        lines=['ZEYNAL | İZOLE TEST BOTU | ÜRETİM DEĞİL',
            'Telegram komut alımı: OK',
            'Yetkili sohbet: OK',
            'Bu yanıtın teslimi Telegram üzerinden kontrol edilmelidir.']
        if mode in ('all','euroleague'):
            try:
                count=len(archive.records)
                lines.append(f'EuroLeague doğrulanmış arşiv kaydı: {count}')
                lines.append('EuroLeague arşiv: OK' if count else 'EuroLeague arşiv: BOŞ')
            except (AttributeError,TypeError,ValueError,OSError) as exc:
                lines.append('EuroLeague arşiv: HATA ('+type(exc).__name__+')')
        if mode in ('all','nba'):
            try:
                if nba_replay is not None:
                    cases=nba_replay.cases()
                    lines.append(f'NBA replay kayıtları: {len(cases)}')
                    lines.append('NBA replay: OK' if cases else 'NBA replay: BOŞ')
                else:
                    lines.append('NBA replay: YAPILANDIRILMADI')
                lines.append('Canlı NBA hibrit motoru: '+('YÜKLÜ (analiz henüz doğrulanmadı)' if nba_service is not None else 'DEVRE DIŞI'))
            except (TypeError,ValueError,OSError,KeyError) as exc:
                lines.append('NBA replay: HATA ('+type(exc).__name__+')')
        lines.append('Bu kontrol maç tahmini, gerçek fikstür veya Fly.io dağıtımını doğrulamaz.')
        await message.reply_text('\n'.join(lines))
        raise ApplicationHandlerStop
    from telegram.ext import CommandHandler
    app.add_handler(CommandHandler('test',self_test),group=-50)
    app.add_handler(TypeHandler(Update,authorized),group=-100);app.add_error_handler(error)
    return journal,results


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--preflight',action='store_true')
    parser.add_argument('--archive-directory');parser.add_argument('--data-directory');parser.add_argument('--result-poll-seconds',type=int,default=300)
    parser.add_argument('--nba-model');parser.add_argument('--nba-model-sha')
    parser.add_argument('--decision-layer',action='store_true');parser.add_argument('--decision-audit');parser.add_argument('--decision-audit-sha')
    parser.add_argument('--forward-euroleague-directory');parser.add_argument('--forward-nba-ledger')
    parser.add_argument('--nba-replay-packet');parser.add_argument('--replay-only',action='store_true')
    args=parser.parse_args();config=configuration(os.environ)
    if args.preflight or config['status']=='NOT_CONFIGURED':print(json.dumps(config));return
    if not args.archive_directory or not args.data_directory:raise ValueError('ISOLATED_DIRECTORIES_REQUIRED')
    if args.replay_only and (args.nba_model or args.nba_model_sha or args.forward_euroleague_directory or args.forward_nba_ledger):
        raise ValueError('REPLAY_ONLY_FORBIDS_LIVE_MODELS_AND_RESULT_COLLECTION')
    from hybrid_engine.nba_replay import NBAReplayArchive,DEFAULT_PACKET
    nba_replay=NBAReplayArchive(local_path(args.nba_replay_packet) if args.nba_replay_packet else DEFAULT_PACKET)
    if args.result_poll_seconds<60:raise ValueError('BOUNDED_RESULT_POLL_INTERVAL_REQUIRED')
    if bool(args.nba_model)!=bool(args.nba_model_sha):raise ValueError('EXPLICIT_NBA_MODEL_AND_TRUSTED_PIN_REQUIRED')
    nba_model_path=local_path(args.nba_model) if args.nba_model else None
    forward_el=None
    if args.forward_euroleague_directory:
        from hybrid_engine.forward_validation import ForwardRegistry
        forward_el=ForwardRegistry(local_path(args.forward_euroleague_directory))
    forward_nba=local_path(args.forward_nba_ledger) if args.forward_nba_ledger else None
    if bool(args.decision_audit)!=bool(args.decision_audit_sha):raise ValueError('EXPLICIT_AUDIT_PATH_AND_PIN_REQUIRED')
    audit_report=None
    if args.decision_audit:
        from hybrid_engine.decision_integration import read_audit_report
        if not args.decision_layer:raise ValueError('AUDIT_REQUIRES_DECISION_LAYER')
        audit_report=read_audit_report(local_path(args.decision_audit),args.decision_audit_sha)
    archive=FrozenArchive(args.archive_directory);root=local_path(args.data_directory);root.mkdir(parents=True,exist_ok=True)
    os.environ['TELEGRAM_BOT_TOKEN']=os.environ['ZEYNAL_TEST_BOT_TOKEN']
    os.environ['PREDICTION_LEDGER_DB']=str(root/'unused-live-ledger.sqlite')
    os.environ['API_SPORTS_KEY']='';os.environ['ENABLE_LEGACY_SCHEDULER']='0'
    os.chdir(root)
    import main as application
    application.TELEGRAM_BOT_TOKEN=os.environ['ZEYNAL_TEST_BOT_TOKEN']
    journal=DeliveryJournal(root/'telegram-delivery.sqlite');transport=ControlledTransport(fetch_document)
    original=application.Application
    tasks=[]
    async def ready(app):
        me=await app.bot.get_me()
        if me.id!=config['bot_id'] or me.username!=config['username']:raise ValueError('TEST_BOT_SERVER_IDENTITY_MISMATCH')
        hook=await app.bot.get_webhook_info()
        if hook.url:raise ValueError('TEST_BOT_HAS_WEBHOOK_POLLING_NOT_STARTED')
        async def collect():
            while True:
                try:
                    receipt=await asyncio.to_thread(transport,'EUROLEAGUE_LIVE',OFFICIAL)
                    await asyncio.to_thread(app.bot_data['test_results'].ingest,receipt)
                    if forward_el is not None:
                        from hybrid_engine.forward_nba_results import report_euroleague
                        await asyncio.to_thread(forward_el.settle,receipt)
                        await asyncio.to_thread(report_euroleague,forward_el)
                    if forward_nba is not None:
                        from hybrid_engine.forward_nba_results import collect as collect_forward_nba
                        await asyncio.to_thread(collect_forward_nba,forward_nba,root/'forward-nba-results')
                except (ValueError,OSError) as exc:
                    await asyncio.to_thread(journal.append,digest(dict(kind='RESULT_POLL_FAILED',at=int(time.time()))),
                        dict(kind='RESULT_POLL_FAILED',error_type=type(exc).__name__,observed_at_utc=int(time.time())))
                await asyncio.sleep(args.result_poll_seconds)
        if not args.replay_only:tasks.append(asyncio.create_task(collect()))
    async def stop(app):
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
    class IsolatedApplication:
        @staticmethod
        def builder():return Application.builder().request(AuditedRequest(journal,expected_identity=config)).post_init(ready).post_shutdown(stop)
    application.Application=IsolatedApplication
    try:app=application.build_app()
    finally:application.Application=original
    nba_service=None
    if args.nba_model:
        from hybrid_engine.live_nba import PreparedBayes,LiveNBAHybridService
        nba_service=LiveNBAHybridService(root/'live-nba',PreparedBayes(nba_model_path,trusted_sha256=args.nba_model_sha))
    _,results=install_isolated_services(app,archive,root,chat_id=config['chat_id'],transport=transport,nba_service=nba_service,
        decision_layer=args.decision_layer,audit_report=audit_report,nba_replay=nba_replay,replay_only=args.replay_only)
    app.bot_data['test_results']=results
    # Commands must arrive from the authorized HUMAN test chat; bot self-messages
    # are never counted as real command-input E2E evidence.
    from concurrent.futures import ThreadPoolExecutor
    loop=asyncio.new_event_loop();asyncio.set_event_loop(loop)
    loop.set_default_executor(ThreadPoolExecutor(max_workers=1,thread_name_prefix='hybrid-test'))
    app.run_polling(bootstrap_retries=0,drop_pending_updates=False)


if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps(failure_report(exc)))
        raise SystemExit(2)

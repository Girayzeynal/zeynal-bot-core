"""Opt-in isolated Telegram test bot. No production token or user account is used."""
import argparse
import asyncio
from contextvars import ContextVar
import json
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
    def __init__(self,journal,**kwargs):super().__init__(**kwargs);self.journal=journal
    async def do_request(self,url,method,**kwargs):
        name=url.rsplit('/',1)[-1]
        try:status,body=await super().do_request(url,method,**kwargs)
        except Exception as exc:
            if name=='sendMessage':
                await asyncio.to_thread(self.journal.append,digest(dict(update=_update.get(),kind='SEND_UNCONFIRMED')),
                    dict(kind='SEND_UNCONFIRMED',update_id=_update.get(),error_type=type(exc).__name__,observed_at_utc=int(time.time())))
            raise
        if name=='sendMessage':
            data=json.loads(body)
            if status==200 and data.get('ok'):
                r=data['result'];event=dict(kind='DELIVERY_ACCEPTED',update_id=_update.get(),telegram_sent_at_utc=r['date'],
                    telegram_reply_at_utc=r['date'],
                    telegram_message_id=r['message_id'],chat_id=r['chat']['id'],ack_at_utc=int(time.time()),
                    message_sha256=digest(r.get('text','')))
                await asyncio.to_thread(self.journal.append,digest(dict(chat=event['chat_id'],message=event['telegram_message_id'])),event)
        return status,body


def install_isolated_services(app,archive,data_directory,*,chat_id,transport=None,nba_service=None):
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
        app.bot_data['verified_analysis_service']=frozen;app.bot_data['ledger_reports']=ResearchReports(results)
    app.bot_data['delivery_journal']=journal
    fetch=transport or ControlledTransport(fetch_document)
    app.bot_data['nba_fixture_loader']=VerifiedAnalyzeService(None,fetcher=fetch).list_nba_games
    async def authorized(update,context):
        if update.effective_chat is None or update.effective_chat.id!=chat_id:raise ApplicationHandlerStop
        _update.set(update.update_id)
        message=update.effective_message
        if message and message.text:
            await asyncio.to_thread(journal.append,'received:'+str(update.update_id),dict(kind='COMMAND_RECEIVED',update_id=update.update_id,
                command=message.text.split()[0],user_message_at_utc=int(message.date.timestamp()),received_at_utc=int(time.time())))
    async def error(update,context):
        await asyncio.to_thread(journal.append,digest(dict(update=getattr(update,'update_id',None),kind='HANDLER_ERROR')),
            dict(kind='HANDLER_ERROR',update_id=getattr(update,'update_id',None),error_type=type(context.error).__name__,observed_at_utc=int(time.time())))
    app.add_handler(TypeHandler(Update,authorized),group=-100);app.add_error_handler(error)
    return journal,results


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--preflight',action='store_true')
    parser.add_argument('--archive-directory');parser.add_argument('--data-directory');parser.add_argument('--result-poll-seconds',type=int,default=300)
    parser.add_argument('--nba-model');parser.add_argument('--nba-model-sha')
    args=parser.parse_args();config=configuration(os.environ)
    if args.preflight or config['status']=='NOT_CONFIGURED':print(json.dumps(config));return
    if not args.archive_directory or not args.data_directory:raise ValueError('ISOLATED_DIRECTORIES_REQUIRED')
    if args.result_poll_seconds<60:raise ValueError('BOUNDED_RESULT_POLL_INTERVAL_REQUIRED')
    if bool(args.nba_model)!=bool(args.nba_model_sha):raise ValueError('EXPLICIT_NBA_MODEL_AND_TRUSTED_PIN_REQUIRED')
    nba_model_path=local_path(args.nba_model) if args.nba_model else None
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
                except (ValueError,OSError) as exc:
                    await asyncio.to_thread(journal.append,digest(dict(kind='RESULT_POLL_FAILED',at=int(time.time()))),
                        dict(kind='RESULT_POLL_FAILED',error_type=type(exc).__name__,observed_at_utc=int(time.time())))
                await asyncio.sleep(args.result_poll_seconds)
        tasks.append(asyncio.create_task(collect()))
    async def stop(app):
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
    class IsolatedApplication:
        @staticmethod
        def builder():return Application.builder().request(AuditedRequest(journal)).post_init(ready).post_shutdown(stop)
    application.Application=IsolatedApplication
    try:app=application.build_app()
    finally:application.Application=original
    nba_service=None
    if args.nba_model:
        from hybrid_engine.live_nba import PreparedBayes,LiveNBAHybridService
        nba_service=LiveNBAHybridService(root/'live-nba',PreparedBayes(nba_model_path,trusted_sha256=args.nba_model_sha))
    _,results=install_isolated_services(app,archive,root,chat_id=config['chat_id'],transport=transport,nba_service=nba_service)
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
        print(json.dumps(dict(status='FAILED',error_type=type(exc).__name__,actual_telegram_delivery_verified=False)))
        raise SystemExit(2)

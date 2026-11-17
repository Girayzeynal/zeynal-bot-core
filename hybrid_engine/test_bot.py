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


def install_isolated_services(app,archive,data_directory,*,chat_id,transport=None,nba_service=None,decision_layer=False,audit_report=None,nba_replay=None,replay_only=False,forward_el=None,provider_bridge=None,roster_review=None,europe_directory=None):
    if replay_only and (nba_service is not None or forward_el is not None or europe_directory is not None):raise ValueError('REPLAY_ONLY_FORBIDS_LIVE_NBA_SERVICE')
    if nba_replay is None and nba_service is None:
        from hybrid_engine.nba_replay import NBAReplayArchive
        nba_replay=NBAReplayArchive()
    root=local_path(data_directory);root.mkdir(parents=True,exist_ok=True)
    from hybrid_engine.market_observations import ObservationStore
    market_store=ObservationStore(root/'market-observations')
    app.bot_data['market_observation_store']=market_store
    if nba_service is not None:
        from hybrid_engine.current_roster import CurrentRosterReview
        app.bot_data['current_roster_review']=roster_review or CurrentRosterReview(root/'current-roster',report_archive=root/'official-reports')
    journal=DeliveryJournal(root/'telegram-delivery.sqlite');results=ProspectiveResults(archive,root/'official-results')
    frozen=FrozenHybridService(archive)
    if nba_service is not None:
        from ledger_reports import LedgerReports,render_accuracy,render_compare
        class Dispatch:
            ledger=nba_service.ledger
            async def analyze(self,league,*args):
                response=await (nba_service if league.upper()=='NBA' else frozen).analyze(league,*args)
                if league.upper()=='NBA' and response.get('status')=='ABSTAIN':
                    from hybrid_engine.fixture_rejection_diagnostic import enrich_fixture_rejection, render_fixture_rejection
                    preflight=await enrich_fixture_rejection(response.get('preflight') or {},args[0],transport or ControlledTransport(fetch_document))
                    diagnostic=render_fixture_rejection(preflight)
                    if diagnostic:
                        response=dict(response)
                        response['html']=(response.get('html') or '')+diagnostic
                    return response
                if league.upper()!='NBA' or response.get('status')!='ANALYSIS_OK':
                    return response
                from hybrid_engine.prediction_audit import audit_snapshot,render_source_annotation
                try:
                    quality=await asyncio.to_thread(audit_snapshot,response['snapshot'],nba_service.assets)
                except (ValueError,KeyError,TypeError,OSError):
                    return dict(status='ABSTAIN',html='Kayıtlı tahminin kaynak/zaman/model bütünlüğü doğrulanamadı; tahmin değiştirilmedi ve analiz yayınlanmadı.')
                from hybrid_engine.quality_monitor import monitor
                from hybrid_engine.health_card import build as build_health, render as render_health
                def prior_quality():
                    report=LedgerReports(nba_service.ledger.path).read('NBA')
                    return monitor(report['forecasts'],asof_utc=response['snapshot']['prediction_generated_at_utc'])
                try:
                    prior=await asyncio.wait_for(asyncio.to_thread(prior_quality),timeout=3)
                except Exception as exc:
                    logging.getLogger(__name__).warning('Prior quality read unavailable: %s',type(exc).__name__)
                    prior=None
                health=build_health(response['snapshot'],quality,prior_quality=prior)
                if not health['publication_allowed']:
                    return dict(status='ABSTAIN',html=render_health(health)+'\nVar olan tahminler değiştirilmedi; sağlık denetimi bu analiz yayını durdurdu.')
                response=dict(response,quality_audit=quality,html_parts=[*response['html_parts'],render_source_annotation(quality)])
                from hybrid_engine.market_evidence_report import observed_market_evidence, render_quote_line
                import html as _html
                from datetime import datetime, timezone
                snapshot=response['snapshot']
                try:
                    evidence=observed_market_evidence(
                        nba_service.assets,
                        {str(i): ref for i,ref in enumerate(snapshot['source_assets'])},
                        snapshot['fixture_id'],
                        snapshot['prediction_generated_at_utc'],
                        snapshot['fixture_start_utc'])
                except (ValueError, KeyError, TypeError, OSError):
                    evidence=[]
                if evidence:
                    market_lines=['<b>GÖZLENEN PİYASA | ARAŞTIRMA</b>',
                        'Normal süre/uzatma kapsamı doğrulanmadı; karşılaştırılabilir edge veya güven endeksi yok.']
                    report_utc=int(datetime.now(timezone.utc).timestamp())
                    for quote in evidence:
                        market_lines.append(_html.escape(render_quote_line(
                            quote, snapshot['prediction_generated_at_utc'], report_utc)))
                else:
                    market_lines=['<b>PİYASA KAYNAĞI</b>',
                        'Tahmin anından önce doğrulanmış piyasa çizgisi yok; barem veya güven endeksi üretilmedi.']
                direction_cards=[]
                if provider_bridge is not None:
                    try:
                        from hybrid_engine.provider_bridge import nba_provider_panel
                        provider_panel=await asyncio.wait_for(
                            asyncio.to_thread(nba_provider_panel,snapshot,nba_service,provider_bridge,structured=True),timeout=16)
                        market_lines.append(provider_panel['html'])
                        direction_cards.extend(provider_panel['cards'])
                    except Exception as exc:
                        logging.getLogger(__name__).warning('Provider review unavailable: %s',type(exc).__name__)
                        market_lines.append('Sağlayıcı denetimi tamamlanamadı: PROVIDER_REVIEW_UNAVAILABLE. Bu durum NO EDGE değildir; skor tahmini korunuyor.')
                market_note=None
                from hybrid_engine.market_panels import nba_panel
                try:
                    panel=await asyncio.wait_for(asyncio.to_thread(nba_panel,snapshot,nba_service,evidence,market_store),timeout=5)
                    market_lines.append(panel['html'])
                    direction_cards.extend(panel.get('cards',[]))
                    if panel['observations']:
                        market_note=f"Piyasa düğmesinde {panel['observations']} kaynak gözlemi / {panel['lines']} barem; ham model hesabı."
                except Exception as exc:
                    logging.getLogger(__name__).warning('Market source panel unavailable: %s',type(exc).__name__)
                    market_lines.append('Piyasa kaynak/dağılım denetimi tamamlanamadı; skor tahmini korunuyor. Kod: MARKET_PANEL_UNAVAILABLE')
                response=dict(response)
                from hybrid_engine.telegram_premium_ui import compact_summary, keyboard, detail_sections
                import secrets
                token=secrets.token_hex(6)
                from hybrid_engine.market_direction_ui import order,pages as direction_pages
                ranked=order(direction_cards)
                first_total=next((c for c in ranked if c['current'] and c['period']=='FULL' and c['market']=='TOTAL'),None)
                summary=compact_summary(snapshot,evidence,replayed=not response['new_record'],health=health,
                    market_note=market_note,direction_card=first_total)
                from hybrid_engine.telegram_roster_bridge import read_fixture_roster_evidence
                roster=read_fixture_roster_evidence(
                    app.bot_data.get('verified_roster_packets'),
                    fixture_id=snapshot['fixture_id'],
                    prediction_utc=snapshot['prediction_generated_at_utc'],
                    fixture_start_utc=snapshot['fixture_start_utc'],
                    home_team_id=str(snapshot['home'].get('team_id') or snapshot['home'].get('official_name')),
                    away_team_id=str(snapshot['away'].get('team_id') or snapshot['away'].get('official_name')))
                market_pages=direction_pages(direction_cards)
                market_html=market_pages[0] if market_pages else '<b>PİYASA</b>\nDoğrulanabilir barem yok; yön veya yüzde üretilmedi.\nSağlayıcı ayrıntıları: Model / Kaynak düğmesi.'
                sections=detail_sections(response['html_parts'],market_html,
                                         roster_evidence=roster)
                sections['audit']=render_health(health)+'\n\n'+sections['audit']+'\n\n'+'\n\n'.join(market_lines)
                from hybrid_engine.elite_render import split_blocks
                section_pages={k:split_blocks(v.splitlines(),limit=3200) for k,v in sections.items()}
                if market_pages:section_pages['market']=market_pages
                cache=app.bot_data.setdefault('premium_reports',{})
                from hybrid_engine.telegram_premium_ui import cache_report
                expiry=[c['valid_until_utc'] for c in ranked if c['current']]
                entry=dict(summary=summary,sections=sections,section_pages=section_pages,chat_id=chat_id,
                    tipoff_utc=snapshot['fixture_start_utc'],quote_valid_until_utc=min(expiry) if expiry else None)
                try:
                    from hybrid_engine.current_roster import context_for
                    entry['roster_context']=context_for(snapshot)
                    entry['original_roster_html']='🏥 <b>İLK TAHMİN ANINDAKİ KADRO KANITI</b>\n'+sections['roster']
                except (ValueError,KeyError,TypeError):
                    entry['roster_context']=None
                cache_report(cache,token,entry)
                response['html_parts']=[summary]
                response['reply_markup']=keyboard(token)
                return response
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
    if forward_el is not None:
        from hybrid_engine.live_euroleague import LiveEuroLeagueService
        from hybrid_engine.forward_reports import ForwardEuroLeagueReports
        live_el=LiveEuroLeagueService(archive,forward_el,transport or ControlledTransport(fetch_document),frozen)
        prior=app.bot_data['verified_analysis_service']
        class LeagueDispatch:
            ledger=getattr(prior,'ledger',None)
            async def analyze(self,league,*args):
                return await (live_el if league.upper()=='EUROLEAGUE' else prior).analyze(league,*args)
        app.bot_data['verified_analysis_service']=LeagueDispatch()
        app.bot_data['ledger_reports']=ForwardEuroLeagueReports(live_el,app.bot_data['ledger_reports'])
    # Listing the preserved five-game archive does not require enabling inference.
    from types import SimpleNamespace
    from hybrid_engine.europe_reports import EuropeanReports,EuropeanReportRouter
    empty=SimpleNamespace(independent_records=lambda:[])
    legacy_service=(SimpleNamespace(league='EUROLEAGUE',registry=forward_el,pair=live_el._pair) if forward_el is not None else
                    SimpleNamespace(league='EUROLEAGUE',registry=empty))
    europe_readers={'EUROLEAGUE':EuropeanReports(legacy_service,results),
                    'EUROCUP':EuropeanReports(SimpleNamespace(league='EUROCUP',registry=empty))}
    europe_services={}
    if europe_directory is not None:
        from hybrid_engine.europe_live import EuropeanService
        directory=local_path(europe_directory)
        for code in ('EUROLEAGUE','EUROCUP'):
            service=EuropeanService(code,directory/code.lower(),directory/'models',transport or ControlledTransport(fetch_document),
                archive=archive if code=='EUROLEAGUE' else None,fallback=frozen,
                previous=live_el if code=='EUROLEAGUE' and forward_el is not None else None)
            europe_services[code]=service
            extras=(legacy_service,) if code=='EUROLEAGUE' and forward_el is not None else ()
            europe_readers[code]=EuropeanReports(service,results if code=='EUROLEAGUE' else None,extras)
        previous_service=app.bot_data['verified_analysis_service']
        class EuropeanDispatch:
            ledger=getattr(previous_service,'ledger',None)
            async def analyze(self,league,*args):
                code=league.upper()
                if code in europe_services:
                    return await asyncio.wait_for(europe_services[code].analyze(code,*args),timeout=45)
                return await previous_service.analyze(league,*args)
        app.bot_data['verified_analysis_service']=EuropeanDispatch()
        app.bot_data['ledger_reports']=EuropeanReportRouter(app.bot_data['ledger_reports'],europe_readers)
    app.bot_data['europe_services']=europe_services
    app.bot_data['europe_prediction_reports']=europe_readers
    prior_market_service=app.bot_data['verified_analysis_service']
    class EuroLeagueMarketDisplay:
        ledger=getattr(prior_market_service,'ledger',None)
        async def analyze(self,league,*args):
            report=await prior_market_service.analyze(league,*args)
            if league.upper()!='EUROLEAGUE' or report.get('status') not in ('FROZEN_REPLAY_OK','FORWARD_EUROLEAGUE_OK'):
                return report
            try:
                from hybrid_engine.market_panels import euroleague_panel
                panel=await asyncio.wait_for(asyncio.to_thread(euroleague_panel,report,archive,market_store,forward_registry=forward_el),timeout=5)
                if panel:
                    from hybrid_engine.elite_render import split_blocks
                    return dict(report,html_parts=[*report['html_parts'],*split_blocks(panel.splitlines(),limit=3200)])
            except Exception as exc:
                logging.getLogger(__name__).warning('EuroLeague market panel unavailable: %s',type(exc).__name__)
            return report
    app.bot_data['verified_analysis_service']=EuroLeagueMarketDisplay()
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
        if mode not in ('all','nba','euroleague','eurocup','roster'):
            await message.reply_text('Kullanım: /test, /test nba, /test euroleague, /test eurocup, /test roster, /test all')
            raise ApplicationHandlerStop
        lines=['ZEYNAL | İZOLE TEST BOTU | ÜRETİM DEĞİL',
            'Telegram komut alımı: OK',
            'Yetkili sohbet: OK',
            'Bu yanıtın teslimi Telegram üzerinden kontrol edilmelidir.']
        for code in ('EUROLEAGUE','EUROCUP'):
            if mode in ('all',code.lower()):
                lines.append(code+' yeni tahmin servisi: '+('AÇIK; model ve kaynak her istekte doğrulanır' if code in europe_services else 'DEVRE DIŞI; arşiv listeleme açıktır'))
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
        if mode in ('all','roster'):
            packets=app.bot_data.get('verified_roster_packets')
            reports=app.bot_data.get('premium_reports')
            lines.append('Kadro kanıt paketleri (bellek): '+str(len(packets) if isinstance(packets,dict) else 0))
            lines.append('Premium analiz oturumları (bellek): '+str(len(reports) if isinstance(reports,dict) else 0))
            lines.append('Oyuncu kimliği / rapor içeriği / Telegram kadro teslimi: bu komutla doğrulanmaz.')
        registered=[group for group,handlers in app.handlers.items() for handler in handlers if 'predictions' in getattr(handler,'commands',())]
        lines.append('/predictions handler grupları: '+str(registered))
        lines.append('Listeleyici sürümü: '+getattr(app.bot_data.get('predictions_command'),'version','YAPILANDIRILMADI'))
        lines.append('Bu kontrol maç tahmini, gerçek fikstür veya Fly.io dağıtımını doğrulamaz.')
        await message.reply_text('\n'.join(lines))
        raise ApplicationHandlerStop
    from telegram.ext import CommandHandler, CallbackQueryHandler
    from hybrid_engine.analyze_input import AnalyzeInputGuard
    app.add_handler(CommandHandler('analyze',AnalyzeInputGuard(chat_id).handle),group=-60)
    async def isolated_fixtures(update,context):
        from nba_command import parse_nba_date
        from hybrid_engine.fixture_menu import nba_blocks,euroleague_blocks
        from datetime import datetime,timezone
        command=(update.effective_message.text or '').split()[0].split('@')[0].lower()
        try:
            day=parse_nba_date(context.args or [],datetime.now(timezone.utc))
            code=command[1:].upper()
            if code in europe_services:
                parts=await asyncio.to_thread(europe_services[code].fixture_blocks,day)
            elif command=='/euroleague':
                receipt=await asyncio.to_thread(fetch,'EUROLEAGUE_LIVE',OFFICIAL)
                parts=euroleague_blocks(receipt,day)
            else:
                games=await app.bot_data['nba_fixture_loader'](day)
                parts=nba_blocks(games,day)
            for part in parts:await update.effective_message.reply_text(part,parse_mode='HTML',disable_web_page_preview=True)
        except (ValueError,KeyError,TypeError,OSError):
            await update.effective_message.reply_text('Fikstür kaynağı doğrulanamadı veya tarih geçersiz. Kullanım: '+command+' YYYY-MM-DD. Tahmin üretilmedi.')
        raise ApplicationHandlerStop
    from hybrid_engine.predictions_command import PredictionsCommand
    from ledger_reports import LedgerReports
    predictions=PredictionsCommand(LedgerReports(nba_service.ledger.path) if nba_service is not None else None,journal,chat_id,league_reports=europe_readers)
    app.bot_data['predictions_command']=predictions
    app.add_handler(CommandHandler('predictions',predictions.handle),group=-50)
    from hybrid_engine.health_command import HealthCommand
    health_command=HealthCommand(predictions.reports,journal,chat_id)
    app.bot_data['health_command']=health_command
    app.add_handler(CommandHandler('health',health_command.handle),group=-50)
    if nba_service is not None:app.add_handler(CommandHandler('nba',isolated_fixtures),group=-50)
    if forward_el is not None or 'EUROLEAGUE' in europe_services:app.add_handler(CommandHandler('euroleague',isolated_fixtures),group=-50)
    if 'EUROCUP' in europe_services:app.add_handler(CommandHandler('eurocup',isolated_fixtures),group=-50)
    async def premium_callback(update,context):
        query=update.callback_query
        if query is None or update.effective_chat is None or update.effective_chat.id!=chat_id:
            return
        data=query.data or ''
        parts=data.split(':')
        if len(parts) not in (3,4) or parts[0]!='zui':
            return
        _,token,section=parts[:3]
        page=int(parts[3]) if len(parts)==4 and parts[3].isascii() and parts[3].isdigit() else 0
        cache=app.bot_data.get('premium_reports',{})
        entry=cache.get(token)
        if entry is None or entry['chat_id']!=chat_id:
            await query.answer('Bu raporun oturumu sona erdi. /analyze ile tekrar açın.',show_alert=True)
            return
        if section!='summary' and section not in entry['sections']:
            await query.answer('Bölüm bulunamadı.',show_alert=True)
            return
        from hybrid_engine.telegram_premium_ui import keyboard,page_view
        answered=False
        if section=='roster' and page==0 and entry.get('roster_context'):
            await query.answer('Güncel kaynaklar kontrol ediliyor…')
            answered=True
            reviewer=app.bot_data.get('current_roster_review')
            if reviewer is not None:
                try:
                    from hybrid_engine.current_roster import render_review
                    review=await asyncio.wait_for(asyncio.to_thread(reviewer.review,entry['roster_context']),timeout=20)
                    if review['original_snapshot_sha256']!=entry['roster_context']['original_snapshot_sha256']:
                        raise ValueError('ROSTER_REVIEW_CONTEXT_CONFLICT')
                    current=render_review(review)
                    from hybrid_engine.player_shadow import render_status as render_player_status
                    current+='\n\n'+await asyncio.to_thread(render_player_status,root/'player-shadow')
                    from hybrid_engine.elite_render import split_blocks
                    from hybrid_engine.telegram_premium_ui import cache_report
                    entry=dict(entry,sections=dict(entry['sections']),section_pages=dict(entry['section_pages']))
                    entry['sections']['roster']=current+'\n\n'+entry['original_roster_html']
                    entry['section_pages']['roster']=split_blocks(entry['sections']['roster'].splitlines(),limit=3200)
                    entry['roster_review_at_utc']=review['observed_at_utc']
                    entry['roster_valid_until_utc']=review.get('valid_until_utc',review['observed_at_utc']+300)
                    cache_report(cache,token,entry)
                except Exception as exc:
                    logging.getLogger(__name__).warning('Current roster review unavailable: %s',type(exc).__name__)
                    await query.edit_message_text('Güncel kadro kaynağı denetlenemedi veya süre aşıldı. '
                        'Bu, sakat/cezalı oyuncu yok demek değildir. İlk tahmin değiştirilmedi.',
                        reply_markup=keyboard(token))
                    return
        try:
            body,page_count=page_view(entry,section,page,now=int(time.time()))
        except ValueError:
            await query.answer('Sayfa bulunamadı. Bölümü yeniden açın.',show_alert=True)
            return
        if not answered:await query.answer()
        try:
            await query.edit_message_text(body,parse_mode='HTML',
                disable_web_page_preview=True,reply_markup=keyboard(token,section=section,page=page,pages=page_count))
        except Exception as exc:
            if 'Message is not modified' not in str(exc):
                raise
    app.add_handler(CallbackQueryHandler(premium_callback,pattern=r'^zui:[0-9a-f]{12}:(summary|period|market|ranges|audit|roster)(?::[0-9]{1,3})?$'),group=-50)
    app.add_handler(CommandHandler('test',self_test),group=-50)
    app.add_handler(TypeHandler(Update,authorized),group=-100);app.add_error_handler(error)
    return journal,results


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--preflight',action='store_true')
    parser.add_argument('--archive-directory');parser.add_argument('--data-directory');parser.add_argument('--result-poll-seconds',type=int,default=300)
    parser.add_argument('--nba-model');parser.add_argument('--nba-model-sha')
    parser.add_argument('--decision-layer',action='store_true');parser.add_argument('--decision-audit');parser.add_argument('--decision-audit-sha')
    parser.add_argument('--forward-euroleague-directory');parser.add_argument('--forward-nba-ledger')
    parser.add_argument('--europe-directory',help='Isolated EuroLeague/EuroCup registries and offline model directory')
    parser.add_argument('--nba-replay-packet');parser.add_argument('--replay-only',action='store_true')
    args=parser.parse_args();config=configuration(os.environ)
    # Capture dedicated data credentials before blanking the legacy production
    # bootstrap key. Never inject data keys into main.py or its scheduler.
    from hybrid_engine.provider_access import credentials,ProviderAccess
    data_access=ProviderAccess(credentials())
    if args.preflight or config['status']=='NOT_CONFIGURED':
        print(json.dumps(dict(config,data_providers=data_access.configuration())));return
    if not args.archive_directory or not args.data_directory:raise ValueError('ISOLATED_DIRECTORIES_REQUIRED')
    if args.replay_only and (args.nba_model or args.nba_model_sha or args.forward_euroleague_directory or args.forward_nba_ledger or args.europe_directory):
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
                from hybrid_engine.result_poll import poll_once
                def euroleague_results():
                    receipt=transport('EUROLEAGUE_LIVE',OFFICIAL)
                    result=app.bot_data['test_results'].ingest(receipt)
                    if forward_el is not None:
                        from hybrid_engine.forward_nba_results import report_euroleague
                        forward_el.settle(receipt)
                        report_euroleague(forward_el)
                    return result
                jobs=[('EUROLEAGUE',euroleague_results)]
                if forward_nba is not None:
                    from hybrid_engine.forward_nba_results import collect as collect_forward_nba
                    jobs.append(('FORWARD_NBA',lambda:collect_forward_nba(forward_nba,root/'forward-nba-results',fetcher=transport)))
                if nba_service is not None:
                    from hybrid_engine.nba_ledger_settlement import settle as settle_hybrid_nba
                    jobs.append(('LIVE_NBA',lambda:settle_hybrid_nba(nba_service.ledger,fetcher=transport)))
                for code,service in app.bot_data.get('europe_services',{}).items():
                    jobs.append(('EUROPE_HYBRID_'+code,service.collect_results))
                app.bot_data['last_result_poll']=await poll_once(jobs,journal)
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
    provider_bridge=None
    if not args.replay_only:
        from hybrid_engine.provider_bridge import ProviderBridge
        provider_bridge=ProviderBridge(data_access,root/'provider-evidence',
            extended=os.getenv('ZEYNAL_TEST_ODDS_EXTENDED','0')=='1')
    _,results=install_isolated_services(app,archive,root,chat_id=config['chat_id'],transport=transport,nba_service=nba_service,
        decision_layer=args.decision_layer,audit_report=audit_report,nba_replay=nba_replay,replay_only=args.replay_only,forward_el=forward_el,provider_bridge=provider_bridge,
        europe_directory=None if args.replay_only else local_path(args.europe_directory) if args.europe_directory else root/'europe')
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

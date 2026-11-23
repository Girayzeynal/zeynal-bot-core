"""Opt-in isolated Telegram test bot. No production token or user account is used."""
import argparse
import asyncio
from contextvars import ContextVar
import json
import logging
import os
import sqlite3
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
        from concurrent.futures import ThreadPoolExecutor
        self._journal_executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='telegram-journal')
        self.journal_status='NOT_ATTEMPTED'
        # HTTPX INFO request lines contain the Bot API token in the URL path.
        logging.getLogger('httpx').setLevel(logging.ERROR)
        logging.getLogger('httpcore').setLevel(logging.ERROR)
    async def append_journal(self,journal,key,event):
        # Research deliberately has one worker. Accepted HTTP responses and
        # authorized human commands must not queue behind a model fit there.
        from functools import partial
        try:
            await asyncio.wait_for(asyncio.get_running_loop().run_in_executor(
                self._journal_executor,partial(journal.append,key,event)),timeout=2)
        except Exception as exc:
            self.journal_status='UNAVAILABLE'
            logging.getLogger(__name__).warning('Telegram delivery journal unavailable: %s',type(exc).__name__)
            return False
        self.journal_status='WRITTEN'
        return True

    async def shutdown(self):
        try:await super().shutdown()
        finally:self._journal_executor.shutdown(wait=False,cancel_futures=True)

    async def do_request(self,url,method,**kwargs):
        name=url.rsplit('/',1)[-1]
        try:status,body=await super().do_request(url,method,**kwargs)
        except Exception as exc:
            if name=='sendMessage':
                await self.append_journal(self.journal,digest(dict(update=_update.get(),kind='SEND_UNCONFIRMED')),
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
                    bot_id=identity.get('bot_id') if self.identity_verified and official else None,
                    dedicated_bot_identity_verified=self.identity_verified and official,
                    expected_chat_matches=r['chat']['id']==identity.get('chat_id'),
                    response_content_matches_request=(type(parameters.get('text')) is str and
                        plaintext(parameters['text'],parameters.get('parse_mode'))==r.get('text')),
                    response_sha256=digest(data),request_text_sha256=digest(parameters.get('text','')))
                await self.append_journal(self.journal,digest(dict(chat=event['chat_id'],message=event['telegram_message_id'])),event)
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
    # An isolated, render-only cache survives process restarts. Restored pages
    # are marked archival; no model, quote, or roster fetch is replayed.
    if 'premium_reports' not in app.bot_data:
        from hybrid_engine.premium_report_cache import DiskBackedReports
        app.bot_data['premium_reports']=DiskBackedReports(root/'telegram-premium-pages',chat_id)
    # Shared typed evidence gate for NBA and Europe; an empty dict is not a data provider.
    app.bot_data.setdefault('verified_roster_packets',{})
    from hybrid_engine.market_observations import ObservationStore
    market_store=ObservationStore(root/'market-observations')
    app.bot_data['market_observation_store']=market_store
    if nba_service is not None:
        from hybrid_engine.current_roster import CurrentRosterReview
        app.bot_data['current_roster_review']=roster_review or CurrentRosterReview(
            root/'current-roster',report_archive=root/'official-reports',
            bounded_public_pdf_fallback=True)
        # /analyze launches the bounded optional data continuation by itself.
        # Production-only services have no such opt-in. This never edits a
        # stored forecast or introduces uncalibrated player score corrections.
        app.bot_data['auto_nba_player_pipeline']=dict(
            reviewer=app.bot_data['current_roster_review'],
            assets=getattr(nba_service,'assets',None),directory=root/'player-shadow',
            chat_id=chat_id,cooldown_seconds=300)
    from hybrid_engine.isolated_execution import optional_source_thread
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
                    prior=await asyncio.wait_for(optional_source_thread(prior_quality),timeout=2)
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
                market_candidate_snapshot=None
                market_candidate_cards=[]
                if provider_bridge is not None:
                    try:
                        from hybrid_engine.provider_bridge import nba_provider_panel
                        provider_panel=await asyncio.wait_for(
                            optional_source_thread(nba_provider_panel,snapshot,nba_service,provider_bridge,structured=True),timeout=10)
                        market_lines.append(provider_panel['html'])
                        direction_cards.extend(provider_panel['cards'])
                        market_candidate_snapshot=provider_panel.get('market_candidate_snapshot')
                        market_candidate_cards=provider_panel['cards'][:128] if market_candidate_snapshot else []
                    except Exception as exc:
                        logging.getLogger(__name__).warning('Provider review unavailable: %s',type(exc).__name__)
                        market_lines.append('Sağlayıcı denetimi tamamlanamadı: PROVIDER_REVIEW_UNAVAILABLE. Bu durum NO EDGE değildir; skor tahmini korunuyor.')
                market_note=None
                from hybrid_engine.market_panels import nba_panel
                try:
                    panel=await asyncio.wait_for(optional_source_thread(nba_panel,snapshot,nba_service,evidence,market_store),timeout=3)
                    market_lines.append(panel['html'])
                    direction_cards.extend(panel.get('cards',[]))
                    if panel['observations']:
                        market_note=f"Piyasa düğmesinde {panel['observations']} kaynak gözlemi / {panel['lines']} barem; ham model hesabı."
                except Exception as exc:
                    logging.getLogger(__name__).warning('Market source panel unavailable: %s',type(exc).__name__)
                    market_lines.append('Piyasa kaynak/dağılım denetimi tamamlanamadı; skor tahmini korunuyor. Kod: MARKET_PANEL_UNAVAILABLE')
                response=dict(response)
                from hybrid_engine.telegram_premium_ui import (
                    compact_summary,keyboard,detail_sections,direction_card_matches_snapshot)
                import secrets
                token=secrets.token_hex(6)
                from hybrid_engine.market_direction_ui import order,pages as direction_pages
                ranked=order(direction_cards)
                # Later research context may have a different model digest or
                # clock than the immutable first NBA forecast. It is not an
                # original-model direction and must never break /analyze.
                current_totals=[c for c in ranked if c['current'] and
                                c['period']=='FULL' and c['market']=='TOTAL']
                bound_totals=[c for c in current_totals if
                              direction_card_matches_snapshot(snapshot,c)]
                first_total=bound_totals[0] if bound_totals else None
                if len(bound_totals)!=len(current_totals):
                    market_lines.append('Piyasa araştırması farklı model kesiti/zamanıyla hesaplandı; '
                        'ilk skor tahminine güncel model yönü olarak bağlanmadı. '
                        'Piyasa kartları kendi kanıtlarıyla ayrı görüntülenebilir.')
                    logging.getLogger(__name__).info(
                        'NBA current market headline suppressed due to model/clock/mean mismatch: %s',
                        len(current_totals)-len(bound_totals))
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
                if len(bound_totals)!=len(current_totals):
                    market_html=('⚠️ <b>AYRI ARAŞTIRMA MODELİ</b>\n'
                        'Bu piyasa kartının model kesiti/saati ilk tahminle eşleşmedi. '
                        'İlk skor tahminine uygulanmadı; kalibre edilmiş yön değildir.\n\n'
                        +market_html)
                sections=detail_sections(response['html_parts'],market_html,
                                         roster_evidence=roster)
                sections['audit']=render_health(health)+'\n\n'+sections['audit']+'\n\n'+'\n\n'.join(market_lines)
                from hybrid_engine.elite_render import split_blocks
                section_pages={k:split_blocks(v.splitlines(),limit=3200) for k,v in sections.items()}
                if market_pages:
                    section_pages['market']=([market_html,*market_pages[1:]]
                        if len(bound_totals)!=len(current_totals) else market_pages)
                cache=app.bot_data.setdefault('premium_reports',{})
                from hybrid_engine.telegram_premium_ui import cache_report
                expiry=[c['valid_until_utc'] for c in ranked if c['current']]
                entry=dict(summary=summary,sections=sections,section_pages=section_pages,chat_id=chat_id,
                    tipoff_utc=snapshot['fixture_start_utc'],quote_valid_until_utc=min(expiry) if expiry else None,
                    research_market_snapshot=market_candidate_snapshot,
                    research_market_cards=market_candidate_cards)
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
                if not r['live']:return self.frozen.render_accuracy(r['report'])
                original='İZOLE NBA HİBRİT ARAŞTIRMA — ÜRETİM DEĞİL\n'+render_accuracy(r['report'])
                # Include the already computed, separate, prospective model
                # comparison; never refit or call a provider in /accuracy.
                assessments=app.bot_data.get('current_assessments')
                if assessments is not None:
                    original+='\n\n'+assessments.render_performance()
                return original
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
        from hybrid_engine.europe_command_identity import EuropeanCommandService as EuropeanService
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
    if europe_services and not replay_only:
        from hybrid_engine.europe_prematch import EuropeanPrematchScheduler
        app.bot_data['europe_prematch_scheduler']=EuropeanPrematchScheduler(europe_services,root/'europe-prematch')
    app.bot_data['europe_prediction_reports']=europe_readers
    if europe_services:
        from hybrid_engine.europe_data import EuropeanDataReview
        from hybrid_engine.provider_access import ProviderAccess
        from hybrid_engine.provider_bridge import ProviderBridge
        # Reuse the already configured, quota-limited isolated credentials.
        european_bridge=provider_bridge or ProviderBridge(ProviderAccess({}),root/'europe-provider-evidence')
        from hybrid_engine.europe_native_roster_source import fetch_native
        # Opt-in only: a commercial provider must NEVER be queried merely
        # because a key exists. No provider key enters bot_data or reports.
        # Security hold: do not instantiate RotoWire even if old private
        # environment variables remain set. The official roster source
        # and Telegram UI must continue to function without this provider.
        advisory_getter=None
        app.bot_data['europe_injury_advisory_setup_status']='SECURITY_HOLD_ROTOWIRE'
        app.bot_data['europe_injury_advisory_enabled']=False
        from hybrid_engine.europe_injury_public_sources import PublicEuroInjuryNewsHub
        # Anonymous public indexes only; opt-in and robots-gated, no secret.
        public_news=PublicEuroInjuryNewsHub(
            enabled=os.getenv('ZEYNAL_PUBLIC_EURO_NEWS_ENABLED','0')=='1')
        app.bot_data['europe_public_injury_news_hub']=public_news
        app.bot_data['europe_data_review']=EuropeanDataReview(europe_services,european_bridge,root/'europe-data',
            roster_store=app.bot_data['verified_roster_packets'],native_roster_getter=fetch_native,
            injury_advisory_getter=advisory_getter,public_news_hub=public_news)
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
    # Same authenticated/paginated callbacks as NBA; European engine files and
    # prepared-model pins remain unchanged. All work here is presentation-only.
    european_plain_service=app.bot_data['verified_analysis_service']
    class EuropeanPremiumDisplay:
        ledger=getattr(european_plain_service,'ledger',None)
        async def analyze(self,league,*args):
            report=await european_plain_service.analyze(league,*args)
            code=league.upper()
            from hybrid_engine.europe_premium_ui import present,SUPPORTED
            if code not in europe_services or report.get('status') not in SUPPORTED:
                return report
            try:
                cache=app.bot_data.setdefault('premium_reports',{})
                displayed=await asyncio.wait_for(asyncio.to_thread(present,report,code,cache,chat_id,
                    service=europe_services.get(code),
                    forward_service=live_el if forward_el is not None else None,
                    roster_store=app.bot_data.get('verified_roster_packets')),timeout=10)
                app.bot_data.setdefault('last_europe_presentation',{})[code]=dict(status='READY',version=displayed['presentation_version'])
                return displayed
            except Exception as exc:
                logging.getLogger(__name__).warning('European presentation unavailable: %s',type(exc).__name__)
                app.bot_data.setdefault('last_europe_presentation',{})[code]=dict(status='UNAVAILABLE',error_type=type(exc).__name__)
                return dict(report,html_parts=[*(report.get('html_parts') or [report['html']]),
                    'Detay düğmeleri hazırlanamadı; kayıtlı tahmin korunuyor. Kod: EUROPE_UI_UNAVAILABLE'])
    app.bot_data['verified_analysis_service']=EuropeanPremiumDisplay()
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
                if league.upper()=='NBA':
                    if replay_only or nba_service is None:
                        return await nba_replay.analyze(league,day,home,away)
                    if nba_replay.has_pair(home,away):
                        replay=await nba_replay.analyze(league,day,home,away)
                        # The same teams may meet again on another date. A static
                        # replay's date mismatch must not hide a live original.
                        if replay.get('status')=='NBA_ARCHIVE_REPLAY_OK':return replay
                return await base.analyze(league,day,home,away)
        app.bot_data['verified_analysis_service']=ReplayDispatch()
    fetch=transport or ControlledTransport(fetch_document)
    app.bot_data['nba_fixture_loader']=nba_replay.list_nba_games if replay_only else VerifiedAnalyzeService(None,fetcher=fetch).list_nba_games
    if nba_service is not None and not replay_only:
        from hybrid_engine.nba_overnight import NBAOvernightScheduler,LiveNBAHybridService
        if isinstance(nba_service,LiveNBAHybridService):
            app.bot_data['nba_overnight_scheduler']=NBAOvernightScheduler(nba_service,app.bot_data['nba_fixture_loader'],
                root/'nba-overnight',root/'challenger-research'/'protocol')
    if not replay_only and (europe_services or app.bot_data.get('nba_overnight_scheduler')):
        from hybrid_engine.adaptive_worker import AdaptiveWorker
        from hybrid_engine.research_protocol_namespace import namespace
        from hybrid_engine.adaptive_research import POLICY as V2_POLICY, source_pins as v2_pins
        adaptive_protocol=namespace(root,'adaptive-v2',policy=V2_POLICY,source_pins=v2_pins())
        app.bot_data['adaptive_v2_worker']=AdaptiveWorker(root/'adaptive-v2',
            nba=nba_service if app.bot_data.get('nba_overnight_scheduler') else None,europe=europe_services,
            fetcher=transport or fetch_document,research_directory=adaptive_protocol)
        if app.bot_data['adaptive_v2_worker'].nba is not None:
            from hybrid_engine.native_fixture_recheck import NativeFixtureRecheck
            recheck=NativeFixtureRecheck(app.bot_data['adaptive_v2_worker'].transport)
            app.bot_data['adaptive_v2_worker'].verify=recheck.verify
            app.bot_data['native_fixture_recheck']=recheck
            from hybrid_engine.issue90_research import Research, POLICY as V3_POLICY, pins as v3_pins
            from hybrid_engine.research_diagnostics import ObservedResearch
            v3_protocol=namespace(root,'nba-v3',policy=V3_POLICY,source_pins=v3_pins())
            app.bot_data['issue90_research']=ObservedResearch(Research(v3_protocol,app.bot_data['adaptive_v2_worker']))
        from hybrid_engine.current_assessment import CurrentAssessments, POLICY as ASSESS_POLICY
        from hybrid_engine.issue90_research import pins as assessment_pins
        from hybrid_engine.research_diagnostics import ResearchCycle
        # The current-assessment implementation is itself part of the
        # experiment identity; V3's inherited pins do not cover this module.
        import hashlib as _protocol_hashlib
        assessment_source_pins=dict(assessment_pins())
        assessment_source_pins['current_assessment_module_sha256']=_protocol_hashlib.sha256(
            (Path(__file__).parent/'current_assessment.py').read_bytes()).hexdigest()
        assessment_protocol=namespace(root,'current-assessment',policy=ASSESS_POLICY,
                                      source_pins=assessment_source_pins)
        assessments=CurrentAssessments(assessment_protocol,app.bot_data['adaptive_v2_worker'],app.bot_data.get('issue90_research'))
        app.bot_data['research_protocol_directories']=dict(
            adaptive_v2=str(adaptive_protocol),nba_v3=str(v3_protocol) if app.bot_data['adaptive_v2_worker'].nba is not None else None,
            current_assessment=str(assessment_protocol))
        app.bot_data['current_assessments']=assessments
        app.bot_data['research_cycle']=ResearchCycle(app.bot_data['adaptive_v2_worker'],app.bot_data.get('issue90_research'),assessments)
        for bridge in (provider_bridge,getattr(app.bot_data.get('europe_data_review'),'bridge',None)):
            if bridge is not None:bridge.assessments=assessments
        from hybrid_engine.current_assessment_ui import install_dual_clock_display
        install_dual_clock_display(app.bot_data,assessments)
    async def journal_write(key,event):
        request=app.bot.request
        if isinstance(request,AuditedRequest):return await request.append_journal(journal,key,event)
        await asyncio.to_thread(journal.append,key,event)
        return True

    async def authorized(update,context):
        if update.effective_chat is None or update.effective_chat.id!=chat_id:raise ApplicationHandlerStop
        _update.set(update.update_id)
        message=update.effective_message
        if message and message.text:
            try:command_bot_id=getattr(getattr(context,'bot',None),'id',None)
            except RuntimeError:command_bot_id=None
            await journal_write('received:'+str(update.update_id),dict(kind='COMMAND_RECEIVED',update_id=update.update_id,
                command=message.text.split()[0].split('@')[0],chat_id=update.effective_chat.id,
                bot_id=command_bot_id,
                request_sha256=digest(message.text),
                is_bot=getattr(update.effective_user,'is_bot',None),
                user_message_at_utc=int(message.date.timestamp()),received_at_utc=int(time.time())))
    async def error(update,context):
        await journal_write(digest(dict(update=getattr(update,'update_id',None),kind='HANDLER_ERROR')),
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
        if mode not in ('all','nba','euroleague','eurocup','roster','research','data','runtime','integrations','engines','predictions','playerimpact'):
            await message.reply_text('Kullanım: /test, /test nba, /test euroleague, /test eurocup, /test roster, /test research, /test data, /test runtime, /test integrations, /test predictions, /test all')
            raise ApplicationHandlerStop
        lines=['ZEYNAL | İZOLE TEST BOTU | ÜRETİM DEĞİL',
            'Telegram komut alımı: OK',
            'Yetkili sohbet: OK',
            'Bu yanıtın teslimi Telegram üzerinden kontrol edilmelidir.']
        from hybrid_engine.integrated_features import RELEASE
        lines.extend(['İşlev sürümü: '+RELEASE,'Etkin bileşenler: /features · Ayrı model skorları: /models NBA MAÇ_KİMLİĞİ'])
        if mode=='predictions':
            command=app.bot_data.get('predictions_command');last=getattr(command,'last_send',None) or {}
            read=getattr(command,'last_read',None) or {};kind=getattr(command,'last_response_kind',None)
            kinds={'PREDICTION_LIST':'TAHMİN LİSTESİ','ERROR_NOTICE':'HATA BİLDİRİMİ','USAGE':'KULLANIM BİLGİSİ'}
            lines.extend(['Arşiv okuma durumu: '+read.get('status','HENÜZ_GÖZLENMEDİ'),
                'Arşiv okuma hata kodu: '+str(read.get('error_code') or 'YOK'),
                'Okuma sınırı (sn): '+str(read.get('deadline_seconds','?')),
                'Gönderilen yanıt: '+kinds.get(kind,'HENÜZ_GÖZLENMEDİ'),
                'Tahmin listesi teslimi: '+('GÖNDERİLDİ' if kind=='PREDICTION_LIST' and last.get('status')=='SENT' else 'DOĞRULANMADI'),
                'Yanıt mesajı gönderimi: '+last.get('status','HENÜZ_GÖZLENMEDİ'),
                'Tamamlanan bölüm: '+str(last.get('sent',0))+'/'+str(last.get('parts',0)),
                'Gönderim sınıfı: '+str(last.get('error_code') or 'YOK'),
                'Teslim kayıt durumu: '+getattr(app.bot.request,'journal_status','BU_TAŞIMADA_İZLENMİYOR')])
            if read:
                now=time.monotonic();started=read.get('started_at')
                queue=(started or now)-read['queued_at']
                lines.append(f'İşçi kuyruğunda bekleme (sn): {max(0,queue):.2f}')
                lines.append('Arşiv doğrulama süresi (sn): '+
                    ('henüz başlamadı' if started is None else f"{max(0,(read.get('finished_at') or now)-started):.2f}"))
        if mode=='playerimpact':
            from hybrid_engine.predictions_command import split_plain
            path=root/'player-effect-smoke.json'
            record=dict(format='NBA_PLAYER_IMPACT_TEST_STATUS_V1',
                mode='SYNTHETIC_AND_LIVE_ARE_SEPARATE',
                training_in_telegram=False,production_changed=False,
                original_forecasts_changed=False,
                live_fixture_player_model_status='BLOCKED_UNLESS_PROSPECTIVE_EVIDENCE_EXISTS')
            worker=app.bot_data.get('adaptive_v2_worker')
            progress=getattr(worker,'progress',{}) if worker else {}
            # Actual /analyze automation is NOT the old adaptive research
            # worker. Report both independently rather than masking a real
            # execution with the worker's NO_ATTEMPT_OBSERVED default.
            automatic=app.bot_data.get('auto_nba_last_attempt')
            record['automatic_nba_data_collection']=(
                dict(automatic) if isinstance(automatic,dict)
                else dict(status='NO_ANALYZE_TRIGGER_OBSERVED_IN_THIS_BOT_PROCESS'))
            record['live_player_minutes_status']=(
                automatic.get('player_input_status','NOT_STARTED')
                if isinstance(automatic,dict) else 'NO_AUTOMATIC_ANALYZE_TRIGGER_OBSERVED')
            record['legacy_worker_player_input_status']=(
                progress.get('player_input_status','NO_ATTEMPT_OBSERVED')
                if isinstance(progress,dict) else 'NOT_OBSERVED')
            record['live_player_model_coefficients_applied']=False
            # Verify the REAL archived inputs separately from the synthetic
            # smoke. A roster row or a made-up injury never counts as a
            # prospective training example.
            try:
                from hybrid_engine.player_shadow import readiness as player_readiness
                actual=await asyncio.wait_for(asyncio.to_thread(
                    player_readiness,root/'player-shadow'),timeout=5)
                record['real_player_inputs']=dict(
                    status=actual['status'],
                    prospective_minutes_games=actual['prospective_minutes_games'],
                    rejected_inputs=actual['rejected_inputs'],
                    prepared_artifacts=actual['prepared_artifacts'],
                    offline_fit_target_games=actual['minimum_fit_games'],
                    calibration_status=actual['calibration_status'],
                    production_enabled=actual['production_enabled'])
            except (ValueError,KeyError,TypeError,OSError,asyncio.TimeoutError):
                record['real_player_inputs']=dict(status='READ_UNAVAILABLE_NOT_VERIFIED')
            # Source-attempt evidence is kept separate from synthetic smoke and
            # only names the actual rejected constraints, never player diagnoses.
            try:
                from hybrid_engine.player_inputs import recent_collection_diagnostics
                record['latest_real_collection_attempts']=await asyncio.wait_for(
                    asyncio.to_thread(recent_collection_diagnostics,root/'player-shadow'),timeout=3)
            except (ValueError,KeyError,TypeError,OSError,asyncio.TimeoutError):
                record['latest_real_collection_attempts']=dict(
                    status='READ_UNAVAILABLE_NOT_VERIFIED',read_only=True)
            record['europe_player_score_models']='NOT_VERIFIED_BY_NBA_SYNTHETIC_SMOKE'
            if not path.is_file() or path.is_symlink() or path.stat().st_size>18000:
                record['synthetic_demo']='NOT_RUN'
                record['next_step']='UserLAnd: bash scripts/run_isolated_test_bot.sh --player-effect-smoke'
            else:
                try:
                    wrapped=json.loads(path.read_text())
                    p=wrapped['payload']
                    if (wrapped['sha256']!=digest(p) or
                            p['format']!='NBA_SYNTHETIC_PLAYER_EFFECT_SMOKE_V1' or
                            p['input_classification']!='FULLY_MANUFACTURED_TEST_GAMES_AND_INJURY' or
                            p['original_forecasts_changed'] is not False or
                            p['production_enabled'] is not False or
                            p['network_requests_made']!=0 or
                            p['evidence_is_real_game'] is not False or
                            p['player_effect_is_live'] is not False):
                        raise ValueError('SYNTHETIC_PLAYER_REPORT_PIN_OR_SCOPE')
                    record.update(synthetic_demo=p['status'],
                        synthetic_fit_games=p['synthetic_fit_games'],
                        fake_missing_player=p['simulated_injury'],
                        minute_conservation=dict(before=p['home_rotation_minutes_before'],
                            after=p['home_rotation_minutes_after']),
                        missing_player_minutes=dict(before=p['missing_player_minutes_before'],
                            after=p['missing_player_minutes_after']),
                        replacement_minutes=p['replacement_minutes_top4'],
                        team_control=p['TEAM_BAYES_CONTROL'],
                        player_bayes_before=p['PLAYER_BAYES_BEFORE'],
                        player_bayes_after=p['PLAYER_BAYES_AFTER'],
                        player_bayes_delta=p['PLAYER_BAYES_DELTA'],
                        score_sensitivity_observed=p['score_sensitivity_observed'],
                        warning='SENTETIK_TEST; GERCEK_MAC_OYUNCU_ETKISI_DEGIL')
                except (ValueError,KeyError,TypeError,UnicodeError,OSError):
                    record['synthetic_demo']='INVALID_OR_UNVERIFIED_TEST_REPORT'
            for part in split_plain(json.dumps(record,ensure_ascii=False,indent=2),limit=3200):
                await message.reply_text(part,parse_mode=None)
            raise ApplicationHandlerStop
        if mode=='engines':
            from hybrid_engine.active_engine_status import describe as engine_status
            from hybrid_engine.predictions_command import split_plain
            report=await asyncio.to_thread(engine_status,app.bot_data,root)
            for part in split_plain(json.dumps(report,ensure_ascii=False,indent=2),limit=3200):
                await message.reply_text(part,parse_mode=None)
            raise ApplicationHandlerStop
        if mode=='integrations':
            from hybrid_engine.production_parity import runtime_command
            await runtime_command(update,context)
            raise ApplicationHandlerStop
        if mode=='runtime':
            from hybrid_engine.runtime_identity import describe
            from hybrid_engine.elite_render import split_blocks
            value=json.dumps(describe(app.bot_data),ensure_ascii=False,indent=2)
            for part in split_blocks(value.splitlines(),limit=3200):await message.reply_text(part,parse_mode=None)
            raise ApplicationHandlerStop
        if mode in ('all','data'):
            lines.extend(['VERİ / MODEL BAĞLANTISI',
                'Ana skor: kayıtlı tahmin veya sabit parametreli takım modeli.',
                'V2/V3 adayları ayrı araştırmadır; otomatik ana model değişimi yok.',
                'Piyasa ve Kadro düğmeleri mevcut skor hesabını güncellemez.',
                'Avrupa kadro kaynağı: resmî haber metni; doğrulanmış oyuncu durum akışı değil.'])
            bridge=provider_bridge or getattr(app.bot_data.get('europe_data_review'),'bridge',None)
            if bridge is not None:
                for provider,state in bridge.access.runtime_status().items():
                    remaining=state['provider_reported_remaining']
                    lines.append(provider+': yerel istek '+str(state['local_calls_today'])+'/'+str(state['local_daily_limit'])+
                        ' · sağlayıcının bildirdiği kalan '+('bilinmiyor' if remaining is None else str(remaining)))
                usage=await asyncio.to_thread(bridge.storage_status)
                lines.append('Yerel sağlayıcı kanıtı: '+str(usage['files'])+'/'+str(usage['maximum_files'])+' belge · '+usage['status'])
        worker=app.bot_data.get('adaptive_v2_worker')
        if worker and mode in ('all','research'):
            lines.extend(worker.render().splitlines())
            recheck=app.bot_data.get('native_fixture_recheck')
            if recheck:
                info=recheck.identity()
                lines.extend(['NBA fikstür yeniden kontrolü: ESPN · '+info['calendar'],
                    'Kaynak adaptörü: '+info['format']+' · '+info['policy_sha256'][:12],
                    'UTC maç saati ve tam native kimlik/durum kontrolleri korunur.'])
            study=app.bot_data.get('issue90_research')
            if study:lines.extend(study.render().splitlines())
            cycle=app.bot_data.get('research_cycle')
            if cycle:lines.extend(cycle.render().splitlines())
            assessments=app.bot_data.get('current_assessments')
            if assessments:
                last=assessments.last_report or {}
                lines.append('Güncel analiz zinciri: '+last.get('status','İLK TUR BEKLENİYOR'))
                lines.append('Son turda yeni aday yayınlama: '+str(last.get('candidate_published_count','BİLİNMİYOR'))+
                    ' · Denenen '+str(last.get('capture_attempt_count','?'))+
                    ' · Uygun sırada '+str(last.get('eligible_not_yet_saved_count','?')))
                if last.get('requested_fixture_id'):
                    lines.append('Talep edilen maç kimliği: '+str(last['requested_fixture_id'])[:100])
                    lines.append('Talep edilen maçın üretim sonucu: '+
                        str(last.get('requested_fixture_status','BİLİNMİYOR')))
                for capture in (last.get('captures') or [])[:3]:
                    lines.append('Aday kaydı: '+str(capture.get('fixture_id','KİMLİK_YOK'))[:100]+
                        ' · '+str(capture.get('status','BİLİNMİYOR'))+
                        (' · Engeli: '+str(capture.get('reason','BELİRTİLMEDİ'))[:90]
                         if capture.get('status')=='ABSTAIN' else ''))
                if cycle:
                    lines.append('Gelecek tur öncelikli maç: '+
                        (', '.join(cycle.requested_fixtures[:3]) if cycle.requested_fixtures else 'YOK'))
                lines.extend(assessments.render_performance().splitlines())
            bridge=provider_bridge or getattr(app.bot_data.get('europe_data_review'),'bridge',None)
            if bridge is not None and getattr(bridge,'rule_book',None):
                lines.append('Piyasa ödeme kuralı makbuzları: '+bridge.rule_book.status())
        overnight=app.bot_data.get('nba_overnight_scheduler')
        if mode in ('all','nba') and overnight:
            lines.append('NBA otomatik PREMATCH: AÇIK · gelecek 36 saat · son 15 dk yeni kayıt yok')
            lines.append('Kabul deneyi kaydı otomatik; gece komut vermek veya botu durdurmak gerekmez.')
            last=app.bot_data.get('last_nba_overnight_poll') or overnight.last_report or {}
            lines.append('Son NBA otomatik kontrol: '+str(last.get('status','HENÜZ_ÇALIŞMADI')))
            progress=last.get('progress') or {}
            lines.append('İleri deney: '+str(progress.get('status','HENÜZ_DOĞRULANMADI'))+
                ' · Sonuçlu '+str(progress.get('settled','?'))+' · Bekleyen '+str(progress.get('pending','?')))
            if progress.get('protocol_sha256'):lines.append('Korunan plan SHA: '+progress['protocol_sha256'][:12])
            skipped=(last.get('acceptance') or {}).get('skipped',{})
            if skipped.get('ORIGINAL_INPUTS_TOO_OLD_FOR_PROTOCOL'):
                lines.append('Eski girdili '+str(skipped['ORIGINAL_INPUTS_TOO_OLD_FOR_PROTOCOL'])+' tahmin kabul deneyine alınmadı; ilk kayıtlar korundu.')
            for group in progress.get('groups',[]):
                lines.append('Aynı kohortta eşleşmiş maç: '+str(group['matched'])+'/100 · Farklı maç günü: '+str(group['day_clusters'])+'/20')
        for code in ('EUROLEAGUE','EUROCUP'):
            if mode in ('all',code.lower()):
                lines.append(code+' yeni tahmin servisi: '+('AÇIK; model ve kaynak her istekte doğrulanır' if code in europe_services else 'DEVRE DIŞI; arşiv listeleme açıktır'))
                if code in europe_services:
                    from hybrid_engine.europe_command_identity import VERSION as alias_version
                    from hybrid_engine.europe_premium_ui import VERSION as ui_version
                    lines.append('Takım adı adaptörü: '+alias_version)
                    lines.append('Düğmeli arşiv görünümü: '+ui_version)
                    last=app.bot_data.get('last_europe_presentation',{}).get(code,{})
                    lines.append('Son görünüm kontrolü: '+last.get('status','HENÜZ_ÇALIŞMADI')+
                                 (' · '+last['error_type'] if last.get('error_type') else ''))
        if mode in ('all','euroleague','eurocup') and app.bot_data.get('europe_prematch_scheduler'):
            lines.append('Avrupa otomatik PREMATCH: AÇIK · gelecek 36 saat · son 15 dk yeni kayıt yok')
            lines.append('EuroLeague / EuroCup için maç saatinde ek komut gerekmiyor.')
            last=app.bot_data.get('last_europe_prematch_poll',{})
            lines.append('Son otomatik kontrol: '+str(last.get('status','HENÜZ_ÇALIŞMADI')))
        if mode in ('all','euroleague'):
            try:
                count=len(archive.records)
                lines.append(f'EuroLeague doğrulanmış arşiv kaydı: {count}')
                lines.append('EuroLeague arşiv: OK' if count else 'EuroLeague arşiv: BOŞ')
            except (AttributeError,TypeError,ValueError,OSError) as exc:
                lines.append('EuroLeague arşiv: HATA ('+type(exc).__name__+')')
        if mode in ('all','nba'):
            try:
                if nba_service is not None:
                    from hybrid_engine.results_health import inspect as inspect_results,render as render_results
                    health=await asyncio.to_thread(inspect_results,nba_service.ledger.path)
                    lines.extend(render_results(health,app.bot_data.get('last_result_poll')).splitlines())
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
        from hybrid_engine.elite_render import split_blocks
        for part in split_blocks(lines,limit=3200):await message.reply_text(part.replace('\n\n','\n'),parse_mode=None)
        raise ApplicationHandlerStop
    from telegram.ext import CommandHandler, CallbackQueryHandler
    async def research_command(update,context):
        args=context.args or [];worker=app.bot_data.get('adaptive_v2_worker')
        if not worker or len(args)>2 or (args and args[0].upper() not in ('NBA','EUROLEAGUE','EUROCUP')):
            await update.effective_message.reply_text('Kullanım: /research [NBA|EUROLEAGUE|EUROCUP] [maç_kimliği]. İzole V2 araştırma servisi gerekli.')
        else:
            try:
                value=await asyncio.to_thread(worker.render,args[0].upper() if args else None,args[1] if len(args)>1 else None)
                from hybrid_engine.elite_render import split_blocks
                for part in split_blocks(value.splitlines(),limit=3200):await update.effective_message.reply_text(part,parse_mode=None)
            except (ValueError,KeyError,TypeError,OSError):
                await update.effective_message.reply_text('V2 araştırma arşivi doğrulanamadı. Eski tahminler korunuyor.')
        raise ApplicationHandlerStop
    app.add_handler(CommandHandler('research',research_command),group=-50)
    async def feature_command(update,context):
        if update.effective_chat is None or update.effective_chat.id!=chat_id:return
        from hybrid_engine.integrated_features import features
        from hybrid_engine.predictions_command import split_plain
        for part in split_plain(features(app.bot_data),limit=3200):
            await update.effective_message.reply_text(part,parse_mode=None)
        raise ApplicationHandlerStop
    async def model_command(update,context):
        if update.effective_chat is None or update.effective_chat.id!=chat_id:return
        from hybrid_engine.integrated_features import models
        from hybrid_engine.predictions_command import split_plain
        args=context.args or []
        if len(args)!=2 or args[0].upper() not in ('NBA','EUROLEAGUE','EUROCUP'):
            value='Kullanım: /models NBA|EUROLEAGUE|EUROCUP MAÇ_KİMLİĞİ'
        else:
            try:value=await asyncio.to_thread(models,app.bot_data,args[0].upper(),args[1])
            except (ValueError,KeyError,TypeError,OSError,sqlite3.Error):
                value='Ayrı model kaydı doğrulanamadı. Kayıtlı ana tahmin korunuyor; /test research ile kaynak durumunu kontrol edin.'
        for part in split_plain(value,limit=3200):await update.effective_message.reply_text(part,parse_mode=None)
        raise ApplicationHandlerStop
    from hybrid_engine.europe_native_roster_source import command_handler as player_source_handler
    app.add_handler(player_source_handler(),group=-50)
    app.add_handler(CommandHandler('features',feature_command),group=-50)
    # Same on-demand read-only public club/news command on test and production.
    from hybrid_engine.production_parity import injurynews_command
    app.add_handler(CommandHandler('injurynews',injurynews_command),group=-50)
    app.add_handler(CommandHandler('models',model_command),group=-50)
    from hybrid_engine.runtime_identity import install as observe_analysis
    observe_analysis(app.bot_data)
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
    predictions=PredictionsCommand(LedgerReports(nba_service.ledger.path) if nba_service is not None else None,journal,chat_id,
        league_reports=europe_readers,journal_writer=journal_write)
    app.bot_data['predictions_command']=predictions
    app.add_handler(CommandHandler('predictions',predictions.handle),group=-50)
    from hybrid_engine.unified_results_view import LEAGUES,render_all,render_performance
    from hybrid_engine.predictions_command import split_plain
    async def _three_league_reports():
        reader=app.bot_data['ledger_reports']
        result={}
        for code in LEAGUES:
            result[code]=await asyncio.to_thread(reader.read,code,None)
        return result
    async def results_all_command(update,context):
        """All archived fixtures; never fetches or settles results on demand."""
        if update.effective_chat is None or update.effective_chat.id!=chat_id:
            return
        args=[x.lower() for x in (context.args or [])]
        if args not in ([],['all']):
            await update.effective_message.reply_text('Kullanım: /results all')
            raise ApplicationHandlerStop
        try:
            reports=await _three_league_reports()
            value=await asyncio.to_thread(render_all,reports,now=int(time.time()),detail=True)
        except (ValueError,KeyError,TypeError,OSError,sqlite3.Error,RuntimeError) as exc:
            logging.getLogger(__name__).warning('Three-league results unavailable: %s',type(exc).__name__)
            value='Üç lig arşivinden biri doğrulanamadı. Eksik veya hatalı kayıtlar sonuçlanmış sayılmadı.'
        for part in split_plain(value,limit=3200):
            await update.effective_message.reply_text(part,parse_mode=None,disable_web_page_preview=True)
        raise ApplicationHandlerStop
    async def accuracy_all_command(update,context):
        if update.effective_chat is None or update.effective_chat.id!=chat_id:
            return
        if [x.lower() for x in (context.args or [])]!=['all']:
            return  # /accuracy NBA and /accuracy EUROCUP keep their existing handlers.
        try:
            reports=await _three_league_reports()
            value=await asyncio.to_thread(render_performance,reports)
            assessments=app.bot_data.get('current_assessments')
            if assessments:value+='\n\n'+assessments.render_performance()
        except (ValueError,KeyError,TypeError,OSError,sqlite3.Error,RuntimeError) as exc:
            logging.getLogger(__name__).warning('Three-league accuracy unavailable: %s',type(exc).__name__)
            value='Üç lig için doğrulanmış performans raporu alınamadı; başarı yüzdesi uydurulmadı.'
        for part in split_plain(value,limit=3200):
            await update.effective_message.reply_text(part,parse_mode=None,disable_web_page_preview=True)
        raise ApplicationHandlerStop
    app.add_handler(CommandHandler('results',results_all_command),group=-50)
    app.add_handler(CommandHandler('accuracy',accuracy_all_command),group=-50)
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
        if section in ('market','roster') and page==0 and entry.get('europe_context'):
            await query.answer('Güncel Avrupa kaynakları kontrol ediliyor…')
            answered=True
            try:
                reviewer=app.bot_data['europe_data_review']
                # First market review may retrieve two bounded official club
                # catalog receipts before the provider's 12s admission window.
                review=await asyncio.wait_for(asyncio.to_thread(reviewer.review,entry['europe_context'],section),
                                            timeout=45 if section=='market' else 20)
                if review['original_forecast_sha256']!=entry['europe_forecast_sha256'] or review['section']!=section:
                    raise ValueError('EUROPE_SOURCE_REVIEW_BINDING')
                from hybrid_engine.elite_render import split_blocks
                from hybrid_engine.telegram_premium_ui import cache_report
                entry=dict(entry,sections=dict(entry['sections']),section_pages=dict(entry['section_pages']))
                original=entry.get('europe_original_sections',{}).get(section,'')
                entry['sections'][section]=review['html']+'\n\n<b>İLK TAHMİN / ARŞİV KANITI</b>\n'+original
                entry['section_pages'][section]=split_blocks(entry['sections'][section].splitlines(),limit=3200)
                if section=='market':
                    entry['quote_valid_until_utc']=review['valid_until_utc']
                    if review.get('details',{}).get('admitted_observations'):
                        entry['summary']=entry['summary'].replace('Güncel doğrulanmış barem yok; piyasa ayrıntıları butonda.',
                            'Güncel piyasa kaynak gözlemleri Piyasa düğmesinde; kapsam ve kalibrasyon durumuna bakın.')
                if section=='roster':
                    entry['roster_review_at_utc']=review['observed_at_utc']
                    entry['roster_valid_until_utc']=review['valid_until_utc']
                cache_report(cache,token,entry)
            except Exception as exc:
                logging.getLogger(__name__).warning('European source review unavailable: %s',type(exc).__name__)
                await query.edit_message_text('Avrupa veri kaynağı denetlenemedi veya süre aşıldı. '
                    'Veri yokluğu tam kadro/NO EDGE anlamına gelmez. İlk tahmin korunuyor. Kod: EUROPE_SOURCE_REVIEW_UNAVAILABLE',
                    reply_markup=keyboard(token))
                return
        if section=='roster' and page==0 and entry.get('roster_auto_ready') and (
                int(time.time())<entry.get('roster_valid_until_utc',0)):
            # Already collected in the same /analyze request: no duplicate
            # fetch, no new Telegram message, one in-place paginated card.
            pass
        elif section=='roster' and page==0 and entry.get('roster_context'):
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
    from hybrid_engine.isolated_execution import IsolatedExecutor,background_task
    async def ready(app):
        me=await app.bot.get_me()
        if me.id!=config['bot_id'] or me.username!=config['username']:raise ValueError('TEST_BOT_SERVER_IDENTITY_MISMATCH')
        hook=await app.bot.get_webhook_info()
        if hook.url:raise ValueError('TEST_BOT_HAS_WEBHOOK_POLLING_NOT_STARTED')
        scheduler=app.bot_data.get('europe_prematch_scheduler')
        if scheduler and not args.replay_only:tasks.append(background_task(scheduler.run(app)))
        overnight=app.bot_data.get('nba_overnight_scheduler')
        if overnight and not args.replay_only:tasks.append(background_task(overnight.run(app)))
        adaptive=app.bot_data.get('adaptive_v2_worker')
        if adaptive and not args.replay_only:
            cycle=app.bot_data.get('research_cycle')
            if cycle:tasks.append(background_task(cycle.run(app)))
            else:tasks.append(background_task(adaptive.run(app)))
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
        if not args.replay_only:tasks.append(background_task(collect()))
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
    loop=asyncio.new_event_loop();asyncio.set_event_loop(loop)
    loop.set_default_executor(IsolatedExecutor())
    app.run_polling(bootstrap_retries=0,drop_pending_updates=False)


if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps(failure_report(exc)))
        raise SystemExit(2)

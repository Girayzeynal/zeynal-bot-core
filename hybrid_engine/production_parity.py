"""Read-only production Telegram parity with the isolated bot's archive commands.

Never reads test credentials, executes research fits, mutates archives, or turns
82 candidate URLs into player injury claims. All views use the production
application's own verified ledger, if that ledger has the required schema.
"""
import asyncio
import json
import logging
import os
import sqlite3
import time

from telegram.ext import CommandHandler

from hybrid_engine.predictions_command import render_predictions, split_plain
from hybrid_engine.unified_results_view import LEAGUES, render_all, render_performance

LOG = logging.getLogger(__name__)
SUPPORTED = frozenset(LEAGUES)
READ_SECONDS = 12


async def _send(update, value):
    message = update.effective_message
    if message is None:
        return
    for part in split_plain(str(value), limit=3200):
        await message.reply_text(part, parse_mode=None, disable_web_page_preview=True)


def _reader(context):
    reader = context.application.bot_data.get("ledger_reports")
    if reader is None:
        raise ValueError("PRODUCTION_LEDGER_NOT_CONFIGURED")
    return reader


async def _read(context, league, fixture=None):
    reader = _reader(context)
    result = await asyncio.wait_for(
        asyncio.to_thread(reader.read, league, fixture), timeout=READ_SECONDS)
    while isinstance(result, dict) and isinstance(result.get("report"), dict):
        result = result["report"]
    if not isinstance(result, dict) or result.get("status") != "VERIFIED_LIVE_REPORT":
        raise ValueError("PRODUCTION_VERIFIED_LIVE_REPORT_UNAVAILABLE")
    return result


async def _all(context):
    result = {}
    for league in LEAGUES:
        result[league] = await _read(context, league)
    return result


async def features_command(update, context):
    state = context.application.bot_data
    from hybrid_engine.runtime_identity import describe
    info = describe(state)
    from hybrid_engine.official_all_82_club_batch import load_all_82
    candidates = len(load_all_82())
    value = ("ZEYNAL | ÜRETİM İŞLEVLERİ\n"
             "Analiz: " + ("YÜKLÜ" if state.get("verified_analysis_service") else "YAPILANDIRILMADI") +
             "\nArşiv okuma: " + ("YÜKLÜ; içerik henüz doğrulanmadı" if state.get("ledger_reports") else "YAPILANDIRILMADI") +
             "\nKomutlar: /nba /analyze /predictions /models /results all /accuracy all /compare /sources /sourceplayers /test runtime" +
             "\nResmî kulüp kaynak ADAYLARI: " + str(candidates) +
             "\nOyuncu kimliği / sakatlık / dakika / model etkisi: ayrı maç-öncesi doğrulama gerekli." +
             "\nKaynak adayları ve SHADOW rotasyon modeli canlı skorun girdisi değildir." +
             "\nYayın SHA: " + str(info.get("reported_release_sha") or "BİLİNMİYOR") +
             "\nGerçek Telegram teslimatı bu komutla kanıtlanmaz.")
    await _send(update, value)


async def sources_command(update, context):
    from hybrid_engine.official_all_82_club_batch import load_all_82
    candidates = load_all_82()
    await _send(update,
        "ZEYNAL | RESMÎ KULÜP ADRES DİZİNİ\n"
        "NBA / EuroLeague / EuroCup: " + str(len(candidates)) +
        " aday kulüp kaydı. Site/haber adresi kaydı erişim, güncel sakatlık, "
        "kesin ilk beş, oyuncu kimliği veya sayısal model etkisi kanıtı DEĞİLDİR.\n"
        "Resmî maç-öncesi kaynak doğrulanamadıysa skor değiştirilmez.")


async def models_command(update, context):
    args = context.args or []
    if len(args) != 2 or args[0].upper() not in SUPPORTED or not args[1] or any(c.isspace() for c in args[1]):
        await _send(update, "Kullanım: /models NBA|EUROLEAGUE|EUROCUP MAÇ_KİMLİĞİ")
        return
    try:
        from hybrid_engine.integrated_features import models
        value = await asyncio.wait_for(
            asyncio.to_thread(models, context.application.bot_data, args[0].upper(), args[1]),
            timeout=READ_SECONDS)
    except (ValueError, TypeError, KeyError, OSError, sqlite3.Error, asyncio.TimeoutError, RuntimeError):
        value = "Kayıtlı, doğrulanmış ayrı model çıktısı okunamadı. Yeni tahmin üretilmedi."
    await _send(update, value)


async def predictions_command(update, context):
    args = context.args or []
    if len(args) > 2 or (args and args[0].upper() not in SUPPORTED):
        await _send(update, "Kullanım: /predictions NBA|EUROLEAGUE|EUROCUP [sayfa]")
        return
    league = args[0].upper() if args else "NBA"
    if len(args) == 2 and (not args[1].isascii() or not args[1].isdigit() or len(args[1]) > 4 or not 1 <= int(args[1]) <= 1000):
        await _send(update, "Sayfa geçersiz. Kullanım: /predictions LİG [sayfa]")
        return
    page = int(args[1]) if len(args) == 2 else 1
    try:
        report = await _read(context, league)
        parts = await asyncio.to_thread(render_predictions, report, page, league)
        value = "\n".join(parts)
    except (ValueError, TypeError, KeyError, OSError, sqlite3.Error, asyncio.TimeoutError, RuntimeError):
        value = "Doğrulanmış üretim tahmin arşivi okunamadı. Kayıt uydurulmadı veya değiştirilmedi."
    await _send(update, value)


async def results_command(update, context):
    if [v.lower() for v in (context.args or [])] != ["all"]:
        await _send(update, "Kullanım: /results all")
        return
    try:
        reports = await _all(context)
        value = await asyncio.to_thread(render_all, reports, now=int(time.time()), detail=True, source_label="Doğrulanmış üretim arşivi")
    except (ValueError, TypeError, KeyError, OSError, sqlite3.Error, asyncio.TimeoutError, RuntimeError):
        value = "Üç ligde doğrulanmış üretim FINAL arşivi tam okunamadı; sonuç veya performans uydurulmadı."
    await _send(update, value)


async def accuracy_command(update, context):
    """Route /accuracy all; preserve existing /accuracy <league> handler."""
    if [v.lower() for v in (context.args or [])] != ["all"]:
        from ledger_reports import accuracy_command as legacy_accuracy
        await legacy_accuracy(update, context)
        return
    try:
        reports = await _all(context)
        value = await asyncio.to_thread(render_performance, reports)
    except (ValueError, TypeError, KeyError, OSError, sqlite3.Error, asyncio.TimeoutError, RuntimeError):
        value = "Üç ligde doğrulanmış üretim performans arşivi okunamadı; güven veya başarı yüzdesi uydurulmadı."
    await _send(update, value)



async def injurynews_command(update, context):
    """On-demand exact-team news receipt; no fixture or player admission."""
    args=context.args or []
    if (len(args)<5 or len(args)>18 or args[0].upper() not in
            ("EUROLEAGUE","EUROCUP") or
        sum(x.lower()=="vs" for x in args)!=1):
        await _send(update,"Kullanım: /injurynews EUROLEAGUE|EUROCUP Ev Sahibi vs Deplasman")
        return
    boundary=next(i for i,v in enumerate(args) if v.lower()=="vs")
    home=" ".join(args[1:boundary])
    away=" ".join(args[boundary+1:])
    if not (2<=len(home)<=100 and 2<=len(away)<=100 and home!=away):
        await _send(update,"Tam ve birbirinden farklı takım adları gereklidir.")
        return
    from hybrid_engine.europe_injury_public_sources import (
        review_current_team_news,render)
    state=context.application.bot_data
    now=int(time.time())
    key=(args[0].upper(),home,away)
    cache=state.setdefault("_injurynews_cache",{})
    previous=cache.get(key)
    if previous and now<previous["valid_until_utc"]:
        report=previous["report"]
    else:
        try:
            report=await asyncio.wait_for(asyncio.to_thread(
                review_current_team_news,args[0].upper(),home,away),
                timeout=16)
        except (ValueError,KeyError,TypeError,OSError,RuntimeError,asyncio.TimeoutError):
            await _send(update,"Resmî/haber kaynakları şu anda doğrulanamadı; eski kadro veya tahmin değiştirilmedi.")
            return
        if len(cache)>=16:cache.clear()
        cache[key]=dict(valid_until_utc=now+600,report=report)
    heading=("ZEYNAL | GÜNCEL KULÜP HABER KONTROLÜ\n"+
             args[0].upper()+" | "+home+" vs "+away+"\n"+
             "Kaynak kulüp eşleşmeleri: "+str(len(report.get("official_club_matches",[])))+
             " / 2\n"+
             "Bu sorgu maç fikstürü ya da resmî 12 kişilik kadro doğrulaması değildir.\n")
    await _send(update,heading+"\n"+render(report))


async def runtime_command(update, context):
    args=[v.lower() for v in (context.args or [])]
    if args not in (["runtime"],["integrations"]):
        await _send(update, "Kullanım: /test runtime veya /test integrations")
        return
    from hybrid_engine.runtime_identity import describe
    state=context.application.bot_data
    runtime=describe(state)
    if args==["runtime"]:
        await _send(update, json.dumps(runtime,ensure_ascii=False,indent=2))
        return
    # This intentionally audits ACTIVE process state separately from Git source.
    # A compiled/installed source adapter is not proof of configured runtime data,
    # a fresh pregame player status, fitted effects or a Telegram-issued pick.
    try:
        from hybrid_engine.three_league_roster_bridge import readiness
        sources=readiness()
    except (ValueError,KeyError,TypeError,OSError,ImportError) as exc:
        await _send(update,"PLAYER_PIPELINE_DIAGNOSTIC_UNAVAILABLE | "+
                    type(exc).__name__+" | canlı skor ve eski tahminler değiştirilmedi")
        return
    report=dict(
        format="THREE_LEAGUE_REAL_PROCESS_INTEGRATION_DIAGNOSTIC_V1",
        release_sha=runtime["reported_release_sha"],
        analysis_service=runtime["identity_status"],
        analysis_service_chain=runtime["service_chain"],
        last_analysis=runtime["last_analysis"],
        data_mount_present=runtime["data_mount_present"],
        original_archive_reader_configured=state.get("ledger_reports") is not None,
        last_actual_official_player_directory_query=state.get("last_sourceplayers_native_receipt"),
        league_counts=sources["membership_inventory"],
        observed_official_news_pilots=sources["observed_official_club_news_pilots"],
        unverified_official_news_sites=sources["not_connected_club_news_sites"],
        native_euro_registration_adapter_implemented=sources["native_euro_season_registration_adapter"],
        nba_player_minutes_adapter_implemented=sources["nba_existing_player_minutes_bridge_added"],
        active_current_roster_in_all_82_teams_verified=False,
        active_confirmed_transfer_news_pipeline=False,
        independently_verified_player_coach_effects_in_numeric_forecast=False,
        genuine_telegram_response_delivery_verified=False,
        production_model_changed_by_diagnostic=False,
        no_new_forecast_created=True)
    await _send(update,json.dumps(report,ensure_ascii=False,indent=2))


def install(app):
    """Attach production-safe commands only, without changing existing /analyze."""
    # The isolated UserLAnd bot imports main.build_app then installs its own
    # audited group -50 handlers. Never register duplicate production commands.
    test_token = os.getenv("ZEYNAL_TEST_BOT_TOKEN")
    if test_token and os.getenv("TELEGRAM_BOT_TOKEN") == test_token:
        return
    from hybrid_engine.europe_native_roster_source import command_handler as player_source_handler
    app.add_handler(player_source_handler())
    app.add_handler(CommandHandler("features", features_command))
    app.add_handler(CommandHandler("models", models_command))
    app.add_handler(CommandHandler("predictions", predictions_command))
    app.add_handler(CommandHandler("results", results_command))
    app.add_handler(CommandHandler("sources", sources_command))
    app.add_handler(CommandHandler("injurynews", injurynews_command))
    app.add_handler(CommandHandler("test", runtime_command))

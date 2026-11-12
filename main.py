from __future__ import annotations

import os
import html
import logging
import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Tuple

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from baseline.team_baseline_store import TeamBaselineStore, TeamBaselineBootstrapper
from providers.espn_adapter import ESPNAdapter
from nba_command import nba_command
from core.league_identity import resolve_league
from universal_analysis import UniversalAnalyzeService,render_preflight
from verified_analysis import production_service
from ledger_reports import accuracy_command, compare_command, production_reports

from faz13_engine import Faz13Engine, PrematchRequest
from faz22_engine import Faz22Engine
from faz23_engine import Faz23Engine

from aiohttp import web
from faz17_engine import Faz17Engine

# ============================
# LOGGING
# ============================
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("zeynal-core")

# HTTPX logs can contain the Telegram bot token in request URLs.
# Disable third-party request logging before the first Telegram request.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# ============================
# ENV
# ============================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_SPORTS_KEY = os.getenv("API_SPORTS_KEY")
API_SPORTS_BASE = os.getenv("API_SPORTS_BASE", "https://v1.basketball.api-sports.io")

PORT = int(os.getenv("PORT", "8080"))

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN missing")

# ============================
# HELPERS
# ============================
def parse_analyze(text: str) -> Tuple[str, str, str, str]:
    """
    /analyze NBA 2026-01-19 Atlanta Hawks vs Milwaukee Bucks
    """
    parts = text.split()
    if len(parts) < 6:
        raise ValueError("Eksik parametre")

    league = parts[1]
    date_str = parts[2]
    rest = parts[3:]

    lower = [p.lower() for p in rest]
    if "vs" not in lower:
        raise ValueError("'vs' bulunamadi")

    i = lower.index("vs")
    # Strip accidental wrapping/pasted quotes, not punctuation inside team names.
    home = " ".join(rest[:i]).strip().strip().strip(chr(34) + chr(39) + "“”‘’").strip()
    away = " ".join(rest[i + 1 :]).strip().strip().strip(chr(34) + chr(39) + "“”‘’").strip()
    if not home or not away:
        raise ValueError("Ev sahibi ve deplasman takımı zorunludur")
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("Tarih YYYY-MM-DD biçiminde ve geçerli olmalıdır") from exc
    if home.casefold() == away.casefold():
        raise ValueError("Ev sahibi ve deplasman takımları farklı olmalıdır")
    return league, date_str, home, away

# ============================
# TELEGRAM COMMANDS
# ============================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_message:
        await update.effective_message.reply_text(
            "Zeynal Bot Core aktif. NBA fikstürü: /nba veya /nba YYYY-MM-DD\nAnaliz biçimi:\n"
            "/analyze NBA YYYY-MM-DD Ev Sahibi vs Deplasman\n\n"
            "Yeterli doğrulanabilir takım verisi yoksa tahmin üretilmez."
        )

# ============================
# ANALYZE COMMAND
# ============================
async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""

    try:
        league, date_str, home, away = parse_analyze(text)
    except Exception as e:
        await update.message.reply_text(
            f"Parametre hatasi: {html.escape(str(e))}",
            disable_web_page_preview=True,
        )
        return

    # Historical requests require point-in-time snapshots. Current baselines
    # would leak post-game information into a retrospective prediction.
    release_service=context.application.bot_data.get('verified_analysis_service')
    if release_service is not None:
        report=await release_service.analyze(league,date_str,home,away)
        await update.message.reply_text(report['html'],parse_mode='HTML',disable_web_page_preview=True)
        return
    try:
        league=resolve_league(league).code
    except ValueError:
        await update.message.reply_text('Lig doğrulanamadı: UNKNOWN_OR_AMBIGUOUS_LEAGUE. Tahmin üretilmedi.')
        return
    identity_report=None
    identity_service=context.application.bot_data.get('team_identity_service')
    if identity_service is not None:
        identity_report=await identity_service.preflight(league,date_str,home,away)
        if league!='NBA' or identity_report['status']!='VERIFIED_NBA_FIXTURE':
            await update.message.reply_text(render_preflight(identity_report))
            return
        home=identity_report['home']['official_name'];away=identity_report['away']['official_name']
    elif league!='NBA':
        await update.message.reply_text('Aşama: PROVIDER. Lig için sezon kimlik/veri adaptörü yapılandırılmamış. Tahmin üretilmedi.')
        return
    requested_day = datetime.strptime(date_str, "%Y-%m-%d").date()
    utc_today = datetime.now(timezone.utc).date()
    if requested_day < utc_today:
        await update.message.reply_text(
            "Geçmiş maç için güncel takım verisi kullanılamaz. "
            "Tarihsel veri kesiti doğrulanmadan backtest tahmini üretilmedi."
        )
        return

    # Resolve fixture identity before expensive baseline calls. All /nba dates
    # are Europe/Istanbul dates; reject started games even on the same day.
    fixture_start_utc = None
    fixture_provider = None
    fixture_provider_id = None
    if identity_report is not None:
        fixture_start_utc=identity_report['fixture']['start_ts_utc']
        fixture_provider=identity_report['provider']
        aliases=identity_report['fixture']['provider_fixture_ids']
        if len(aliases)!=1:
            await update.message.reply_text('Fikstür sağlayıcı kimliği belirsiz. Tahmin üretilmedi.')
            return
        fixture_provider_id=aliases[0]
    if league.upper() == "NBA" and identity_report is None:
        from nba_command import load_espn_nba_games, load_nba_games
        from zoneinfo import ZoneInfo
        local_today = datetime.now(ZoneInfo("Europe/Istanbul")).date()
        if requested_day < local_today:
            await update.message.reply_text(
                "Maç tarihi Türkiye saatine göre geçmişte. Maç öncesi tahmin üretilmedi."
            )
            return

        def match_key(value):
            return "".join(c for c in value.casefold() if c.isalnum())

        verified = []
        provider_success = False
        available = []
        for loader in (load_espn_nba_games, load_nba_games):
            try:
                fixtures = await loader(date_str)
                provider_success = True
                available = fixtures
                matches = [
                    g for g in fixtures
                    if match_key(g["home"]) == match_key(home)
                    and match_key(g["away"]) == match_key(away)
                ]
                if len(matches) == 1:
                    verified = matches
                    fixture_provider = "ESPN" if loader is load_espn_nba_games else "API-Sports"
                    fixture_provider_id = str(matches[0].get("id") or "").strip()
                    break
            except Exception as exc:
                logger.warning("NBA fixture lookup failed: provider=%s error=%s",
                               loader.__name__, type(exc).__name__)
        if len(verified) != 1:
            if provider_success:
                await update.message.reply_text(
                    "Bu tarih için belirtilen ev sahibi/deplasman eşleşmesi doğrulanamadı. "
                    "Takım adlarını ve ev sahibi sırasını /nba YYYY-MM-DD fikstüründen kontrol et. "
                    "Tahmin üretilmedi."
                )
            else:
                await update.message.reply_text(
                    "NBA fikstür sağlayıcılarına erişilemedi. Başlangıç saati doğrulanamadı; "
                    "tahmin üretilmedi."
                )
            return
        fixture_start_utc = int(verified[0]["start"].timestamp())
        if fixture_start_utc <= int(datetime.now(timezone.utc).timestamp()):
            await update.message.reply_text(
                "Bu maç başlamış veya tamamlanmış. Maç öncesi tahmin üretilmedi."
            )
            return

    faz13: Faz13Engine = context.application.bot_data["faz13"]
    bootstrapper: TeamBaselineBootstrapper = context.application.bot_data["baseline_bootstrapper"]

    # Fail closed: never turn a missing team baseline into a league-average prediction.
    try:
        home_baseline = await bootstrapper.ensure_async(league=league, team_input=home, min_games=6)
        away_baseline = await bootstrapper.ensure_async(league=league, team_input=away, min_games=6)
    except Exception:
        logger.exception("Baseline bootstrap error")
        await update.message.reply_text("Veri sağlayıcısı hatası: analiz oluşturulmadı.")
        return

    now_ts = datetime.now(timezone.utc).timestamp()
    def usable(baseline):
        if baseline is None:
            return False
        try:
            return (int(baseline.n_games) >= 6
                    and 0 <= now_ts - float(baseline.updated_ts) <= 7 * 86400
                    and float(baseline.pts_for) > 0
                    and float(baseline.pts_against) > 0)
        except (ValueError, TypeError, AttributeError):
            return False

    if not (usable(home_baseline) and usable(away_baseline)):
        def baseline_reason(baseline):
            if baseline is None:
                return "missing"
            try:
                age = now_ts - float(baseline.updated_ts)
                if int(baseline.n_games) < 6:
                    return "insufficient_games"
                if age < 0 or age > 7 * 86400:
                    return "stale"
                if float(baseline.pts_for) <= 0 or float(baseline.pts_against) <= 0:
                    return "invalid_scores"
                return "usable"
            except (ValueError, TypeError, AttributeError):
                return "malformed"
        logger.warning(
            "Insufficient verified baselines: league=%s home_reason=%s away_reason=%s",
            league, baseline_reason(home_baseline), baseline_reason(away_baseline),
        )
        home_reason = baseline_reason(home_baseline)
        away_reason = baseline_reason(away_baseline)
        await update.message.reply_text(
            "Analiz durduruldu: doğrulanmış takım verisi yetersiz.\n"
            f"Ev sahibi veri durumu: {home_reason}\n"
            f"Deplasman veri durumu: {away_reason}\n"
            "Kaynak: ESPN takım geçmişi. Lig ortalamasından tahmin üretilmedi."
        )
        return


    try:
        req = PrematchRequest(
            fixture_id=0,
            league=league,
            date_str=date_str,
            home=home,
            away=away,
            strict_point_in_time=(league.upper() == "NBA"),
            fixture_start_utc=fixture_start_utc,
        )

        # 🔥 DOĞRU ÇAĞRI
        result = await faz13.run_prematch(req)
        if fixture_start_utc is not None and int(datetime.now(timezone.utc).timestamp())>=fixture_start_utc:
            await update.message.reply_text('Analiz sırasında maç başlangıcına ulaşıldı. Tahmin arşivlenmedi veya gönderilmedi.')
            return
        if identity_report is not None:
            result.meta['team_identity']={k:identity_report[k] for k in ('home','away','participant_snapshot_sha256','source_catalog_sha256')}

        # Market is optional. A verified current line is NOT an opening price or sharp signal.
        if league.upper() == "NBA":
            try:
                from faz17_engine.faz17_engine import MarketRequest
                market_engine = context.application.bot_data.get("faz17")
                if market_engine is not None:
                    market = await market_engine.fetch_market(
                        MarketRequest(league="NBA", home=home, away=away, date_str=date_str, fixture_start_utc=fixture_start_utc)
                    )
                    if market.get("status") in ("MARKET_OK", "MARKET_OK_DATE_SHIFT") and market.get("total") is not None:
                        result.market = market
                        # Persist only bookmaker-attributed, timestamped quotes on the Fly volume.
                        try:
                            from market_snapshot_store import MarketSnapshotStore
                            from sharp_guard import MarketSnapshot
                            import time
                            market_path = os.getenv("MARKET_SNAPSHOT_DB", "/data/market_snapshots.sqlite").strip()
                            safe_path = os.path.realpath(market_path) if market_path else ""
                            safe_storage = (
                                bool(safe_path) and os.path.ismount("/data")
                                and os.path.commonpath(("/data", safe_path)) == "/data"
                                and os.path.isdir(os.path.dirname(safe_path))
                            )
                            if safe_storage:
                                store = MarketSnapshotStore(safe_path)
                                market_key = f"{fixture_start_utc}:{home.casefold().strip()}:{away.casefold().strip()}"
                                for quote in market.get("quotes") or []:
                                    quote_ts = quote.get("observed_utc", 0)
                                    now_ts = int(time.time())
                                    if (fixture_start_utc is None or quote_ts >= fixture_start_utc
                                            or quote_ts > now_ts or now_ts - quote_ts > 900):
                                        logger.warning("Market quote rejected: post-tipoff, future or stale")
                                        continue
                                    store.append(market_key, MarketSnapshot(**quote))
                            else:
                                logger.warning("Market snapshots not persisted: /data volume unavailable")
                        except Exception:
                            logger.exception("Market snapshot persistence failed; no archive claimed")
                    else:
                        result.market = {"status": "MARKET_UNAVAILABLE", "total": None}
            except Exception:
                logger.exception("NBA market fetch failed; no market edge claimed")
                result.market = {"status": "MARKET_UNAVAILABLE", "total": None}

        # Optional persistent, insert-only ledger. Never claim archived when
        # the storage volume is not configured or the write fails.
        if league.upper() == "NBA":
            ledger_path = os.getenv("PREDICTION_LEDGER_DB", "/data/prediction_ledger.sqlite").strip()
            # Never create a prediction archive in ephemeral container storage.
            # The production Fly volume must be mounted at /data on this machine.
            persistent_root = "/data"
            persistent_path = os.path.realpath(ledger_path) if ledger_path else ""
            ledger_ready = (
                bool(persistent_path)
                and os.path.ismount(persistent_root)
                and os.path.commonpath((persistent_root, persistent_path)) == persistent_root
                and os.path.isdir(os.path.dirname(persistent_path))
            )
            if not ledger_ready:
                logger.error(
                    "Prediction ledger disabled: /data volume missing or ledger path unsafe; path=%s",
                    ledger_path,
                )
            if ledger_ready:
                try:
                    from prediction_ledger import PredictionLedger, PredictionRecord
                    import time
                    prediction_ts = int(time.time())
                    if fixture_start_utc is None or prediction_ts >= fixture_start_utc:
                        logger.warning("Prediction ledger skipped: fixture already started")
                    else:
                        fixture_key = (
                            f"{fixture_start_utc}:{home.casefold().strip()}:"
                            f"{away.casefold().strip()}"
                        )
                        sim = result.meta.get("simulation") or {}
                        home_prob = sim.get("home_win_pct")
                        ledger = PredictionLedger(ledger_path)
                        prediction_record = PredictionRecord(
                            fixture_id=fixture_key,
                            league="NBA",
                            prediction_ts_utc=prediction_ts,
                            expected_home=(result.home_avg.points_for + result.away_avg.points_against) / 2,
                            expected_away=(result.away_avg.points_for + result.home_avg.points_against) / 2,
                            home_win_probability=(home_prob / 100 if home_prob is not None else None),
                            scope="REGULATION_ONLY",
                        )
                        version_id = ledger.record_prediction_version(prediction_record)
                        inserted = ledger.record_prediction(prediction_record)
                        ledger.record_fixture_start("NBA", fixture_key, fixture_start_utc)
                        if fixture_provider and fixture_provider_id:
                            ledger.record_fixture_provenance(
                                "NBA", fixture_key, fixture_provider,
                                fixture_provider_id, fixture_start_utc,
                            )
                        else:
                            logger.warning("Fixture provenance missing; calibration not eligible")
                        logger.info("Prediction ledger: fixture=%s version_id=%s first_record_inserted=%s", fixture_key, version_id, inserted)
                except Exception:
                    logger.exception("Prediction ledger persistence failed; prediction not marked archived")

        # Sharp Guard reports only observed same-bookmaker moves; never promises an edge.
        sharp_report = ""
        if league.upper() == "NBA":
            try:
                from market_snapshot_store import MarketSnapshotStore
                from sharp_guard import audit_market
                import time
                import html
                market_path = os.getenv("MARKET_SNAPSHOT_DB", "/data/market_snapshots.sqlite").strip()
                safe_path = os.path.realpath(market_path) if market_path else ""
                if (safe_path and os.path.ismount("/data")
                        and os.path.commonpath(("/data", safe_path)) == "/data"
                        and os.path.isfile(safe_path)):
                    market_key = f"{fixture_start_utc}:{home.casefold().strip()}:{away.casefold().strip()}"
                    store = MarketSnapshotStore(safe_path)
                    quotes = result.market.get("quotes") or []
                    seen = set()
                    reports = []
                    for quote in quotes:
                        identity = (quote["bookmaker"], quote["market"], quote["source"])
                        if identity in seen:
                            continue
                        seen.add(identity)
                        history = store.history(market_key, *identity)
                        audit = audit_market(history, now_utc=int(time.time()))
                        if audit.status == "OBSERVED_ONLY":
                            reports.append(
                                f"• {html.escape(identity[0])}: {audit.opening_line:.1f} → "
                                f"{audit.current_line:.1f} ({audit.movement:+.1f}); "
                                "ilk gözlem açılış garantisi değil"
                            )
                    if reports:
                        sharp_report = ("\n\n<b>🛡 SHARP GUARD | GÖZLENEN HAREKET</b>\n"
                                        + "\n".join(reports[:5])
                                        + "\n• Sharp para akışı: doğrulanmadı | NO EDGE")
            except Exception:
                logger.exception("Sharp Guard reporting failed; no movement asserted")

        await update.message.reply_text(
            (result.render_telegram_html() + sharp_report) if league.upper() == "NBA" else result.render_html(),
            parse_mode="HTML" if league.upper() == "NBA" else None,
            disable_web_page_preview=True,
        )

    except Exception as e:
        logger.error("ANALYZE ERROR", exc_info=True)
        await update.message.reply_text(
            "Analiz sırasında dahili bir hata oluştu. İşlem tamamlanamadı.",
            disable_web_page_preview=True,
        )

# ============================
# HEALTH SERVER
# ============================
async def start_health(app: Application):
    web_app = web.Application()

    async def ready(_: web.Request):
        updater = app.updater
        running = bool(app.running and updater is not None and updater.running)
        return web.json_response({"ready": running,"release_sha":os.getenv('ZEYNAL_RELEASE_SHA','UNKNOWN')}, status=200 if running else 503)

    async def health(_: web.Request):
        return web.json_response({"ok": True})

    web_app.router.add_get("/health", health)
    web_app.router.add_get("/ready", ready)

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    return runner

# ============================
# BOOT
# ============================
def build_app() -> Application:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    baseline_store = TeamBaselineStore()
    bootstrapper = TeamBaselineBootstrapper(
        store=baseline_store,
        adapters=[ESPNAdapter()],
    )

    faz13 = Faz13Engine(
        api_sports_key=API_SPORTS_KEY,
        api_sports_base=API_SPORTS_BASE,
        baseline_store=baseline_store,
    )

    app.bot_data["baseline_store"] = baseline_store
    app.bot_data['team_identity_service']=UniversalAnalyzeService()
    app.bot_data['verified_analysis_service']=production_service()
    app.bot_data['nba_fixture_loader']=app.bot_data['verified_analysis_service'].list_nba_games
    app.bot_data["baseline_bootstrapper"] = bootstrapper
    app.bot_data["faz13"] = faz13
    app.bot_data["faz17"] = Faz17Engine(os.getenv("ODDS_API_KEY"), os.getenv("ODDS_BASE"))
    app.bot_data["faz22"] = Faz22Engine()
    app.bot_data["faz23"] = Faz23Engine()
    app.bot_data['ledger_reports'] = production_reports()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("analyze", analyze_command))
    app.add_handler(CommandHandler("nba", nba_command))
    app.add_handler(CommandHandler("accuracy", accuracy_command))
    app.add_handler(CommandHandler("compare", compare_command))
    return app

async def scheduler_loop(engines):
    # Manual verified commands do not depend on the legacy API-Sports scheduler.
    # No scheduler is enabled by deploying this release candidate.
    if os.getenv('ENABLE_LEGACY_SCHEDULER','0')=='1':
        from dynamic_scheduler import scheduler_loop as legacy_loop
        await legacy_loop(engines)
    else:
        await asyncio.Event().wait()


async def main_async():
    app = build_app()
    runner = None
    initialized = False
    started = False
    polling = False
    scheduler_task = None
    try:
        runner = await start_health(app)
        await app.initialize()
        initialized = True
        await app.bot.delete_webhook(drop_pending_updates=True)
        await app.start()
        started = True
        if app.updater is None:
            raise RuntimeError("Telegram polling updater unavailable")
        await app.updater.start_polling()
        polling = True
        logger.info("Bot polling started")
        engines = {
            "faz13": app.bot_data["faz13"],
            "faz17": app.bot_data["faz17"],
            "faz22": app.bot_data["faz22"],
            "faz23": app.bot_data["faz23"],
        }
        scheduler_task = asyncio.create_task(scheduler_loop(engines), name="scheduler-loop")
        await scheduler_task
    finally:
        if scheduler_task is not None:
            scheduler_task.cancel()
            await asyncio.gather(scheduler_task, return_exceptions=True)
        try:
            try:
                if polling and app.updater is not None:
                    await app.updater.stop()
            finally:
                try:
                    if started:
                        await app.stop()
                finally:
                    if initialized:
                        await app.shutdown()
        finally:
            if runner is not None:
                await runner.cleanup()

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()

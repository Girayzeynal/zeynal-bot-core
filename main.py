from __future__ import annotations

import os
import html
import logging
import math
import asyncio
import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any, Dict, Tuple

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from baseline.team_baseline_store import TeamBaselineStore, TeamBaselineBootstrapper
from providers.espn_adapter import ESPNAdapter
from nba_fixture_binding import resolve_nba_fixture
from prediction_ledger import PredictionLedger
from ledger_storage_config import resolve_prediction_ledger_path

from faz13_engine import Faz13Engine, PrematchRequest, Faz13CoreOutput
from faz22_engine import Faz22Engine
from faz23_engine import Faz23Engine

from aiohttp import web
from dynamic_scheduler import scheduler_loop
from nba_command import nba_command
from telegram_newscheck import newscheck_command
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
if not API_SPORTS_KEY:
    raise RuntimeError("API_SPORTS_KEY missing")

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
    home = " ".join(rest[:i]).strip()
    away = " ".join(rest[i + 1 :]).strip()
    if not home or not away:
        raise ValueError("Ev sahibi ve deplasman takımı zorunludur")
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("Tarih YYYY-MM-DD biçiminde ve geçerli olmalıdır") from exc
    if home.casefold() == away.casefold():
        raise ValueError("Ev sahibi ve deplasman takımları farklı olmalıdır")
    return league, date_str, home, away

def baseline_quality_reason(baseline: Any, now_ts: float) -> str:
    """Single source of truth for prematch baseline acceptance and diagnostics."""
    if baseline is None:
        return "missing"
    try:
        if type(baseline.n_games) is not int:
            return "malformed"
        if baseline.n_games < 6:
            return "insufficient_games"
        age = now_ts - float(baseline.updated_ts)
        if not math.isfinite(age):
            return "malformed"
        if age < 0 or age > 7 * 86400:
            return "stale"
        stats = (float(baseline.pts_for), float(baseline.pts_against),
                 float(baseline.pace), float(baseline.stdev_total))
        if not all(math.isfinite(value) for value in stats):
            return "malformed"
        if stats[0] <= 0 or stats[1] <= 0:
            return "invalid_scores"
        if stats[2] <= 0 or stats[3] < 0:
            return "invalid_stats"
        return "usable"
    except (ValueError, TypeError, AttributeError, OverflowError):
        return "malformed"


def baseline_is_usable(baseline: Any, now_ts: float) -> bool:
    return baseline_quality_reason(baseline, now_ts) == "usable"

BASELINE_REASON_TR = {
    "missing": "doğrulanmış takım geçmişi bulunamadı",
    "insufficient_games": "en az 6 uygun maç kaydı gerekiyor",
    "stale": "takım verisi güncel değil",
    "invalid_scores": "skor ortalamaları geçersiz",
    "invalid_stats": "tempo veya dağılım istatistikleri geçersiz",
    "malformed": "takım veri yapısı veya sayısal değerler geçersiz",
}


def baseline_failure_message(home_reason: str, away_reason: str) -> str:
    """Explain unavailable inputs without fabricating a prediction."""
    return (
        "Analiz oluşturulmadı: doğrulanabilir takım verisi yetersiz.\n"
        f"Ev sahibi: {BASELINE_REASON_TR.get(home_reason, 'bilinmeyen veri sorunu')}\n"
        f"Deplasman: {BASELINE_REASON_TR.get(away_reason, 'bilinmeyen veri sorunu')}\n"
        "Eksik veriler doğrulanmadan tahmin üretilmez."
    )


# ============================
# TELEGRAM COMMANDS
# ============================
async def compare_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Read-only comparison; never fetch current baselines or regenerate forecasts."""
    args = context.args or []
    if len(args) != 2 or args[0].upper() != "NBA" or not args[1].isascii() or not args[1].isdigit():
        await update.effective_message.reply_text("Kullanım: /compare NBA ESPN_MAC_ID")
        return
    ledger = context.application.bot_data.get("nba_prediction_ledger")
    if ledger is None:
        await update.effective_message.reply_text(
            "Karşılaştırma kullanılamıyor: kalıcı NBA tahmin arşivi etkin değil."
        )
        return
    try:
        from telegram_result_audit import compare_fixture, format_comparison
        result = await asyncio.to_thread(compare_fixture, ledger.db_path, args[1])
        labels = {
            "NO_PREMATCH_PREDICTION": "Maç öncesi kayıtlı tahmin bulunamadı.",
            "UNVERIFIED_PROVENANCE": "Maç kimliği ve kaynak kanıtı doğrulanamadı.",
            "INVALID_PREGAME_TIME": "Tahmin maç başlamadan önce kaydedilmemiş.",
            "AWAITING_VERIFIED_FINAL": "Doğrulanmış maç sonucu henüz arşivde yok.",
            "INCOMPATIBLE_SCOPE": "Tahmin ve sonuç kapsamları uyuşmuyor.",
            "UNVERIFIED_FINAL": "Sonuç kanıtı doğrulanamadı.",
            "LEDGER_SCHEMA_INCOMPLETE": "Arşiv şeması eksik; doğrulanmış karşılaştırma yapılamıyor.",
        }
        message = (format_comparison(result) if result["status"] == "EVALUATED"
                   else f"NBA {args[1]}: {labels.get(result['status'], 'Karşılaştırma kullanılamıyor.')}")
    except (ValueError, OSError, sqlite3.Error):
        logger.exception("Read-only NBA comparison failed")
        message = "Karşılaştırma yapılamadı: arşiv bütünlüğü veya erişim hatası."
    await update.effective_message.reply_text(message)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_message:
        await update.effective_message.reply_text(
            "Zeynal Bot Core aktif. NBA fikstürü: /nba veya /nba YYYY-MM-DD\n"
            "Analiz biçimi:\n"
            "/analyze NBA YYYY-MM-DD Ev Sahibi vs Deplasman\n\n"
            "Karşılaştırma: /compare NBA ESPN_MAC_ID\n"
            "Arşiv durumu: /auditstatus | Performans: /accuracy\n"
            "Haber denetimi: /newscheck NBA ESPN_MAC_ID\n"
            "Yeterli doğrulanabilir takım verisi yoksa tahmin üretilmez."
        )

# ============================
# ANALYZE COMMAND
# ============================
async def auditstatus_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Read-only archive health; never conflate stored rows with model calibration."""
    from ledger_operational_status import ledger_operational_status

    ledger = context.application.bot_data.get("nba_prediction_ledger")
    path = ledger.db_path if ledger is not None else None
    report = await asyncio.to_thread(ledger_operational_status, path)
    if report["status"] != "READABLE":
        message = f"NBA arşiv durumu: {report['status']}\nOtomatik kalibrasyon: DOĞRULANMADI"
    else:
        message = (
            f"NBA arşiv durumu: OK\n"
            f"Tahmin kayıtları: {report['predictions']}\n"
            f"Sonuç kayıtları: {report['outcomes']}\n"
            f"Zaman/kapsam uyumlu eşleşmeler: {report['paired']}\n"
            "Not: Eşleşme sayısı doğrulanmış performans metriği değildir.\n"
            "Otomatik kalibrasyon: DOĞRULANMADI"
        )
    await update.effective_message.reply_text(message)


async def accuracy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verified historical accuracy only; no inference or calibration writes."""
    from verified_nba_accuracy import verified_nba_accuracy

    ledger = context.application.bot_data.get("nba_prediction_ledger")
    if ledger is None:
        await update.effective_message.reply_text(
            "NBA doğrulanmış performans raporu kullanılamıyor: arşiv etkin değil.")
        return
    try:
        report = await asyncio.to_thread(verified_nba_accuracy, ledger.db_path)
    except (ValueError, OSError, sqlite3.Error):
        logger.exception("Verified NBA accuracy unavailable")
        await update.effective_message.reply_text(
            "Performans raporu kullanılamıyor: arşiv bütünlüğü veya erişim hatası.")
        return
    if report["status"] == "INSUFFICIENT_VERIFIED_PAIRS":
        await update.effective_message.reply_text(
            "NBA performans raporu: doğrulanmış maç çifti bulunamadı. "
            f"Arşivdeki tahmin: {report['total_predictions']}; "
            "doğrulanmış karşılaştırma: 0. "
            "Başarı oranı hesaplanmadı.")
        return
    await update.effective_message.reply_text(
        ("NBA doğrulanmış performans (tarihsel)\n"
         if report["status"] == "EVALUATED" else
         "NBA performans: DÜŞÜK ÖRNEKLEM (n<30)\n")
        + f"Doğrulanmış maç: {report['verified']} / {report['total_predictions']}\n"
        f"Toplam skor MAE: {report['total_mae']:.2f}\n"
        f"Skor farkı MAE: {report['margin_mae']:.2f}\n"
        f"Toplam skor sapması (+ yüksek tahmin): {report['total_bias']:+.2f}\n"
        f"Skor farkı sapması (ev sahibi - deplasman): {report['margin_bias']:+.2f}\n"
        f"Toplam skor RMSE: {report['total_rmse']:.2f}\n"
        f"Skor farkı RMSE: {report['margin_rmse']:.2f}\n"
        + (f"Kazanan yönü isabeti: {report['winner_accuracy'] * 100:.1f}% "
           f"(n={report['winner_sample']})\n"
           if report["winner_accuracy"] is not None
           else "Kazanan yönü isabeti: hesaplanamadı\n")
        + f"Hariç tutulan: {sum(report['excluded'].values())}\n"
        "Otomatik kalibrasyon: DOĞRULANMADI"
    )


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
    requested_day = datetime.strptime(date_str, "%Y-%m-%d").date()
    turkey_today = datetime.now(ZoneInfo("Europe/Istanbul")).date()
    if requested_day < turkey_today:
        await update.message.reply_text(
            "Geçmiş maç için güncel takım verisi kullanılamaz. "
            "Tarihsel veri kesiti doğrulanmadan backtest tahmini üretilmedi."
        )
        return

    # Never attach an NBA projection to an invented fixture id.
    fixture_id = 0
    if league.upper() == "NBA":
        try:
            adapter = context.application.bot_data.get("nba_fixture_adapter")
            if adapter is None:
                raise ValueError("ESPN fixture adapter unavailable")
            fixture = await resolve_nba_fixture(adapter, date_str, home, away)
            fixture_id = int(fixture["provider_fixture_id"])
        except (ValueError, RuntimeError, KeyError, TypeError) as exc:
            logger.warning("NBA fixture validation failed: %s", exc)
            await update.message.reply_text(
                "NBA fikstürü doğrulanamadı: analiz oluşturulmadı."
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
    home_reason = baseline_quality_reason(home_baseline, now_ts)
    away_reason = baseline_quality_reason(away_baseline, now_ts)
    if home_reason != "usable" or away_reason != "usable":
        logger.warning(
            "Insufficient verified baselines: league=%s home_reason=%s away_reason=%s",
            league, home_reason, away_reason,
        )
        await update.message.reply_text(
            baseline_failure_message(home_reason, away_reason)
        )
        return

    try:
        req = PrematchRequest(
            fixture_id=fixture_id,
            league=league,
            date_str=date_str,
            home=home,
            away=away,
        )

        # 🔥 DOĞRU ÇAĞRI
        result = await faz13.run_prematch(req)
        if not isinstance(result, Faz13CoreOutput) or not isinstance(result.meta, dict):
            raise TypeError("FAZ13 returned an invalid analysis payload")
        if not result.meta.get("data_quality"):
            raise ValueError("FAZ13 analysis lacks data-quality provenance")

        # PRE pipeline: FAZ22 risk filter, then FAZ23 signal filter and snapshot.
        result = context.application.bot_data["faz22"].score_and_finalize(result)
        if not isinstance(result, Faz13CoreOutput) or not isinstance(result.meta, dict):
            raise TypeError("FAZ22 returned an invalid analysis payload")
        result = context.application.bot_data["faz23"].apply_decision(result)
        if not isinstance(result, Faz13CoreOutput) or not isinstance(result.meta, dict):
            raise TypeError("FAZ23 returned an invalid analysis payload")
        # With opt-in persistence, never show an unrecorded NBA prediction.
        ledger = context.application.bot_data.get("nba_prediction_ledger")
        if league.upper() == "NBA" and ledger is not None:
            from prematch_ledger_bridge import record_faz13_for_espn_fixture
            if result.meta.get("input_snapshot_status") != "CAPTURED":
                raise ValueError("NBA ledger requires original replayable inputs")
            home_ref = await adapter.resolve_team(home)
            away_ref = await adapter.resolve_team(away)
            if not home_ref or not away_ref:
                raise ValueError("NBA ledger team identities unavailable")
            inserted = record_faz13_for_espn_fixture(
                ledger, result, fixture,
                resolved_home_team_id=str(home_ref["id"]),
                resolved_away_team_id=str(away_ref["id"]),
            )
            # A duplicate means this invocation did not archive its forecast.
            # Never display a newly computed forecast as if it were persisted.
            if inserted is not True:
                raise ValueError("NBA prematch forecast was not newly archived")

        await context.application.bot_data["faz23"].record_snapshot(result)

        await update.message.reply_text(
            result.render_html(),
            parse_mode="HTML",
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
        return web.json_response({"ready": running}, status=200 if running else 503)

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

    baseline_store = TeamBaselineStore(base_dir=os.getenv("BASELINE_DIR", "data/baselines"))
    # Estimated pace is accepted only with replayable ESPN boxscore evidence.
    # Keep opt-in disabled until provider coverage and provenance are verified.
    espn_estimated_pace = os.getenv("ESPN_ESTIMATED_PACE_ENABLED", "false").strip().lower() == "true"
    bootstrapper = TeamBaselineBootstrapper(
        store=baseline_store,
        adapters=[ESPNAdapter(allow_estimated_pace=espn_estimated_pace)],
    )

    faz13 = Faz13Engine(
        api_sports_key=API_SPORTS_KEY,
        api_sports_base=API_SPORTS_BASE,
        baseline_store=baseline_store,
    )

    app.bot_data["baseline_store"] = baseline_store
    app.bot_data["baseline_bootstrapper"] = bootstrapper
    app.bot_data["nba_fixture_adapter"] = ESPNAdapter()
    app.bot_data["faz13"] = faz13
    app.bot_data["faz22"] = Faz22Engine()
    app.bot_data["faz23"] = Faz23Engine(storage_path=os.getenv("FAZ23_STORAGE", "faz23_storage.sqlite"))

    # Explicit opt-in. /analyze persists verified NBA projections when enabled.
    ledger_enabled = os.getenv("NBA_LEDGER_ENABLED", "false").strip().lower() == "true"
    ledger_path = resolve_prediction_ledger_path(
        enabled=ledger_enabled,
        configured_path=os.getenv("NBA_LEDGER_PATH"),
    )
    if ledger_path is not None:
        app.bot_data["nba_prediction_ledger"] = PredictionLedger(ledger_path)
        app.bot_data["nba_espn_adapter"] = ESPNAdapter()
        logger.info("NBA prediction ledger enabled for verified /analyze projections")


    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("analyze", analyze_command))
    app.add_handler(CommandHandler("nba", nba_command))
    app.add_handler(CommandHandler("compare", compare_command))
    app.add_handler(CommandHandler("auditstatus", auditstatus_command))
    app.add_handler(CommandHandler("accuracy", accuracy_command))
    app.add_handler(CommandHandler("newscheck", newscheck_command))
    return app

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
            "faz17": Faz17Engine(os.getenv("ODDS_API_KEY"), os.getenv("ODDS_BASE")),
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

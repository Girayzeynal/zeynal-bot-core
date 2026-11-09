"""Read-only Telegram command: /newscheck NBA ESPN_FIXTURE_ID.

Reports archived news provenance without fetching or inventing articles.
"""
import asyncio
import logging
import sqlite3

from prediction_news_audit import audit_prediction_news

log = logging.getLogger(__name__)


def format_news_audit(report):
    if report.status == "NO_NEWS_SNAPSHOT":
        return (f"NBA {report.fixture_id}: Haber kanıtı arşivlenmemiş. "
                "Bu, haber bulunmadığı anlamına gelmez.")
    warnings = {
        "NO_ELIGIBLE_PREGAME_NEWS": "Uygun maç öncesi haber kaydı yok",
        "EDITORIAL_IS_NOT_VERIFIED_FACT": "Editör yorumu doğrulanmış olgu değildir",
        "REPORTING_NOT_INDEPENDENTLY_CORROBORATED": "Muhabir haberi bağımsız doğrulanmamış",
        "NEWS_NOT_CONSUMED_BY_PREDICTION_MODEL": "Haberler tahmin hesabında kullanılmadı",
    }
    lines = [
        f"NBA {report.fixture_id} — haber kanıt denetimi",
        f"Arşivlenen: {report.total_items}",
        f"Resmi: {report.official_items} | Muhabir: {report.reporting_items} | Editör: {report.editorial_items}",
        f"Bağımsız doğrulanan iddia: {report.corroborated_claims}",
        "Model haber kullandı: HAYIR",
    ]
    lines.extend("Uyarı: " + warnings.get(code, code) for code in report.warnings)
    return "\n".join(lines)


async def newscheck_command(update, context):
    args = context.args or []
    if (len(args) != 2 or args[0].upper() != "NBA"
            or not args[1].isascii() or not args[1].isdigit()):
        await update.effective_message.reply_text("Kullanım: /newscheck NBA ESPN_MAC_ID")
        return
    ledger = context.application.bot_data.get("nba_prediction_ledger")
    if ledger is None:
        await update.effective_message.reply_text(
            "Haber denetimi kullanılamıyor: kalıcı NBA tahmin arşivi etkin değil.")
        return
    try:
        report = await asyncio.to_thread(
            audit_prediction_news, ledger, league="NBA", fixture_id=args[1])
        message = format_news_audit(report)
    except (ValueError, TypeError, KeyError, OSError, sqlite3.Error):
        log.exception("News evidence audit failed")
        message = "Haber denetimi yapılamadı: kayıt veya bütünlük hatası."
    await update.effective_message.reply_text(message)

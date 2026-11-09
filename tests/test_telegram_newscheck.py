"""Offline Telegram newscheck command tests."""
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from telegram_newscheck import newscheck_command, format_news_audit


class NewscheckTests(unittest.IsolatedAsyncioTestCase):
    def make_context(self, args, ledger=None):
        return SimpleNamespace(args=args, application=SimpleNamespace(
            bot_data={"nba_prediction_ledger": ledger} if ledger is not None else {}))

    async def test_invalid_args(self):
        update = SimpleNamespace(effective_message=SimpleNamespace(reply_text=AsyncMock()))
        await newscheck_command(update, self.make_context(["NBA", "../bad"]))
        self.assertIn("Kullanım", update.effective_message.reply_text.await_args.args[0])

    async def test_disabled_archive(self):
        update = SimpleNamespace(effective_message=SimpleNamespace(reply_text=AsyncMock()))
        await newscheck_command(update, self.make_context(["NBA", "401999001"]))
        self.assertIn("etkin değil", update.effective_message.reply_text.await_args.args[0])

    async def test_valid_read_only_audit(self):
        update = SimpleNamespace(effective_message=SimpleNamespace(reply_text=AsyncMock()))
        report = SimpleNamespace(
            status="NEWS_EVIDENCE_ARCHIVED", fixture_id="401999001",
            total_items=1, official_items=1, reporting_items=0,
            editorial_items=0, corroborated_claims=0,
            warnings=("NEWS_NOT_CONSUMED_BY_PREDICTION_MODEL",))
        with patch("telegram_newscheck.audit_prediction_news", return_value=report) as audit:
            await newscheck_command(update, self.make_context(["NBA", "401999001"], object()))
        audit.assert_called_once()
        self.assertIn("Model haber kullandı: HAYIR",
                      update.effective_message.reply_text.await_args.args[0])

    def test_missing_snapshot_is_not_reported_as_no_news(self):
        report = SimpleNamespace(status="NO_NEWS_SNAPSHOT", fixture_id="401999001")
        self.assertIn("arşivlenmemiş", format_news_audit(report))


if __name__ == "__main__":
    unittest.main()

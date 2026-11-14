"""Actual asynchronous /analyze research-routing tests with a mocked Telegram API.

No network, production database, live Telegram messages, or betting claims.
"""
import importlib
import os
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch


class HybridTelegramRuntimeTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        with patch.dict(os.environ, {'TELEGRAM_BOT_TOKEN': '123456:SYNTHETIC_ONLY'}):
            self.main = importlib.import_module('main')
        self.message = SimpleNamespace(
            text='/analyze NBA 2026-11-15 New Orleans Pelicans vs Denver Nuggets',
            reply_text=AsyncMock(),
        )
        self.update = SimpleNamespace(message=self.message)
        self.hybrid = SimpleNamespace(analyze=AsyncMock())
        self.release = SimpleNamespace(analyze=AsyncMock())
        self.context = SimpleNamespace(application=SimpleNamespace(
            bot_data={'hybrid_nba_service': self.hybrid, 'verified_analysis_service': self.release}
        ))

    async def test_research_success_sends_warning_and_never_calls_release(self):
        self.hybrid.analyze.return_value = {'html_parts': ['<b>Research</b>', '<i>Part 2</i>']}
        await self.main.analyze_command(self.update, self.context)
        self.hybrid.analyze.assert_awaited_once()
        self.release.analyze.assert_not_awaited()
        self.assertEqual(self.message.reply_text.await_count, 2)
        first = self.message.reply_text.await_args_list[0]
        self.assertIn('KALİBRE EDİLMEDİ', first.args[0])
        self.assertEqual(first.kwargs['parse_mode'], 'HTML')

    async def test_research_exception_never_falls_back(self):
        self.hybrid.analyze.side_effect = RuntimeError('synthetic failure')
        await self.main.analyze_command(self.update, self.context)
        self.release.analyze.assert_not_awaited()
        self.message.reply_text.assert_awaited_once()
        self.assertIn('FAZ13 sonucu üretilmedi', self.message.reply_text.await_args.args[0])

    async def test_late_oversized_part_causes_no_partial_delivery(self):
        self.hybrid.analyze.return_value = {'html_parts': ['short', 'x' * 4097]}
        await self.main.analyze_command(self.update, self.context)
        self.release.analyze.assert_not_awaited()
        self.message.reply_text.assert_awaited_once()
        self.assertIn('rapor gönderilmedi', self.message.reply_text.await_args.args[0])


if __name__ == '__main__':
    import unittest
    unittest.main()

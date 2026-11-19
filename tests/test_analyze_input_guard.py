"""User batch reproduction and real PTB routing with an in-memory Bot API double.

No actual Telegram delivery, source download, or forecast generation occurs.
"""
import importlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase, IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from telegram import Update
from telegram.ext import Application, CommandHandler
from telegram.request import BaseRequest

from core.league_identity import normalize_name
from hybrid_engine.analyze_input import input_error
from hybrid_engine.frozen_archive import FrozenArchive
from hybrid_engine.test_bot import install_isolated_services


PAIRS = [('Boston Celtics', 'Orlando Magic'), ('Cleveland Cavaliers', 'Chicago Bulls'),
         ('Washington Wizards', 'Memphis Grizzlies'), ('Miami Heat', 'Houston Rockets'),
         ('Brooklyn Nets', 'Philadelphia 76ers'), ('Minnesota Timberwolves', 'Portland Trail Blazers'),
         ('New Orleans Pelicans', 'Golden State Warriors'), ('Denver Nuggets', 'Phoenix Suns')]
COMMANDS = ['/analyze NBA 2026-11-16 '+h+' vs '+a for h, a in PAIRS]
ROOT = Path(__file__).resolve().parents[1]


def main_module():
    with patch.dict(os.environ, {'TELEGRAM_BOT_TOKEN': '123456:SYNTHETIC_ONLY'}):
        return importlib.import_module('main')


class AnalyzeInputTests(TestCase):
    def setUp(self):
        self.parse = main_module().parse_analyze

    def test_reported_eight_command_batch_reproduces_original_root_cause(self):
        _, _, home, away = self.parse('\n'.join(COMMANDS))
        self.assertEqual(home, 'Boston Celtics')
        self.assertIn('/analyze NBA', away)
        self.assertGreater(len(away), 300)
        with self.assertRaisesRegex(ValueError, 'NONEMPTY_BOUNDED_NAME_REQUIRED'):
            normalize_name(away)

    def test_batches_are_rejected_before_parser_even_on_one_line(self):
        for separator in ('\n', '\r\n', ' '):
            parser = AsyncMock(side_effect=AssertionError('must not parse batch'))
            text = input_error(separator.join(COMMANDS), parser)
            self.assertIn('tek mesajda', text)
            self.assertIn('topluca çalıştırılmadı', text)
            parser.assert_not_called()
            self.assertLess(len(text.encode('utf-16-le'))//2, 4096)

    def test_batch_with_bot_username_is_also_rejected(self):
        text = '\n'.join(c.replace('/analyze', '/analyze@ZeynalEliteTestBot') for c in COMMANDS)
        self.assertIn('tek mesajda', input_error(text, self.parse))

    def test_all_eight_individual_commands_keep_original_date_and_team_names(self):
        for command, pair in zip(COMMANDS, PAIRS):
            with self.subTest(command=command):
                self.assertIsNone(input_error(command, self.parse))
                self.assertEqual(self.parse(command), ('NBA', '2026-11-16', *pair))

    def test_bare_command_and_invalid_syntax_show_fixed_usage_without_echo(self):
        for text in ('/analyze', '/analyze NBA', '/analyze NBA invalid A vs B',
                     '/analyze NBA 2026-11-17 A https://secret.invalid/token B'):
            reply = input_error(text, self.parse)
            self.assertIn('Kullanım:', reply)
            self.assertIn('TSİ', reply)
            self.assertNotIn('secret.invalid', reply)
            self.assertNotIn('Parametre hatasi', reply)

    def test_overlong_or_punctuation_only_team_names_are_explained(self):
        self.assertIn('300 karakter', input_error('/analyze NBA 2026-11-17 '+('A'*301)+' vs B', self.parse))
        self.assertIn('geçerli takım', input_error('/analyze NBA 2026-11-17 --- vs B', self.parse))

    def test_wrapped_single_command_and_quoted_names_still_pass(self):
        text = '/analyze NBA 2026-11-17 “Boston\nCeltics” vs “Orlando Magic”'
        self.assertIsNone(input_error(text, self.parse))
        self.assertEqual(self.parse(text)[2:], PAIRS[0])


class BotAPIDouble(BaseRequest):
    def __init__(self):
        self.sent = []

    async def initialize(self):
        pass

    async def shutdown(self):
        pass

    async def do_request(self, url, method, request_data=None, **kwargs):
        name = url.rsplit('/', 1)[-1]
        if name == 'getMe':
            result = dict(id=123456, is_bot=True, first_name='Synthetic', username='zeynal_test_bot')
        elif name == 'sendMessage':
            text = request_data.parameters['text']
            self.sent.append(text)
            result = dict(message_id=len(self.sent), date=1794844800,
                          chat=dict(id=17, type='private'), text=text)
        else:
            raise AssertionError('Unexpected Bot API method: '+name)
        return 200, json.dumps(dict(ok=True, result=result)).encode()


class AnalyzeGuardRoutingTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.main = main_module()
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.api = BotAPIDouble()
        self.app = Application.builder().token('123456:SYNTHETIC_ONLY').request(self.api).build()
        self.app.add_handler(CommandHandler('analyze', self.main.analyze_command))
        archive = FrozenArchive(ROOT/'docs/prospective/euroleague-20261112')
        self.archive_before = {
            p: p.read_bytes() for p in (ROOT/'docs/prospective/euroleague-20261112').rglob('*') if p.is_file()}
        self.journal, _ = install_isolated_services(self.app, archive, self.tmp.name, chat_id=17)
        self.service = SimpleNamespace(analyze=AsyncMock(return_value=dict(status='ABSTAIN', html='DATE_GUARD_PRESERVED')))
        self.app.bot_data['verified_analysis_service'] = self.service
        await self.app.initialize()
        self.addAsyncCleanup(self.app.shutdown)

    async def send(self, text, chat=17, update_id=1):
        command = text.split()[0]
        update = Update.de_json(dict(update_id=update_id, message=dict(message_id=update_id,
            date=1794844800, chat=dict(id=chat, type='private'),
            **{'from': dict(id=23, is_bot=False, first_name='Synthetic')}, text=text,
            entities=[dict(type='bot_command', offset=0, length=len(command))])), self.app.bot)
        await self.app.process_update(update)

    async def test_batch_gets_one_help_reply_and_never_calls_analysis_or_changes_archive(self):
        await self.send('\n'.join(COMMANDS))
        self.assertEqual(len(self.api.sent), 1)
        self.assertIn('tek mesajda', self.api.sent[0])
        self.assertNotIn('NONEMPTY_BOUNDED_NAME_REQUIRED', self.api.sent[0])
        self.service.analyze.assert_not_awaited()
        self.assertTrue(all(p.read_bytes() == raw for p, raw in self.archive_before.items()))
        self.assertFalse([e for e in self.journal.read() if e.get('kind') == 'HANDLER_ERROR'])

    async def test_bare_command_is_stopped_before_legacy_missing_parameter_handler(self):
        await self.send('/analyze')
        self.assertEqual(len(self.api.sent), 1)
        self.assertIn('Kullanım:', self.api.sent[0])
        self.assertNotIn('Eksik parametre', self.api.sent[0])
        self.service.analyze.assert_not_awaited()

    async def test_valid_command_continues_once_without_silently_correcting_date(self):
        await self.send(COMMANDS[0])
        self.service.analyze.assert_awaited_once_with('NBA', '2026-11-16', *PAIRS[0])
        self.assertEqual(self.api.sent, ['DATE_GUARD_PRESERVED'])

    async def test_suggested_tsi_date_and_bot_username_continue_to_existing_handler(self):
        await self.send(COMMANDS[0].replace('2026-11-16', '2026-11-17').replace('/analyze', '/analyze@zeynal_test_bot'))
        self.service.analyze.assert_awaited_once_with('NBA', '2026-11-17', *PAIRS[0])

    async def test_unauthorized_chat_gets_neither_usage_nor_service_access(self):
        await self.send('\n'.join(COMMANDS), chat=99)
        self.assertEqual(self.api.sent, [])
        self.service.analyze.assert_not_awaited()

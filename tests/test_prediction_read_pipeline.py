"""Read errors must remain distinct from delivery of the error notice."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading
import time
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock,Mock

from telegram.ext import ApplicationHandlerStop
from hybrid_engine.predictions_command import PredictionsCommand


class PredictionReadPipelineTests(IsolatedAsyncioTestCase):
    def handler(self,reader,timeout):
        writer=AsyncMock(return_value=True)
        command=PredictionsCommand(reader,SimpleNamespace(append=Mock()),17,
            read_timeout=timeout,journal_writer=writer)
        reply=AsyncMock();update=SimpleNamespace(update_id=1,effective_chat=SimpleNamespace(id=17),
            effective_message=SimpleNamespace(reply_text=reply))
        return command,update,reply

    async def test_slow_but_completed_verified_read_delivers_a_list(self):
        def read(*args):
            time.sleep(.025)
            return dict(status='VERIFIED_LIVE_REPORT',forecasts=[],unique_fixtures=0,pending=0)
        command,update,reply=self.handler(SimpleNamespace(read=read),.5)
        with self.assertRaises(ApplicationHandlerStop):await command.handle(update,SimpleNamespace(args=['NBA']))
        self.assertEqual(command.last_read['status'],'VERIFIED')
        self.assertGreater(command.last_read['finished_at']-command.last_read['started_at'],.02)
        self.assertEqual(command.last_response_kind,'PREDICTION_LIST')
        self.assertEqual(command.last_send['status'],'SENT');self.assertIn('KAYITLI NBA',reply.call_args.args[0])

    async def test_read_timeout_stays_a_read_timeout_after_notice_was_sent_and_thread_finishes(self):
        def read(*args):time.sleep(.04);return {}
        command,update,reply=self.handler(SimpleNamespace(read=read),.005)
        with self.assertRaises(ApplicationHandlerStop):await command.handle(update,SimpleNamespace(args=['NBA']))
        await asyncio.sleep(.06)
        self.assertEqual(command.last_read['status'],'TIMEOUT')
        self.assertIsNotNone(command.last_read['finished_at'])
        self.assertEqual(command.last_response_kind,'ERROR_NOTICE')
        self.assertEqual(command.last_send['status'],'SENT')
        self.assertIn('PREDICTIONS_READ_TIMEOUT',reply.call_args.args[0])

    async def test_queued_timeout_is_visible_without_claiming_a_started_archive_read(self):
        asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=1))
        started=threading.Event();release=threading.Event()
        def busy():started.set();release.wait(5)
        task=asyncio.create_task(asyncio.to_thread(busy))
        reader=SimpleNamespace(read=Mock(return_value={}))
        command,update,_=self.handler(reader,.01)
        try:
            while not started.is_set():await asyncio.sleep(.001)
            with self.assertRaises(ApplicationHandlerStop):await command.handle(update,SimpleNamespace(args=['NBA']))
            self.assertIsNone(command.last_read['started_at'])
            self.assertEqual(command.last_read['status'],'TIMEOUT')
            self.assertEqual(command.last_response_kind,'ERROR_NOTICE')
        finally:release.set();await task
        reader.read.assert_not_called()

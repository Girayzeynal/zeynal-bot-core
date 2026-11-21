"""Accepted Bot API responses must not wait behind research fits. No real Telegram."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
import threading
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

from telegram.request import HTTPXRequest
from hybrid_engine.test_bot import AuditedRequest


class IsolatedDeliveryIOTests(IsolatedAsyncioTestCase):
    def payload(self):
        return 200,json.dumps(dict(ok=True,result=dict(message_id=11,date=1795080000,
            chat=dict(id=17,type='private'),text='SYNTHETIC response'))).encode()

    async def test_accepted_response_journal_does_not_queue_behind_research_executor(self):
        loop=asyncio.get_running_loop();loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
        started=threading.Event();release=threading.Event()
        def research():started.set();release.wait(5)
        busy=asyncio.create_task(asyncio.to_thread(research))
        while not started.is_set():await asyncio.sleep(.001)
        journal=SimpleNamespace(append=Mock());request=AuditedRequest(journal)
        try:
            with patch.object(HTTPXRequest,'do_request',new=AsyncMock(return_value=self.payload())):
                status,_=await asyncio.wait_for(request.do_request(
                    'http://127.0.0.1/botSYNTHETIC/sendMessage','POST',
                    request_data=SimpleNamespace(parameters={'text':'SYNTHETIC response'})),.3)
            self.assertEqual(status,200);self.assertFalse(release.is_set())
            journal.append.assert_called_once()
        finally:
            release.set();await busy;await request.shutdown()

    async def test_local_journal_failure_does_not_turn_server_acceptance_into_send_failure(self):
        journal=SimpleNamespace(append=Mock(side_effect=sqlite3.OperationalError('private-secret-path')))
        request=AuditedRequest(journal)
        try:
            with (patch.object(HTTPXRequest,'do_request',new=AsyncMock(return_value=self.payload())),
                  self.assertLogs('hybrid_engine.test_bot',level='WARNING') as logs):
                status,_=await request.do_request('http://127.0.0.1/botSYNTHETIC/sendMessage','POST')
            self.assertEqual(status,200);self.assertEqual(request.journal_status,'UNAVAILABLE')
            self.assertNotIn('private-secret-path',' '.join(logs.output))
        finally:await request.shutdown()

    async def test_real_transport_failure_remains_unconfirmed_and_is_not_hidden(self):
        from telegram.error import TimedOut
        failure=TimedOut('synthetic transport timeout')
        journal=SimpleNamespace(append=Mock());request=AuditedRequest(journal)
        try:
            with patch.object(HTTPXRequest,'do_request',new=AsyncMock(side_effect=failure)):
                with self.assertRaises(TimedOut) as raised:
                    await request.do_request('http://127.0.0.1/botSYNTHETIC/sendMessage','POST')
            self.assertIs(raised.exception,failure)
            self.assertEqual(journal.append.call_args.args[1]['kind'],'SEND_UNCONFIRMED')
        finally:await request.shutdown()

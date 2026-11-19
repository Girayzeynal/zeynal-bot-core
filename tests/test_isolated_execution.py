"""Real worker contention, bounded research concurrency, no Telegram credentials."""
import asyncio
import threading
from unittest import IsolatedAsyncioTestCase

from hybrid_engine.isolated_execution import BACKGROUND,IsolatedExecutor,background_task


class IsolatedExecutionTests(IsolatedAsyncioTestCase):
    async def test_background_fit_cannot_starve_command_archive_or_dns_work(self):
        asyncio.get_running_loop().set_default_executor(IsolatedExecutor())
        release=threading.Event();started=threading.Event()
        def fit():started.set();release.wait(5)
        busy=background_task(asyncio.to_thread(fit))
        try:
            while not started.is_set():await asyncio.sleep(.001)
            current=await asyncio.wait_for(asyncio.to_thread(lambda:('command',BACKGROUND.get())),.3)
            self.assertEqual(current,('command',False));self.assertFalse(release.is_set())
        finally:release.set();await busy

    async def test_two_background_jobs_remain_serial_and_context_is_restored(self):
        asyncio.get_running_loop().set_default_executor(IsolatedExecutor())
        release=threading.Event();started=threading.Event();second=threading.Event()
        def first():started.set();release.wait(5);return BACKGROUND.get()
        def later():second.set();return BACKGROUND.get()
        a=background_task(asyncio.to_thread(first))
        try:
            while not started.is_set():await asyncio.sleep(.001)
            b=background_task(asyncio.to_thread(later))
            # An interactive worker can finish while the second fit is queued.
            await asyncio.wait_for(asyncio.to_thread(lambda:None),.3)
            self.assertFalse(second.is_set());self.assertFalse(BACKGROUND.get())
        finally:release.set()
        self.assertEqual(await asyncio.gather(a,b),[True,True])

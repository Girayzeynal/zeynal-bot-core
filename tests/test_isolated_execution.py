"""Real worker contention, bounded research concurrency, no Telegram credentials."""
import asyncio
import threading
from unittest import IsolatedAsyncioTestCase

from hybrid_engine.isolated_execution import BACKGROUND,OPTIONAL_SOURCE,IsolatedExecutor,background_task,optional_source_thread


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

    async def test_timed_out_optional_provider_cannot_block_next_candidate_read(self):
        """Actual source thread stays blocked after wait_for cancellation."""
        asyncio.get_running_loop().set_default_executor(IsolatedExecutor())
        release=threading.Event()
        entered=[threading.Event(),threading.Event()]
        def blocked_provider(index):
            entered[index].set()
            release.wait(3)
        tasks=[asyncio.create_task(optional_source_thread(blocked_provider,i)) for i in range(2)]
        try:
            for event in entered:
                await asyncio.wait_for(asyncio.to_thread(event.wait,.3),timeout=.5)
                self.assertTrue(event.is_set())
            # Timeouts cancel the awaiters; both underlying source threads
            # intentionally continue until release.
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
            with self.assertRaises(TimeoutError):
                await asyncio.wait_for(optional_source_thread(lambda: 'never reached'),
                                       timeout=.03)
            current=await asyncio.wait_for(
                asyncio.to_thread(lambda:('CANDIDATE_AVAILABLE',BACKGROUND.get(),
                                           OPTIONAL_SOURCE.get())), timeout=.25)
            self.assertEqual(current,('CANDIDATE_AVAILABLE',False,False))
        finally:
            release.set()
        self.assertFalse(OPTIONAL_SOURCE.get())

    async def test_optional_source_context_not_leaked_into_subsequent_command(self):
        asyncio.get_running_loop().set_default_executor(IsolatedExecutor())
        a=await optional_source_thread(lambda: (BACKGROUND.get(),OPTIONAL_SOURCE.get()))
        b=await asyncio.to_thread(lambda: (BACKGROUND.get(),OPTIONAL_SOURCE.get()))
        self.assertEqual(a,(False,True))
        self.assertEqual(b,(False,False))

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

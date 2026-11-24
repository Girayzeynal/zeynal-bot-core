"""One serial background lane and one responsive command/DNS lane.

Only installed by the isolated test-bot entry point. All existing research
to_thread calls remain serial; no scientific module or policy is rewritten.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar

BACKGROUND=ContextVar('isolated_background_work',default=False)
OPTIONAL_SOURCE=ContextVar('isolated_optional_source_work',default=False)


async def optional_source_thread(fn,*args,**kwargs):
    """Place slow, cancellable-at-await optional source work off command lane.

    Cancellation of asyncio.to_thread does not stop an underlying blocking
    worker. A source call that outlives its deadline must not prevent the
    next authoritative candidate lookup from running.
    """
    token=OPTIONAL_SOURCE.set(True)
    try:
        return await asyncio.to_thread(fn,*args,**kwargs)
    finally:
        OPTIONAL_SOURCE.reset(token)


def background_task(coroutine):
    token=BACKGROUND.set(True)
    try:return asyncio.create_task(coroutine)
    finally:BACKGROUND.reset(token)


class IsolatedExecutor(ThreadPoolExecutor):
    def __init__(self):
        super().__init__(max_workers=1,thread_name_prefix='telegram-command')
        self.background=ThreadPoolExecutor(max_workers=1,thread_name_prefix='hybrid-research')
        self.optional_source=ThreadPoolExecutor(max_workers=2,thread_name_prefix='optional-source')

    def submit(self,fn,/,*args,**kwargs):
        # run_in_executor submits in the calling task's context. to_thread
        # also copies that context into the selected worker as usual.
        if BACKGROUND.get():return self.background.submit(fn,*args,**kwargs)
        if OPTIONAL_SOURCE.get():return self.optional_source.submit(fn,*args,**kwargs)
        return super().submit(fn,*args,**kwargs)

    def shutdown(self,wait=True,*,cancel_futures=False):
        self.background.shutdown(wait=wait,cancel_futures=cancel_futures)
        self.optional_source.shutdown(wait=wait,cancel_futures=cancel_futures)
        super().shutdown(wait=wait,cancel_futures=cancel_futures)

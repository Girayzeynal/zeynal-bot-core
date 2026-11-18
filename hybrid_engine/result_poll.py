"""Independent, serial result collectors. One source failure cannot starve NBA."""
import asyncio
import sqlite3
import time
from core.team_identity import digest


async def poll_once(jobs,journal):
    results={}
    for name,job in jobs:
        try:
            value=await asyncio.to_thread(job)
            # A completed Python call is not evidence of a complete source.
            native=value.get('status') if isinstance(value,dict) else None
            status=('SOURCE_INCOMPLETE' if isinstance(native,str) and native.startswith('SOURCE_') else
                    'ABSTAIN' if native in ('ABSTAIN','BLOCKED') else
                    'FAILED' if native in ('FAILED','ERROR') else 'CHECKED')
            results[name]=dict(status=status,result=value,completed_at_utc=int(time.time()))
        except (ValueError,KeyError,TypeError,OSError,sqlite3.Error,RuntimeError) as exc:
            # Never journal raw exception strings, API URLs, or credentials.
            event=dict(kind='RESULT_POLL_FAILED',collector=name,error_type=type(exc).__name__,observed_at_utc=int(time.time()))
            try:await asyncio.to_thread(journal.append,digest(dict(event=event,nonce=time.time_ns())),event)
            except (ValueError,OSError,sqlite3.Error):pass
            results[name]=dict(status='FAILED',error_type=type(exc).__name__,completed_at_utc=int(time.time()))
    return results

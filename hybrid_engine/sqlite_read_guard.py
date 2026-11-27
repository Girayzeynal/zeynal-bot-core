"""Bounded SQLite read handling; no writes or schema changes."""
import sqlite3
import time

BUSY_SECONDS=3.
SQL_SECONDS=10.
RETRY_DELAYS=(.15,.45)

def error_reason(exc):
    if isinstance(exc,sqlite3.OperationalError):
        code=getattr(exc,'sqlite_errorcode',None)
        primary=(code & 255) if isinstance(code,int) else None
        msg=str(exc).lower()
        if primary==5 or 'database is locked' in msg or 'database is busy' in msg:return 'SQLITE_BUSY'
        if primary==6 or 'database table is locked' in msg:return 'SQLITE_LOCKED'
        if primary==9 or msg=='interrupted':return 'SQLITE_QUERY_INTERRUPTED'
        if primary==14 or 'unable to open database file' in msg:return 'SQLITE_CANTOPEN'
        if primary==10 or 'disk i/o error' in msg:return 'SQLITE_IOERR'
        if (primary is None or primary==1) and msg.startswith('no such table:'):return 'SQLITE_SCHEMA_MISSING'
        return 'SQLITE_OPERATIONAL_ERROR'
    reason=str(exc)
    return reason if reason.isupper() and len(reason)<100 and reason.replace('_','').isalnum() else type(exc).__name__

def retry_read(fn):
    for attempt in range(len(RETRY_DELAYS)+1):
        try:return fn()
        except sqlite3.OperationalError as exc:
            if error_reason(exc) not in ('SQLITE_BUSY','SQLITE_LOCKED','SQLITE_QUERY_INTERRUPTED') or attempt==len(RETRY_DELAYS):raise
            time.sleep(RETRY_DELAYS[attempt])

def bounded_rows(db,sql,args=(),*,budget=SQL_SECONDS):
    # Count SQLite stepping time, not native JSON validation between rows.
    # A suspended generator does not consume the SQL execution budget.
    remaining=float(budget)
    def step(fn):
        nonlocal remaining
        if remaining<=0:raise sqlite3.OperationalError('interrupted')
        start=time.monotonic();deadline=start+remaining
        db.set_progress_handler(lambda:int(time.monotonic()>deadline),1000)
        try:return fn()
        finally:
            db.set_progress_handler(None,0)
            remaining-=time.monotonic()-start
    cursor=step(lambda:db.execute(sql,args))
    try:
        while True:
            row=step(cursor.fetchone)
            if row is None:break
            yield row
    finally:cursor.close()

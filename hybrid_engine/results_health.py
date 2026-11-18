"""Read-only native result health, distinct from scheduler/replay health."""
import time
import sqlite3

from ledger_reports import LedgerReports


def inspect(path, *, asof_utc=None):
    now=int(time.time()) if asof_utc is None else asof_utc
    if type(now) is not int or not 0<now<=int(time.time()):raise ValueError('RESULT_HEALTH_ACTUAL_CLOCK')
    try:report=LedgerReports(path).read('NBA')
    except (ValueError,OSError,sqlite3.Error) as exc:
        return dict(status='ARCHIVE_NOT_VERIFIED',source='LIVE_NBA_LEDGER',error_type=type(exc).__name__,query_read_only=True)
    if report['status']!='VERIFIED_LIVE_REPORT':
        return dict(status=report['status'],source='LIVE_NBA_LEDGER',query_read_only=True)
    rows=report['forecasts'];pending=[r for r in rows if r['actual'] is None]
    return dict(status='PENDING_STARTED_RESULTS' if any(r['fixture_start_utc']<=now for r in pending) else 'CHECKED',
        source='LIVE_NBA_LEDGER',observed_at_utc=now,unique_fixtures=report['unique_fixtures'],
        settled_forecasts=len(rows)-len(pending),pending_forecasts=len(pending),
        pending_started_fixtures=len({r['fixture_id'] for r in pending if r['fixture_start_utc']<=now}),
        pending_future_fixtures=len({r['fixture_id'] for r in pending if r['fixture_start_utc']>now}),
        # Started is deliberately not called final: native final evidence is required.
        pending_provider_ids=sorted({p for r in pending if r['fixture_start_utc']<=now for p in r['provider_fixture_ids']}),
        scope='REGULATION_ONLY',query_read_only=True,forecasts_changed=False)


def render(health, poll=None):
    lines=['NBA sonuç kaynağı: canlı değişmez tahmin arşivi',
           'Sonuç denetimi: '+health['status']]
    if 'settled_forecasts' in health:
        lines.append(f"Sonuçlu tahmin {health['settled_forecasts']} · Bekleyen tahmin {health['pending_forecasts']}")
        lines.append(f"Bekleyen maç: başlamış {health['pending_started_fixtures']} · gelecekte {health['pending_future_fixtures']}")
        if health['pending_started_fixtures']:lines.append('Başlamış kayıtlar için doğrulanmış final eksik; sonuç uydurulmadı.')
    if poll:
        live=poll.get('LIVE_NBA',{})
        lines.append('Son NBA sonuç kolektörü: '+live.get('status','HENÜZ_ÇALIŞMADI'))
        value=live.get('result') or {}
        if value.get('unavailable_dates'):lines.append('Eksik kaynak günü: '+', '.join(value['unavailable_dates']))
        if value.get('invalid_dates'):lines.append('Reddedilen kaynak günü: '+', '.join(r['date'] for r in value['invalid_dates']))
    return '\n'.join(lines)

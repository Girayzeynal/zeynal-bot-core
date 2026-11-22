"""Sanitized analysis-exception evidence: not a prediction or archive verdict.

Never echo exception messages or tracebacks into Telegram; they can include
API URLs, credentials or private filesystem paths. Keep evidence in memory.
"""
import asyncio
from pathlib import Path
import re
import sqlite3
import time

STAGES={
    'nba_replay':'NBA_REPLAY',
    'live_nba':'NBA_LIVE_MODEL',
    'nba_ledger':'NBA_LEDGER',
    'prediction_ledger':'PREDICTION_LEDGER',
    'ledger_reports':'ARCHIVE_REPORT',
    'decision_integration':'DECISION_LAYER',
    'verified_analysis':'VERIFIED_ANALYSIS',
    'universal_analysis':'FIXTURE_IDENTITY',
    'telegram_delivery':'DELIVERY',
    'runtime_identity':'RUNTIME_WRAPPER',
    'test_bot':'TEST_BOT_DISPATCH',
    'current_roster':'ROSTER_REVIEW',
    'data':'NATIVE_SOURCE',
    'market_panels':'MARKET_PANEL',
}
KINDS={
    'TimeoutError':'TIMEOUT',
    'OperationalError':'DATABASE_OPERATION',
    'IntegrityError':'DATABASE_INTEGRITY',
    'DatabaseError':'DATABASE_ERROR',
    'ConnectionError':'NETWORK_CONNECTION',
    'ClientError':'NETWORK_CLIENT',
    'KeyError':'MISSING_REQUIRED_FIELD',
    'ValueError':'VALIDATION_ERROR',
    'TypeError':'TYPE_ERROR',
    'OSError':'IO_ERROR',
    'RuntimeError':'RUNTIME_ERROR',
    'AssertionError':'ASSERTION_ERROR',
}


def summarize(exc,*,clock=time.time):
    """Return stable bounded categories, never original error text or paths."""
    if isinstance(exc,(asyncio.TimeoutError,TimeoutError)):
        kind='TIMEOUT'
    elif isinstance(exc,sqlite3.OperationalError):
        kind='DATABASE_OPERATION'
    elif isinstance(exc,sqlite3.DatabaseError):
        kind='DATABASE_ERROR'
    elif isinstance(exc,ConnectionError):
        kind='NETWORK_CONNECTION'
    elif isinstance(exc,OSError):
        kind='IO_ERROR'
    else:
        kind=KINDS.get(type(exc).__name__,'UNEXPECTED_EXCEPTION')
    stage='SERVICE_UNKNOWN'
    tb=exc.__traceback__
    while tb is not None:
        name=Path(tb.tb_frame.f_code.co_filename).stem
        if name in STAGES:
            stage=STAGES[name]
        tb=tb.tb_next
    return dict(format='ANALYSIS_EXCEPTION_DIAGNOSTIC_V1',
        status='EXCEPTION_NOT_ARCHIVE_VERDICT',
        code='ANALYZE_'+kind,
        stage=stage,
        observed_at_utc=int(clock()),
        archive_corruption_verified=False,
        model_retrained=False,
        diagnostic_only=True)


def render(record):
    code=record['code'] if isinstance(record,dict) else 'ANALYZE_UNEXPECTED_EXCEPTION'
    stage=record['stage'] if isinstance(record,dict) else 'SERVICE_UNKNOWN'
    if not (isinstance(code,str) and re.fullmatch('[A-Z_]{6,64}',code)):
        code='ANALYZE_UNEXPECTED_EXCEPTION'
    if not (isinstance(stage,str) and re.fullmatch('[A-Z_]{3,40}',stage)):
        stage='SERVICE_UNKNOWN'
    return ('Analiz servisi beklenmeyen bir hata verdi. '
        'Hata: '+code+' | Aşama: '+stage+'\n'
        'Bu mesaj arşivin bozulduğunu veya 30 dakikalık rapor sınırına takıldığını kanıtlamaz. '
        'Durum için /test runtime komutunu kullan. '
        'Analizin tamamlandığı doğrulanmadı.')

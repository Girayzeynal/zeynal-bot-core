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
    'current_assessment':'CURRENT_ASSESSMENT_DISPLAY',
    'fixture_rejection_diagnostic':'FIXTURE_REJECTION_DIAGNOSTIC',
    'frozen_archive':'FROZEN_REPLAY',
    'verified_history':'HISTORICAL_SOURCE',
    'live_analysis_ledger':'LIVE_ANALYSIS_LEDGER',
    'season_archive_inventory':'ARCHIVE_INVENTORY',
    'season_archive_collect':'NATIVE_FETCH',
    'team_identity':'TEAM_IDENTITY',
    'production_parity':'PRODUCTION_PARITY',
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
    # The previous version reported only the last matching wrapper (often
    # TEST_BOT_DISPATCH). Preserve the exact in-repository code location that
    # raised the exception; do not expose source paths or exception strings.
    origin=None
    tb=exc.__traceback__
    while tb is not None:
        filename=tb.tb_frame.f_code.co_filename
        name=Path(filename).stem
        module=tb.tb_frame.f_globals.get('__name__','')
        allowed=(name in STAGES or
            isinstance(module,str) and
            (module.startswith(('hybrid_engine.','core.','baseline.','providers.')) or
             module in ('main','verified_analysis','universal_analysis',
                 'telegram_delivery','live_analysis_ledger','season_archive_inventory',
                 'season_archive_collect','projection_integrity')))
        if allowed and re.fullmatch('[a-z][a-z0-9_]{1,63}',name):
            origin=dict(file=name+'.py',line=int(tb.tb_lineno))
            stage=STAGES.get(name,'PROJECT_COMPONENT')
        tb=tb.tb_next
    return dict(format='ANALYSIS_EXCEPTION_DIAGNOSTIC_V1',
        status='EXCEPTION_NOT_ARCHIVE_VERDICT',
        code='ANALYZE_'+kind,
        stage=stage,
        origin=origin,
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
    origin=record.get('origin') if isinstance(record,dict) else None
    location=''
    if isinstance(origin,dict):
        file=origin.get('file')
        line=origin.get('line')
    if (isinstance(file,str) and re.fullmatch(r'[a-z][a-z0-9_]{1,63}\.py',file)
                and type(line) is int and 1<=line<=100000):
            location=' | Kod satırı: '+file+':'+str(line)
    return ('Analiz servisi beklenmeyen bir hata verdi. '
        'Hata: '+code+' | Aşama: '+stage+location+'\n'
        'Bu mesaj arşivin bozulduğunu veya 30 dakikalık rapor sınırına takıldığını kanıtlamaz. '
        'Durum için /test runtime komutunu kullan. '
        'Analizin tamamlandığı doğrulanmadı.')

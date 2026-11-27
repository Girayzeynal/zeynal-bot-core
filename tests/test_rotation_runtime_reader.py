"""Exercise rotation runtime path without modifying registered historical reader."""
import sqlite3
from unittest.mock import patch
from hybrid_engine.runtime_reports import RuntimeLedgerReports
from hybrid_engine.sqlite_read_guard import error_reason
from ledger_reports import LedgerReports
from live_analysis_ledger import LiveAnalysisLedger
from tests.test_phase91 import ten_game_ledger

def test_rotation_runtime_snapshot_releases_lock_before_validation(tmp_path):
    path=tmp_path/'games.sqlite'
    ten_game_ledger(path,count=74)
    expected=LedgerReports(path).read('NBA')
    decode=LiveAnalysisLedger._decode
    elapsed=[0.]
    def slow_validate(*args,**kwargs):
        writer=sqlite3.connect(path,timeout=0)
        try:
            writer.execute('BEGIN EXCLUSIVE')
            writer.rollback()
        finally:writer.close()
        elapsed[0]+=.12
        return decode(*args,**kwargs)
    before=path.read_bytes()
    with patch('time.monotonic',side_effect=lambda:elapsed[0]),patch.object(LiveAnalysisLedger,'_decode',side_effect=slow_validate):
        actual=RuntimeLedgerReports(path).read('NBA',summarize=False)
    assert actual['forecasts']==expected['forecasts']
    assert actual['groups']==[]
    assert path.read_bytes()==before

def test_legacy_python_schema_classification():
    assert error_reason(sqlite3.OperationalError('no such table: private'))=='SQLITE_SCHEMA_MISSING'

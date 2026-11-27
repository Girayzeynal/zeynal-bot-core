import sqlite3
import time

import pytest

from hybrid_engine.runtime_reports import RuntimeLedgerReports, failure
from hybrid_engine.unified_results_view import accuracy_sections
from ledger_reports import LedgerReports
from live_analysis_ledger import LiveAnalysisLedger
from tests.test_phase91 import ten_game_ledger
from tests.test_season_archive_audit import NOW


def test_validation_does_not_consume_sqlite_query_deadline_or_hold_read_lock(tmp_path, monkeypatch):
    path = tmp_path/'games.sqlite'
    ten_game_ledger(path, count=74)
    expected = LedgerReports(path).read('NBA')
    decode = LiveAnalysisLedger._decode
    elapsed = [0.]
    monkeypatch.setattr('time.monotonic', lambda:elapsed[0])

    def slow_validate(*args, **kwargs):
        elapsed[0] += .12  # deterministic simulation of busy device validation
        return decode(*args, **kwargs)

    monkeypatch.setattr(LiveAnalysisLedger, '_decode', staticmethod(slow_validate))
    with pytest.raises(sqlite3.OperationalError) as err:
        LedgerReports(path).read('NBA')
    assert err.value.sqlite_errorcode == sqlite3.SQLITE_INTERRUPT

    def exclusive_validate(*args, **kwargs):
        with sqlite3.connect(path, timeout=0) as writer:
            writer.execute('BEGIN EXCLUSIVE')
        return slow_validate(*args, **kwargs)

    monkeypatch.setattr(LiveAnalysisLedger, '_decode', staticmethod(exclusive_validate))
    before = path.read_bytes()
    runtime = RuntimeLedgerReports(path)
    actual = runtime.read('NBA')
    assert actual == expected
    reduced = runtime.read('NBA', fit='a'*64, archived_by=NOW, settled_only=True, summarize=False)
    assert len(reduced['forecasts']) == 1 and not reduced['groups']
    assert path.read_bytes() == before


def test_actual_sqlite_error_classes_distinguish_busy_and_corruption(tmp_path):
    path = tmp_path/'games.sqlite'
    ten_game_ledger(path, count=1)
    with sqlite3.connect(path) as db, pytest.raises(sqlite3.OperationalError) as err:
        db.execute('BEGIN EXCLUSIVE')
        RuntimeLedgerReports(path).read('NBA')
    assert failure(err.value) == 'SQLITE_BUSY (SQLITE_BUSY/5)'
    path.write_bytes(b'not a database'*100)
    with pytest.raises(sqlite3.DatabaseError) as err:
        RuntimeLedgerReports(path).read('NBA')
    assert 'SQLITE_INTEGRITY (SQLITE_NOTADB/26)' == failure(err.value)


def test_accuracy_isolates_native_reader_candidate_and_market_failures(tmp_path):
    path = tmp_path/'games.sqlite'
    ten_game_ledger(path, count=1)
    nba = RuntimeLedgerReports(path).read('NBA')

    class Reader:
        def read(self, league, fixture):
            if league == 'NBA':
                return {'report': nba}
            if league == 'EUROLEAGUE':
                raise ValueError('REPORT_NATIVE_SCORE_CONFLICT')
            return dict(status='VERIFIED_LIVE_REPORT', forecasts=[], groups=[])

    def candidate():
        raise TimeoutError

    def market(reports):
        assert set(reports) == {'NBA', 'EUROCUP'}
        return 'İddaa örnek raporu'

    text = accuracy_sections(Reader(), candidate=candidate, market=market)
    assert 'NBA: 1 model' in text
    assert 'EUROCUP: 0 model' in text
    assert 'EUROLEAGUE · Arşiv okunamadı · REPORT_NATIVE_SCORE_CONFLICT' in text
    assert 'Güncel aday performansı · Okunamadı · REPORT_TIMEOUT' in text
    assert 'İddaa örnek raporu' in text


def test_gateway_html_error_preserves_native_http_status_and_delivery_is_unconfirmed(tmp_path):
    import asyncio
    from unittest.mock import AsyncMock, patch
    from telegram.request import HTTPXRequest
    from hybrid_engine.test_bot import AuditedRequest
    from telegram_delivery import DeliveryJournal

    async def exercise():
        request = AuditedRequest(DeliveryJournal(tmp_path/'audit.sqlite'))
        try:
            with patch.object(HTTPXRequest,'do_request',new_callable=AsyncMock,
                              return_value=(502,b'<html>Bad Gateway</html>')):
                result = await request.do_request('https://api.telegram.org/botsynthetic/sendMessage','POST')
            assert result[0]==502
            assert request.journal_status=='WRITTEN'
        finally:
            await request.shutdown()
    asyncio.run(exercise())



def test_pair_diagnostics_measure_pace_fit_age_and_period_errors_below_promotion_sample():
    from hybrid_engine.paired_error_axes import summarize
    periods={'home':[25,25,25,25],'away':[24,24,24,24]}
    old=dict(prediction=[104,96],actual=[100,96],actual_periods=periods,predicted_quarters=[[26,24]]*4)
    new=dict(old,fixture_id='one',prediction=[108,100],predicted_quarters=[[27,25]]*4,
             estimated_possessions=99.,parameter_age_seconds=120)
    result=summarize([(new,old)])
    assert result['n']==1 and result['mean_total_revision']==8
    assert result['original_total_bias']==4 and result['candidate_total_bias']==12
    assert result['quarters'][0]['candidate_mae']==3 and result['quarters'][0]['original_mae']==1
    assert result['mean_estimated_possessions']==99 and result['parameter_age_range_seconds']==[120,120]
    assert result['causal_attribution'] is False


def test_sqlite_diagnostic_works_without_new_python_result_constants(monkeypatch):
    legacy = sqlite3.OperationalError('private path or query')
    monkeypatch.delattr(sqlite3, 'SQLITE_BUSY', raising=False)
    assert failure(legacy) == 'SQLITE_OTHER'
    legacy.sqlite_errorcode = 5
    legacy.sqlite_errorname = 'SQLITE_BUSY'
    assert failure(legacy) == 'SQLITE_BUSY (SQLITE_BUSY/5)'
    legacy.sqlite_errorname = 'private path'
    assert failure(legacy) == 'SQLITE_BUSY'


def test_nba_result_health_uses_runtime_reader_without_old_validation_deadline(tmp_path, monkeypatch):
    from hybrid_engine.results_health import inspect, render
    path = tmp_path/'games.sqlite'
    ten_game_ledger(path, count=12)
    decode = LiveAnalysisLedger._decode
    elapsed = [0.]
    monkeypatch.setattr('time.monotonic', lambda:elapsed[0])
    def slow_validate(*args, **kwargs):
        elapsed[0] += .2
        return decode(*args, **kwargs)
    monkeypatch.setattr(LiveAnalysisLedger, '_decode', staticmethod(slow_validate))
    before = path.read_bytes()
    health = inspect(path, asof_utc=NOW)
    assert health['status'] == 'CHECKED'
    assert health['settled_forecasts'] == 1
    assert health['pending_forecasts'] == 11
    assert health['pending_future_fixtures'] == 11
    assert 'Sonuçlu tahmin 1' in render(health)
    assert path.read_bytes() == before


def test_nba_result_health_failure_is_explicit_and_redacted(tmp_path, monkeypatch):
    from hybrid_engine.results_health import inspect, render
    path = tmp_path/'games.sqlite'
    ten_game_ledger(path, count=1)
    def locked(*args, **kwargs):
        exc = sqlite3.OperationalError('PRIVATE_SQLITE_PATH')
        exc.sqlite_errorcode = 5
        exc.sqlite_errorname = 'SQLITE_BUSY'
        raise exc
    monkeypatch.setattr(RuntimeLedgerReports, 'read', locked)
    health = inspect(path, asof_utc=NOW)
    assert health['status'] == 'ARCHIVE_NOT_VERIFIED'
    assert health['error_code'] == 'SQLITE_BUSY'
    assert 'settled_forecasts' not in health
    assert 'PRIVATE_SQLITE_PATH' not in str(health)
    assert 'SQLITE_BUSY' in render(health)
    def invalid(*args, **kwargs):
        raise ValueError('PRIVATE_UPPERCASE_TOKEN')
    monkeypatch.setattr(RuntimeLedgerReports, 'read', invalid)
    health = inspect(path, asof_utc=NOW)
    assert health['error_code'] == 'REPORT_VALIDATION_FAILED'
    assert 'PRIVATE_UPPERCASE_TOKEN' not in str(health)

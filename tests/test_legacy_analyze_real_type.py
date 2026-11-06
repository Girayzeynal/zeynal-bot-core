"""Run extracted legacy handler with its real declared imports, no bot startup.

Synthetic data, real Python output class. No credentials or API/network calls.
"""
import ast
from datetime import datetime,timedelta,timezone
from pathlib import Path
import types
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from faz13_engine import Faz13CoreOutput,FixtureContext,TeamAverages
from tests.test_telegram_analyze_failclosed import load_handler


class LegacyAnalyzeTypeBindingTests(IsolatedAsyncioTestCase):
    async def test_real_output_type_is_bound_by_main_import_before_stage_pipeline(self):
        handler=load_handler();tree=ast.parse((Path(__file__).resolve().parents[1]/'main.py').read_text())
        imports=[n for n in tree.body if isinstance(n,ast.ImportFrom) and n.module=='faz13_engine']
        exec(compile(ast.Module(body=imports,type_ignores=[]),'main-real-imports','exec'),handler.__globals__)
        day=(datetime.now(ZoneInfo('Europe/Istanbul')).date()+timedelta(days=1)).isoformat()
        avg=TeamAverages(100,100,100,10)
        core=Faz13CoreOutput(ctx=FixtureContext('NBA',day,'Home','Away'),home_avg=avg,away_avg=avg,
            total_band=(190,210),home_band=(95,105),away_band=(95,105),ou_direction='NO_SIGNAL',quarters={},
            blowout_risk='UNKNOWN',tempo_flag='SYNTHETIC_TEST',meta={'data_quality':'VERIFIED_BASELINE'})
        baseline=types.SimpleNamespace(n_games=6,updated_ts=datetime.now(timezone.utc).timestamp(),pts_for=100,pts_against=100,pace=100,stdev_total=10)
        stage23=types.SimpleNamespace(apply_decision=lambda c:c,record_snapshot=AsyncMock())
        context=types.SimpleNamespace(application=types.SimpleNamespace(bot_data={
            'faz13':types.SimpleNamespace(run_prematch=AsyncMock(return_value=core)),
            'baseline_bootstrapper':types.SimpleNamespace(ensure_async=AsyncMock(return_value=baseline)),
            'faz22':types.SimpleNamespace(score_and_finalize=lambda c:c),'faz23':stage23}))
        message=types.SimpleNamespace(text=f'/analyze NBA {day} Home vs Away',reply_text=AsyncMock())
        await handler(types.SimpleNamespace(message=message),context)
        stage23.record_snapshot.assert_awaited_once_with(core)
        self.assertEqual(message.reply_text.await_args.kwargs.get('parse_mode'),'HTML')

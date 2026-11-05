"""Real trimmed finals and synthetic source-bound prospective audit regression."""
from copy import deepcopy
from pathlib import Path
import json
import sqlite3
import time
import unittest
from unittest.mock import AsyncMock
from prospective_error_audit import errors,period_final,record_period_result,audit
from tests import test_faz24 as fixtures
from tests.test_bound_result_pipeline import summary
from faz24 import build_bundle
from providers.espn_bound_results import reconcile_bound_result
from historical_backtest import HistoricalPrediction
from walk_forward_calibration import evaluate_walk_forward


class ErrorMathTests(unittest.TestCase):
    def test_signed_errors_and_total_cancellation_are_distinct(self):
        r=errors(108.49,105.58,106,112)
        self.assertEqual((r['home_error'],r['away_error'],r['total_absolute_error']),(2.49,-6.42,3.93))
        self.assertEqual(r['margin_error'],8.91)
        self.assertFalse(r['winner_direction_correct'])

    def test_real_final_periods_and_corruption(self):
        cases=json.loads((Path(__file__).parent/'fixtures/faz29-real-final-periods.json').read_text())
        for fixture,raw in cases.items():
            with self.subTest(fixture=fixture):
                r=period_final(raw,int(time.time()))
                self.assertFalse(r['overtime']);self.assertEqual(r['event']['provider_fixture_id'],fixture)
                bad=deepcopy(raw);bad['header']['competitions'][0]['competitors'][0]['linescores'][0]['displayValue']='999'
                with self.assertRaises(ValueError):period_final(bad,int(time.time()))
                bad=deepcopy(raw);bad['header']['competitions'][0]['status']['type']['completed']=False
                with self.assertRaises(ValueError):period_final(bad,int(time.time()))

    def test_missing_periods_cannot_validate_regulation(self):
        raw=summary(int(time.time())-7200)
        with self.assertRaises(ValueError):period_final(raw,int(time.time()))

    def test_results_observed_later_or_at_prediction_never_train_earlier_fold(self):
        rows=[HistoricalPrediction('a','NBA',10,100,110,100,100,90,fixture_start_ts_utc=20),
              HistoricalPrediction('b','NBA',40,80,110,100,100,90,fixture_start_ts_utc=50),
              HistoricalPrediction('c','NBA',100,120,110,100,100,90,fixture_start_ts_utc=110)]
        r=evaluate_walk_forward(rows,1)
        self.assertEqual(r['evaluated_games'],1)
        self.assertEqual(r['folds'][0]['training_games'],1)
        self.assertEqual(r['folds'][0]['latest_training_result_ts_utc'],80)


class AuditIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.setup=fixtures.Faz24Tests();await self.setup.asyncSetUp()
        self.addCleanup(self.setup.doCleanups)
        self.fx=self.setup.fixture;self.addCleanup(self.fx.folder.cleanup)
        # All timestamps/source rows/results in this integration case are synthetic.
        self.fx.fixture['provider_fixture_id']='99001'
        cores=[self.fx.core,deepcopy(self.fx.core),deepcopy(self.fx.core)]
        self.setup.bundle=build_bundle(cores,'a'*40,{})
        await self.setup.persist()
        self.raw=summary(self.fx.tipoff,source_id='99001')
        c=self.raw['header']['competitions'][0]
        for side,tid,lines in ((0,'2',[20,30,40,25]),(1,'18',[25,25,30,28])):
            c['competitors'][side]['team']['id']=tid
            c['competitors'][side]['linescores']=[{'displayValue':str(x)} for x in lines]
        self.fx.adapter._get_json=AsyncMock(return_value=self.raw)

    async def ingest(self):
        from unittest.mock import patch
        with patch('time.time',return_value=self.fx.tipoff+7200):
            result=await reconcile_bound_result(adapter=self.fx.adapter,ledger=self.fx.ledger,fixture_id='99001')
            self.assertEqual(result['status'],'accepted')
            record_period_result(self.fx.ledger,'99001',self.raw,self.fx.tipoff+7200)
            return audit([self.fx.ledger.db_path])

    async def test_versions_and_scopes_do_not_merge_and_originals_unchanged(self):
        with self.fx.ledger._connect() as db:before=db.execute('SELECT * FROM faz24_stages').fetchall()
        r=await self.ingest()
        self.assertEqual(r['distinct_fixtures'],1);self.assertEqual(len(r['cohorts']),2)
        self.assertEqual({g['scope'] for g in r['cohorts']},{'FINAL_WITH_OT','REGULATION_ONLY'})
        self.assertTrue(all(g['metrics']['n_games']==1 for g in r['cohorts']))
        with self.fx.ledger._connect() as db:self.assertEqual(before,db.execute('SELECT * FROM faz24_stages').fetchall())

    async def test_idempotent_periods_and_readonly_audit(self):
        from unittest.mock import patch
        await self.ingest()
        with patch('time.time',return_value=self.fx.tipoff+7300):
            self.assertFalse(record_period_result(self.fx.ledger,'99001',self.raw,self.fx.tipoff+7300))
            before=Path(self.fx.ledger.db_path).read_bytes();audit([self.fx.ledger.db_path])
            self.assertEqual(before,Path(self.fx.ledger.db_path).read_bytes())
        with self.fx.ledger._connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM period_result_evidence').fetchone()[0],1)

    async def test_duplicate_research_ledgers_cannot_inflate_sample(self):
        from unittest.mock import patch
        await self.ingest()
        with patch('time.time',return_value=self.fx.tipoff+7300),self.assertRaises(ValueError):
            audit([self.fx.ledger.db_path,self.fx.ledger.db_path])

    async def test_period_tamper_is_rejected(self):
        from unittest.mock import patch
        await self.ingest()
        with self.fx.ledger._connect() as db:
            db.execute('DROP TRIGGER period_result_no_UPDATE')
            db.execute("UPDATE period_result_evidence SET sha256='tampered'")
        with patch('time.time',return_value=self.fx.tipoff+7300),self.assertRaises(ValueError):audit([self.fx.ledger.db_path])

    async def test_audit_never_regenerates_original_simulation(self):
        from unittest.mock import patch
        await self.ingest()
        with patch('time.time',return_value=self.fx.tipoff+7300):
            with patch('prematch_monte_carlo.PrematchMonteCarloEngine.simulate',side_effect=AssertionError('no retrospective simulation')):
                r=audit([self.fx.ledger.db_path])
        self.assertEqual(len(r['cohorts']),2)

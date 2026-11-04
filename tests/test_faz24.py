"""Synthetic prospective collection; no historical observation is backdated."""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import time
import unittest
from unittest.mock import patch
from tests import test_prediction_input_binding as fixtures
from faz24 import build_bundle, report, collect
from faz22_engine import Faz22Engine
from faz23_engine import Faz23Engine
from nba_prematch_orchestrator import persist_resolved_nba_prematch
from prediction_inputs import digest


class Faz24Tests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fixture=fixtures.PredictionInputBindingTests()
        await self.fixture.asyncSetUp()
        self.addCleanup(self.fixture.folder.cleanup)
        self.addCleanup(self.fixture.doCleanups)
        self.ledger=self.fixture.ledger
        first=deepcopy(self.fixture.core)
        second=Faz22Engine().score_and_finalize(deepcopy(first))
        third=Faz23Engine(str(Path(self.fixture.folder.name)/'decisions.sqlite')).apply_decision(deepcopy(second))
        self.bundle=build_bundle([first,second,third],'a'*40)

    async def persist(self):
        return await persist_resolved_nba_prematch(adapter=self.fixture.adapter,
            ledger=self.ledger,core=self.fixture.core,stage_bundle=self.bundle)

    async def test_atomic_collection_and_readonly_empty_result_report(self):
        self.assertTrue((await self.persist())['inserted'])
        before=Path(self.ledger.db_path).read_bytes()
        result=report(self.ledger.db_path)
        self.assertEqual(before,Path(self.ledger.db_path).read_bytes())
        self.assertEqual(result['prospective']['sample_size'],0)
        self.assertIsNone(result['stages']['FAZ23']['metrics'])
        self.assertEqual(result['historical_walk_forward']['evaluated_games'],0)

    async def test_exact_retry_is_idempotent_changed_stage_is_rejected(self):
        await self.persist()
        self.assertFalse((await self.persist())['inserted'])
        self.bundle['stages'][2]['output']['meta']['risk']='ALTERED'
        with self.assertRaises(ValueError): await self.persist()

    async def test_actual_tipoff_guard_cannot_be_bypassed_with_old_generated_time(self):
        with patch('faz24.time.time',return_value=time.time()+86400*10):
            with self.assertRaises(ValueError): await self.persist()
        self.fixture.assert_no_prediction()

    async def test_stage_projection_change_rolls_back_all_records(self):
        self.bundle['stages'][1]['output']['meta']['expected_home']+=5
        with self.assertRaises(ValueError): await self.persist()
        self.fixture.assert_no_prediction()

    async def test_no_posthoc_stage_attachment(self):
        await self.fixture.persist()
        with self.assertRaisesRegex(ValueError,'attach stages'): await self.persist()

    async def test_sql_update_delete_forbidden(self):
        await self.persist()
        for sql in ('DELETE FROM faz24_stages',"UPDATE faz24_stages SET sha256='bad'"):
            with self.assertRaises(sqlite3.IntegrityError):
                with self.ledger._connect() as db: db.execute(sql)

    async def test_digest_and_binding_corruption_refused(self):
        await self.persist()
        with self.ledger._connect() as db:
            db.execute('DROP TRIGGER faz24_no_update')
            db.execute("UPDATE faz24_stages SET sha256='corrupt'")
        with self.assertRaises(ValueError): report(self.ledger.db_path)

    async def test_late_stage_and_wrong_order_rejected(self):
        self.bundle['stages'][0]['captured_at_utc']=int(time.time())+999999
        with self.assertRaises(ValueError): await self.persist()
        self.fixture.assert_no_prediction()

    async def test_automatic_pipeline_captures_all_three_stages(self):
        from unittest.mock import AsyncMock
        engine=type('Engine',(),{})()
        engine.run_prematch=AsyncMock(return_value=deepcopy(self.fixture.core))
        finalizer=Faz23Engine(str(Path(self.fixture.folder.name)/'runner.sqlite'))
        result=await collect(engine=engine,request=self.fixture.request,adapter=self.fixture.adapter,
            ledger=self.ledger,model_version='b'*40,finalizer=finalizer)
        self.assertTrue(result['inserted'])
        with self.ledger._connect() as db:
            bundle=json.loads(db.execute('SELECT payload FROM faz24_stages').fetchone()[0])
        self.assertEqual([s['stage'] for s in bundle['stages']],['FAZ13','FAZ22','FAZ23'])

    async def test_canonical_insert_failure_rolls_back_stage_bundle(self):
        with self.ledger._connect() as db:
            db.execute("CREATE TRIGGER fail_prediction BEFORE INSERT ON predictions BEGIN SELECT RAISE(ABORT,'test failure'); END")
        with self.assertRaises(sqlite3.IntegrityError): await self.persist()
        self.fixture.assert_no_prediction()
        with self.ledger._connect() as db:
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'faz24_stages' in tables:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM faz24_stages').fetchone()[0],0)

    async def test_espn_observation_time_uses_nested_source_snapshot(self):
        core=deepcopy(self.fixture.core)
        rows=core.meta['input_snapshot']['payload']['teams']['home']['records']
        for row in rows:
            row['pace_evidence']={'snapshot':{'observed_at_utc':123}}
        bundle=build_bundle([core,deepcopy(core),deepcopy(core)],'c'*40)
        self.assertEqual(bundle['freshness']['latest_source_observation_utc'],123)
        self.assertEqual(bundle['freshness']['missing_observation_times'],6)

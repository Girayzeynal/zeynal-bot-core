"""Bounded offline collection contracts; no real forecasts or external messages."""
from copy import deepcopy
from contextlib import redirect_stderr
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock,patch

from core.team_identity import digest
from hybrid_engine.player_inputs import collect_batch,load_snapshot,main
from tests import test_player_minutes as minutes

NOW=minutes.NOW


class PlayerBatchTests(TestCase):
    def setUp(self):
        tmp=TemporaryDirectory(); self.addCleanup(tmp.cleanup); self.root=Path(tmp.name)
        timer=patch('time.time',return_value=NOW); timer.start(); self.addCleanup(timer.stop)
        self.ledger=self.root/'ledger.sqlite'; self.ledger.write_bytes(b'SYNTHETIC_READ_ONLY_PLACEHOLDER')
        self.output=self.root/'shadow'; self.snapshots={}
        self.rows=[]
        for i in range(6):
            snapshot=dict(fixture_id=str(i),prediction=dict(home=100,away=90))
            self.snapshots[str(i)]=snapshot
            self.rows.append(dict(fixture_id=str(i),snapshot_sha256=digest(snapshot),actual=None,
                fixture_start_utc=NOW+3600+i*60,provider_fixture_ids=[str(401000000+i)],home='Home',away='Away'))
        self.loader=Mock(side_effect=lambda path,fid:deepcopy(self.snapshots[fid]))
        self.collector=Mock(side_effect=lambda s,a,d:dict(fixture_id=s['fixture_id'],
            status='PROSPECTIVE_MINUTES_ARCHIVED',projection='a'*64,new_record=True,reason=None))

    def run_batch(self,**kw):
        report=dict(status='VERIFIED_LIVE_REPORT',forecasts=self.rows)
        with patch('hybrid_engine.player_inputs.LedgerReports.read',return_value=report):
            return collect_batch(self.ledger,self.root/'assets',self.output,
                collect_one=self.collector,loader=self.loader,**kw)

    def test_dry_run_lists_only_bounded_future_fixtures_without_sources_or_writes(self):
        before=self.ledger.read_bytes(); r=self.run_batch(dry_run=True)
        self.assertEqual(r['status'],'DRY_RUN'); self.assertEqual(r['eligible_total'],6)
        self.assertEqual([r['fixture_id'] for r in r['selected']],['0','1','2','3'])
        self.loader.assert_not_called(); self.collector.assert_not_called()
        self.assertEqual(self.ledger.read_bytes(),before); self.assertTrue(r['database_bytes_unchanged'])
        self.assertFalse(self.output.exists())

    def test_collection_is_sequential_bounded_and_preserves_ledger(self):
        r=self.run_batch(maximum=2)
        self.assertEqual(r['status'],'COMPLETED'); self.assertEqual(len(r['results']),2)
        self.assertEqual(r['remaining_eligible'],4)
        self.assertEqual([c.args[0]['fixture_id'] for c in self.collector.call_args_list],['0','1'])
        self.assertTrue(r['database_bytes_unchanged']); self.assertFalse(r['forecast_changed'])
        self.assertFalse(r['online_training']); self.assertFalse(r['actual_telegram_delivery_verified'])
        saved=json.loads(next(self.output.glob('batch-*')).read_text())
        self.assertEqual(digest(saved['payload']),saved['sha256'])

    def test_started_settled_near_tipoff_and_far_future_fixtures_are_excluded(self):
        self.rows[0]['fixture_start_utc']=NOW
        self.rows[1]['actual']=[100,90]
        self.rows[2]['fixture_start_utc']=NOW+899
        self.rows[3]['fixture_start_utc']=NOW+48*3600+1
        r=self.run_batch(dry_run=True)
        self.assertEqual([r['fixture_id'] for r in r['selected']],['4','5'])
        self.assertEqual(set(r['skipped']),{'MATCH_ALREADY_STARTED','ALREADY_HAS_FINAL_RESULT',
            'INSUFFICIENT_PRETIPOFF_COLLECTION_WINDOW','OUTSIDE_PROSPECTIVE_WINDOW'})

    def test_exact_lead_and_horizon_boundaries_are_inclusive(self):
        self.rows=self.rows[:2]; self.rows[0]['fixture_start_utc']=NOW+900
        self.rows[1]['fixture_start_utc']=NOW+48*3600
        self.assertEqual(self.run_batch(dry_run=True)['eligible_total'],2)

    def test_duplicate_model_versions_are_not_arbitrarily_selected(self):
        self.rows.append(dict(self.rows[0],snapshot_sha256='b'*64))
        r=self.run_batch(dry_run=True)
        self.assertEqual(r['skipped']['AMBIGUOUS_ARCHIVED_MODELS'],1)
        self.assertNotIn('0',[r['fixture_id'] for r in r['selected']])

    def test_existing_first_inputs_do_not_starve_new_fixtures_or_repeat_downloads(self):
        publication=dict(projection=dict(payload=dict(fixture_id='0')))
        (self.output/'minutes').mkdir(parents=True)
        with patch('hybrid_engine.player_inputs.MinutesArchive.first',return_value=[publication]),patch(
                'hybrid_engine.player_inputs.validate_witness',return_value=dict(original_snapshot_sha256=self.rows[0]['snapshot_sha256'])):
            r=self.run_batch(maximum=1)
        self.assertEqual(r['skipped']['ALREADY_ARCHIVED_MINUTES'],1)
        self.assertEqual(self.loader.call_args.args[1],'1')

    def test_existing_input_linked_to_another_snapshot_is_not_overwritten(self):
        (self.output/'minutes').mkdir(parents=True)
        publication=dict(projection=dict(payload=dict(fixture_id='0')))
        with patch('hybrid_engine.player_inputs.MinutesArchive.first',return_value=[publication]),patch(
                'hybrid_engine.player_inputs.validate_witness',return_value=dict(original_snapshot_sha256='f'*64)):
            r=self.run_batch(dry_run=True)
        self.assertEqual(r['skipped']['ORIGINAL_SNAPSHOT_LINK_CONFLICT'],1)
        self.collector.assert_not_called()

    def test_invalid_existing_witness_blocks_without_new_downloads(self):
        (self.output/'minutes').mkdir(parents=True)
        with patch('hybrid_engine.player_inputs.MinutesArchive.first',side_effect=ValueError('bad')):
            r=self.run_batch(dry_run=True)
        self.assertEqual(r['status'],'BLOCKED'); self.collector.assert_not_called()

    def test_two_consecutive_blocks_stop_more_source_requests(self):
        self.collector.side_effect=lambda s,a,d:dict(fixture_id=s['fixture_id'],status='BLOCKED',reason='MISSING_SOURCE')
        r=self.run_batch()
        self.assertEqual(r['status'],'PARTIAL'); self.assertEqual(len(r['results']),2)
        self.assertEqual(r['remaining_eligible'],6)
        self.assertEqual(r['reason'],'CONSECUTIVE_SOURCE_OR_INPUT_BLOCKS')

    def test_admission_deadline_prevents_next_fixture_without_claiming_hard_timeout(self):
        with patch('hybrid_engine.player_inputs.time.monotonic',side_effect=[0,181]):
            r=self.run_batch()
        self.assertEqual(r['status'],'PARTIAL'); self.assertEqual(r['results'],[])
        self.collector.assert_not_called()
        self.assertEqual(r['reason'],'ADMISSION_TIME_BUDGET_EXHAUSTED')

    def test_near_tipoff_is_rechecked_before_each_fixture(self):
        with patch('time.time',side_effect=[NOW,NOW+3600]):
            r=self.run_batch(maximum=1)
        self.collector.assert_not_called()
        self.assertEqual(r['results'][0]['reason'],'COLLECTION_WINDOW_CLOSED_DURING_BATCH')

    def test_snapshot_change_between_plan_and_read_does_not_get_new_inputs(self):
        self.loader.side_effect=lambda *args:dict(fixture_id='changed')
        r=self.run_batch(maximum=1)
        self.assertEqual(r['status'],'COMPLETED_WITH_BLOCKS'); self.collector.assert_not_called()

    def test_exception_text_and_source_secrets_are_not_exposed(self):
        self.loader.side_effect=ValueError('SECRET_DO_NOT_EXPOSE')
        r=self.run_batch(maximum=1)
        self.assertNotIn('SECRET_DO_NOT_EXPOSE',json.dumps(r))
        self.assertEqual(r['results'][0]['status'],'BLOCKED')

    def test_missing_ledger_is_not_created(self):
        self.ledger.unlink(); r=self.run_batch(dry_run=True)
        self.assertEqual(r['status'],'BLOCKED'); self.assertFalse(self.ledger.exists())
        self.assertFalse(self.output.exists()); self.collector.assert_not_called()

    def test_unverified_schema_is_not_reported_as_successful_empty_batch(self):
        with patch('hybrid_engine.player_inputs.LedgerReports.read',return_value=dict(status='NO_VERIFIED_LIVE_SCHEMA')):
            r=collect_batch(self.ledger,self.root/'assets',self.output,dry_run=True)
        self.assertEqual(r['status'],'BLOCKED'); self.collector.assert_not_called()

    def test_concurrent_external_ledger_change_is_reported_without_restore(self):
        def external_update(s,a,d):
            self.ledger.write_bytes(b'EXTERNAL_TEST_WRITER')
            return dict(fixture_id=s['fixture_id'],status='BLOCKED',reason='SOURCE')
        self.collector.side_effect=external_update
        r=self.run_batch(maximum=1)
        self.assertFalse(r['database_bytes_unchanged']); self.assertEqual(r['status'],'BLOCKED')
        self.assertEqual(self.ledger.read_bytes(),b'EXTERNAL_TEST_WRITER')
        self.assertIn('NO_RESTORE_ATTEMPT',r['reason'])

    def test_bounded_configuration_and_boolean_types_are_enforced(self):
        for kw in (dict(maximum=True),dict(maximum=9),dict(minimum_lead_seconds=0),
                   dict(window_seconds=49*3600),dict(maximum_seconds=1000),dict(failure_limit=0),dict(dry_run=1)):
            with self.subTest(kw=kw),self.assertRaises(ValueError): self.run_batch(**kw)
        self.collector.assert_not_called()

    def test_cli_rejects_mixed_single_and_batch_modes_before_ledger_access(self):
        argv=['player_inputs','--ledger',str(self.ledger),'--assets-directory','assets',
              '--output-directory',str(self.output),'--fixture-id','123','--all-pending']
        with patch('sys.argv',argv),patch('hybrid_engine.player_inputs.collect_batch') as batch:
            with redirect_stderr(StringIO()),self.assertRaises(SystemExit): main()
        batch.assert_not_called()

    def test_real_sqlite_dry_run_and_snapshot_lookup_preserve_all_bytes(self):
        from tests.test_ledger_reports import fixture
        from tests.test_season_archive_audit import START
        self.ledger.unlink(); fixture(self.ledger,settled=False)
        before=self.ledger.read_bytes()
        with patch('time.time',return_value=START-50):
            r=collect_batch(self.ledger,self.root/'assets',self.output,dry_run=True)
            snapshot=load_snapshot(self.ledger,'401000123')
        self.assertEqual(r['status'],'DRY_RUN'); self.assertEqual(len(r['selected']),0)
        self.assertEqual(r['skipped']['INSUFFICIENT_PRETIPOFF_COLLECTION_WINDOW'],1)
        self.assertEqual(snapshot['provider_fixture_ids'],['401000123'])
        self.assertEqual(self.ledger.read_bytes(),before)
        self.assertFalse(self.output.exists())

    def test_report_disk_failure_is_not_hidden_as_a_successful_saved_batch(self):
        before=self.ledger.read_bytes()
        with patch('hybrid_engine.player_inputs.publish_json',side_effect=OSError('synthetic-disk-full')):
            with self.assertRaises(OSError): self.run_batch(maximum=1)
        self.assertEqual(self.ledger.read_bytes(),before)

    def test_batch_retains_safe_per_player_roster_diagnostics(self):
        self.collector.side_effect=lambda s,a,d:dict(fixture_id=s['fixture_id'],status='BLOCKED',
            reason='ABSENCE_REQUIRES_BOTH_SOURCE_OBSERVATIONS',
            roster_diagnostics=dict(missing_absence_count=1,official_stage='INDEX_FETCH'))
        r=self.run_batch(maximum=1)
        self.assertEqual(r['results'][0]['roster_diagnostics']['missing_absence_count'],1)

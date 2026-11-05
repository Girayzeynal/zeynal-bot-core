"""PR #14 regressions. All captures and recovery fixtures are SYNTHETIC_TEST."""
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import unittest
from unittest.mock import AsyncMock, patch

import faz39
from faz34 import cut_proofs
from faz39_recovery import snapshot, restore
from faz37 import ClockDiscontinuity
from prediction_inputs import digest
from tests import test_faz39 as base


class SourceBudgetTests(unittest.TestCase):
    def test_git_failure_is_a_refusal_not_an_empty_source_identity(self):
        with patch('faz39.subprocess.check_output', side_effect=subprocess.CalledProcessError(1,'git')):
            with self.assertRaisesRegex(faz39.Refused,'SOURCE_GIT_FAILED'):faz39.local_source()

    def test_subprocess_timeout_is_explicit_and_bounded(self):
        with patch('faz39.subprocess.check_output', side_effect=subprocess.TimeoutExpired('git', .1)) as git:
            with self.assertRaisesRegex(faz39.Refused, 'SOURCE_VERIFICATION_TIMEOUT'):
                faz39.local_source(budget_seconds=.1)
        self.assertGreater(git.call_args.kwargs['timeout'], 0)
        self.assertLessEqual(git.call_args.kwargs['timeout'], .1)

    def test_total_budget_applies_across_all_commands_not_per_command(self):
        now = [0.]
        def git(args, **kwargs):
            now[0] += .3
            return 'feature/faz39-test' if args[1] == 'branch' else 'a'*40
        with patch('faz39.time.perf_counter', side_effect=lambda:now[0]), \
             patch('faz39.subprocess.check_output', side_effect=git) as command:
            with self.assertRaisesRegex(faz39.Refused, 'SOURCE_VERIFICATION_TIMEOUT'):
                faz39.local_source(budget_seconds=.5)
        self.assertEqual(command.call_count, 2)

    def test_slow_source_file_read_also_expires_total_budget(self):
        now = [0.]
        def git(args, **kwargs):
            return {'branch':'feature/faz39-test', 'rev-parse':'a'*40, 'status':'',
                    'ls-files':'', 'show':b'code'}[args[1]]
        def read(path):
            now[0] += 2
            return b'code'
        with patch('faz39.time.perf_counter', side_effect=lambda:now[0]), \
             patch('faz39.subprocess.check_output', side_effect=git), \
             patch.object(Path, 'read_bytes', read):
            with self.assertRaisesRegex(faz39.Refused, 'SOURCE_VERIFICATION_TIMEOUT'):
                faz39.local_source()

    def test_descriptive_quantiles_include_errors_and_bound_memory(self):
        timings = faz39.Timings()
        for n in range(1, 101):timings.record('operation', n)
        self.assertEqual(timings.summary()['operation']['p95_ms'], 95)
        self.assertEqual(timings.summary()['operation']['p99_ms'], 99)
        with self.assertRaises(ValueError):
            with timings.measure('failure'):raise ValueError('synthetic failure')
        self.assertEqual(timings.summary()['failure']['errors'], 1)
        for n in range(5000):timings.record('bounded', n)
        self.assertEqual(timings.summary()['bounded']['count'], 4096)
        self.assertEqual(timings.summary()['bounded']['dropped'], 904)


class ReviewTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        original_clock, original_sleep = time.time, asyncio.sleep
        def assert_clock_isolation():
            self.assertIs(time.time, original_clock)
            self.assertIs(asyncio.sleep, original_sleep)
        self.addCleanup(assert_clock_isolation)
        self.b = base.ReadinessTests(); await self.b.asyncSetUp()
        # The helper IsolatedAsyncioTestCase has no runner; its doCleanups()
        # would swallow _callMaybeAsync assertions instead of stopping patches.
        for function, args, kwargs in self.b._cleanups:
            self.addCleanup(function, *args, **kwargs)
        self.b._cleanups.clear()
        self.fx, self.p, self.store = self.b.fx, self.b.p, self.b.store

    def portable(self):
        self.p.update(schema_version=2, ledger_id=self.store.ledger_id,
                      config_sha256=self.store.config_hash(self.b.config()),
                      original_config_sha256=digest(self.b.config()))
        return self.p

    async def test_two_valid_receipts_cannot_claim_the_same_existing_cut(self):
        first = self.b.runner()
        other = deepcopy(self.p); other['ready_utc'] -= .1
        self.store.put(other)
        other_gate = self.b.gate(other)
        second = faz39.ArmedRunner(faz39.EvidenceLedger(self.fx.ledger.path, 'SYNTHETIC_TEST', other_gate), other_gate)
        self.fx.clock.now = base.fixtures.BASE + 3
        self.assertEqual((await faz39.capture_armed(first))['status'], 'RECORDED')
        original = Path(self.fx.ledger.path).read_bytes()
        result = await faz39.capture_armed(second)
        self.assertEqual(result['reason'], 'EXISTING_CUT_BINDING_CONFLICT')
        self.assertEqual(result['new_synthetic_cuts'], 0)
        self.assertEqual(Path(self.fx.ledger.path).read_bytes(), original)

    async def test_existing_cut_rejects_different_model_fixture_and_receipt(self):
        runner = self.b.runner(); self.fx.clock.now = base.fixtures.BASE + 3
        await faz39.capture_armed(runner); before = cut_proofs(self.fx.ledger.path)
        for mutate in (lambda p:p['source'].update(sha='b'*40),
                       lambda p:p['fixture'].update(start_ts_utc=p['fixture']['start_ts_utc']+60),
                       lambda p:p['fixture'].update(home_team_id='999'),
                       lambda p:p.update(ready_utc=p['ready_utc']-.1)):
            p = deepcopy(self.p); mutate(p)
            with self.assertRaisesRegex(faz39.Refused, 'BINDING_CONFLICT'):
                faz39.existing_cut(self.fx.ledger, p, digest(p))
        self.assertEqual(before, cut_proofs(self.fx.ledger.path))

    async def test_arm_duplicate_receipt_conflict_does_not_fetch_or_write(self):
        self.p['config_sha256'] = digest(self.b.config())
        runner = self.b.runner(); other = deepcopy(self.p); other['ready_utc'] -= .1
        sha = self.store.put(other)
        self.fx.clock.now = base.fixtures.BASE + 3; await faz39.capture_armed(runner)
        before = cut_proofs(self.fx.ledger.path); client = AsyncMock()
        with patch('faz39.CutLedger', return_value=self.fx.ledger):
            with self.assertRaisesRegex(faz39.Refused, 'EXISTING_CUT_BINDING_CONFLICT'):
                await faz39.arm(self.b.config(), sha, client)
        client.fetch.assert_not_awaited(); self.assertEqual(before, cut_proofs(self.fx.ledger.path))

    async def test_identical_duplicate_is_verified_after_window_without_generation(self):
        runner = self.b.runner(); self.fx.clock.now = base.fixtures.BASE + 3
        await faz39.capture_armed(runner)
        self.fx.clock.now += 10000
        result = await faz39.capture_armed(runner)
        self.assertEqual(result['status'], 'ALREADY_RECORDED')
        self.assertEqual(result['existing_proof']['receipt_sha256'], digest(self.p))
        self.assertEqual(result['existing_proof']['model_sha'], self.p['source']['sha'])
        self.assertEqual(result['timings']['existing_cut_comparison']['count'], 1)

    async def test_legacy_non_faz39_prediction_is_not_misreported_as_same_receipt(self):
        self.fx.clock.now = base.fixtures.BASE + 3
        await self.fx.capture()
        with self.assertRaisesRegex(faz39.Refused, 'EXISTING_CUT_BINDING_CONFLICT'):
            faz39.existing_cut(self.fx.ledger, self.p, digest(self.p))

    async def test_cut_proofs_delay_cannot_authorize_late_generation(self):
        runner = self.b.runner(); self.fx.clock.now = base.fixtures.BASE + 284
        real = faz39.cut_proofs
        def slow(path):
            self.fx.clock.now += 28
            return real(path)
        with patch('faz39.cut_proofs', side_effect=slow), \
             patch.object(runner, 'capture', new_callable=AsyncMock) as generate:
            result = await faz39.capture_armed(runner)
        generate.assert_not_awaited(); self.assertEqual(result['reason'], 'MISSED_CUT')
        self.assertEqual(result['timings']['cut_proofs']['count'], 2)
        self.b.assert_no_cut()

    async def test_ledger_has_delay_cannot_authorize_late_generation(self):
        runner = self.b.runner(); self.fx.clock.now = base.fixtures.BASE + 284
        def slow(*args):
            self.fx.clock.now += 28
            return False
        with patch.object(runner.ledger, 'has', side_effect=slow), \
             patch.object(runner, 'capture', new_callable=AsyncMock) as generate:
            result = await faz39.capture_armed(runner)
        generate.assert_not_awaited(); self.assertEqual(result['reason'], 'MISSED_CUT')
        self.assertEqual(result['timings']['ledger_has']['count'], 1); self.b.assert_no_cut()

    async def test_sqlite_lock_wait_and_failure_are_measured(self):
        runner = self.b.runner(); self.fx.clock.now = base.fixtures.BASE + 3
        with self.fx.ledger.connect() as lock:
            lock.execute('BEGIN IMMEDIATE')
            result = await faz39.capture_armed(runner)
        self.assertEqual(result['status'], 'REFUSED')
        metrics = result['timings']['sqlite_begin_immediate']
        self.assertEqual(metrics['errors'], 1); self.assertGreater(metrics['max_ms'], 500)
        self.b.assert_no_cut()

    async def test_success_measures_sqlite_final_gate_inside_transaction(self):
        runner = self.b.runner(); self.fx.clock.now = base.fixtures.BASE + 3
        result = await faz39.capture_armed(runner)
        for label in ('git_source_check','cut_proofs','ledger_has','sqlite_begin_immediate',
                      'sqlite_cut_insert','sqlite_final_gate'):
            self.assertGreater(result['timings'][label]['count'], 0)
        self.assertEqual(result['timings']['sqlite_final_gate']['errors'], 0)

    async def test_portable_ready_moves_path_but_keeps_identity_and_exact_receipt(self):
        self.portable(); sha = self.store.put(self.p)
        bundle = snapshot(self.fx.ledger.path, self.fx.root/'ready.tar.gz', 'a'*40)['bundle']
        result = restore(bundle['path'], self.fx.root/'relocated', bundle['sha256'])
        ledger = faz39.CutLedger(self.fx.root/'relocated'/'faz39.sqlite','SYNTHETIC_TEST')
        moved = faz39.ReadyStore(ledger); config = deepcopy(self.b.config())
        config['collection']['database'] = ledger.path
        moved.check_config(config, moved.get(sha))
        self.assertEqual(moved.get(sha), self.p); self.assertEqual(moved.ledger_id, self.store.ledger_id)
        self.assertFalse(result['separate_cloud_runtime_verified'])

    async def test_portable_ready_can_arm_in_relocated_synthetic_store(self):
        self.portable();sha=self.store.put(self.p)
        bundle=snapshot(self.fx.ledger.path,self.fx.root/'portable.tar.gz','a'*40)['bundle']
        restore(bundle['path'],self.fx.root/'new-runtime-directory',bundle['sha256'])
        ledger=faz39.CutLedger(self.fx.root/'new-runtime-directory'/'faz39.sqlite','SYNTHETIC_TEST')
        config=deepcopy(self.b.config());config['collection']['database']=ledger.path
        config['collection']['research_database']=str(self.fx.root/'not-read-after-freeze.sqlite')
        client=AsyncMock();client.fetch.return_value=base.utc_proof(self.fx.clock.now)
        guard=faz39.ClockGuard(wall=self.fx.clock.time,monotonic=lambda:self.fx.clock.now+100000)
        with patch('faz39.CutLedger',return_value=ledger), \
             patch('faz39.ClockGuard',return_value=guard), \
             patch('faz39.local_source',return_value=self.p['source']):
            result=await faz39.arm(config,sha,client)
        self.assertEqual(result['new_synthetic_cuts'],1);self.assertEqual(result['new_prospective_cuts'],0)
        self.assertEqual(faz39.audit(ledger.path)['faz39_bound_cuts'],1)
        self.assertEqual(cut_proofs(self.fx.ledger.path),{})

    async def test_legacy_ready_remains_bound_to_its_original_config(self):
        self.p['config_sha256']=digest(self.b.config());sha=self.store.put(self.p)
        moved=deepcopy(self.b.config());moved['collection']['database']=str(self.fx.root/'elsewhere.sqlite')
        with self.assertRaisesRegex(faz39.Refused,'READY_CONFIG_MISMATCH'):
            self.store.check_config(moved,self.store.get(sha))

    async def test_copying_receipt_without_ledger_identity_is_rejected(self):
        self.portable(); self.store.put(self.p)
        other = faz39.ReadyStore(faz39.CutLedger(self.fx.root/'other.sqlite','SYNTHETIC_TEST'))
        with self.assertRaisesRegex(faz39.Refused, 'READY_LEDGER_ID_MISMATCH'):other.put(self.p)

    async def test_new_process_restores_ready_and_original_cut_without_rearming(self):
        self.portable(); runner = self.b.runner(); self.fx.clock.now = base.fixtures.BASE + 3
        await faz39.capture_armed(runner); before = cut_proofs(self.fx.ledger.path)
        bundle = snapshot(self.fx.ledger.path, self.fx.root/'complete.tar.gz', 'a'*40)['bundle']
        output = self.fx.root/'restarted'
        code = "import sys,json;sys.path.insert(0,sys.argv[1]);from faz39_recovery import restore;print(json.dumps(restore(sys.argv[2],sys.argv[3],sys.argv[4])))"
        process = subprocess.run([sys.executable,'-I','-c',code,str(Path(faz39.__file__).parent),
            bundle['path'],str(output),bundle['sha256']],check=True,capture_output=True,text=True,timeout=30)
        restored = json.loads(process.stdout)
        self.assertEqual(restored['audit']['faz39_ready_receipts'], 1)
        self.assertEqual(restored['audit']['faz39_bound_cuts'], 1)
        self.assertEqual(cut_proofs(output/'faz39.sqlite'), before)
        self.assertFalse(restored['separate_cloud_runtime_verified'])
        self.assertFalse(restored['rearms_expired_cut'])

    async def test_corrupt_wrong_pin_and_overwrite_recovery_are_rejected(self):
        self.portable(); self.store.put(self.p)
        bundle = snapshot(self.fx.ledger.path,self.fx.root/'backup.tar.gz','a'*40)['bundle']
        with self.assertRaisesRegex(ValueError, 'checksum'):
            restore(bundle['path'], self.fx.root/'wrong', '0'*64)
        restore(bundle['path'], self.fx.root/'once', bundle['sha256'])
        with self.assertRaises(FileExistsError):restore(bundle['path'],self.fx.root/'once',bundle['sha256'])
        corrupted = self.fx.root/'corrupt.tar.gz';corrupted.write_bytes(Path(bundle['path']).read_bytes()+b'corrupt')
        with self.assertRaisesRegex(ValueError,'checksum'):
            restore(corrupted,self.fx.root/'corrupt-result',bundle['sha256'])

    async def test_semantically_corrupt_ready_is_rejected_before_restore_publication(self):
        from research_recovery import make_bundle
        self.portable();self.store.put(self.p)
        copy=self.fx.root/'tampered.sqlite'
        with self.fx.ledger.connect() as source,sqlite3.connect(copy) as target:source.backup(target)
        with sqlite3.connect(copy) as db:
            db.execute('DROP TRIGGER faz39_identity_no_UPDATE')
            db.execute("UPDATE faz39_identity SET ledger_id=?",('b'*32,))
        bundle=make_bundle({'faz39.sqlite':copy},self.fx.root/'bad-ready.tar.gz','a'*40)
        destination=self.fx.root/'must-not-publish'
        with self.assertRaisesRegex(faz39.Refused,'READY_LEDGER_ID_MISMATCH'):
            restore(bundle['path'],destination,bundle['sha256'])
        self.assertFalse(destination.exists())

    async def test_ledger_identity_is_sql_immutable(self):
        with self.fx.ledger.connect() as db:
            for sql in ('DELETE FROM faz39_identity',"UPDATE faz39_identity SET ledger_id='bad'",
                        'INSERT OR REPLACE INTO faz39_identity SELECT * FROM faz39_identity'):
                with self.assertRaises(sqlite3.IntegrityError):db.execute(sql)

    async def test_utc_offset_and_rtt_boundaries_and_malformed_schema(self):
        now = self.fx.clock.now
        for offset, valid in ((2,True),(-2,True),(2.0001,False),(-2.0001,False)):
            p = base.utc_proof(now);p['observed_utc'] += offset;p['request_started_utc']=p['observed_utc']-.1
            if valid:faz39.utc_anchor(p)
            else:
                with self.assertRaisesRegex(faz39.Refused,'UTC_ATTESTATION_FAILED'):faz39.utc_anchor(p)
        for rtt,valid in ((2,True),(2.0001,False)):
            p=base.utc_proof(now);p['elapsed_seconds']=rtt
            if valid:faz39.utc_anchor(p)
            else:
                with self.assertRaisesRegex(faz39.Refused,'UTC_ATTESTATION_FAILED'):faz39.utc_anchor(p)
        for raw in ([],{},dict(timeZone='UTC',dateTime='invalid')):
            p=base.proof(raw,faz39.UTC_URL,now)
            with self.assertRaisesRegex(faz39.Refused,'UTC_SCHEMA_CHANGED'):faz39.utc_anchor(p)

    async def test_wall_monotonic_drift_at_and_beyond_two_seconds(self):
        gate=self.b.gate();self.fx.clock.now=base.fixtures.BASE-3
        gate.guard.monotonic=lambda:self.fx.clock.now+100000-2
        gate.guard.check()
        gate.guard.monotonic=lambda:self.fx.clock.now+100000-2.0001
        with self.assertRaises(ClockDiscontinuity):gate.guard.check()

    async def test_future_stale_and_forged_official_sources_fail_closed(self):
        runner=self.b.runner();self.fx.clock.now=base.fixtures.BASE+3
        runner.gate.ready['proofs']['official']['observed_utc']=self.fx.clock.now+100
        result=await faz39.capture_armed(runner)
        self.assertEqual(result['reason'],'READINESS_CHANGED_AFTER_ARM');self.b.assert_no_cut()

    async def test_official_html_schema_change_has_explicit_status(self):
        original=self.p['proofs']['official']
        for body,reason in [('<html>schema changed</html>','OFFICIAL_SCHEDULE_UNAVAILABLE'),
            ('<script id="__NEXT_DATA__">[]</script>','OFFICIAL_SCHEDULE_SCHEMA_CHANGED'),
            ('<script id="__NEXT_DATA__">not-json</script>','OFFICIAL_SCHEDULE_SCHEMA_CHANGED')]:
            p=base.proof(body,original['source_url'],original['observed_utc'])
            with self.assertRaisesRegex(faz39.Refused,reason):
                faz39.official_game(p,self.p['fixture'],self.p['directory'])
        missing=original['body'].replace('gameTimeUtc','changedStartField')
        with self.assertRaisesRegex(faz39.Refused,'OFFICIAL_SCHEDULE_SCHEMA_CHANGED'):
            faz39.official_game(base.proof(missing,original['source_url'],original['observed_utc']),
                                self.p['fixture'],self.p['directory'])


if __name__ == '__main__':unittest.main()

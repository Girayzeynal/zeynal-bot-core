"""Offline harness self-tests and additional adversarial acceptance cases."""
from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import faz39_checkpoint_contract as c
from tests import faz39_offline_acceptance as harness
from tests import test_faz39_checkpoint_contract as fake

ROOT=Path(__file__).resolve().parents[1]


def child(*args,cwd=None):
    return subprocess.run([sys.executable,'-I',str(ROOT/'tests/faz39_offline_acceptance.py'),*args],
                          cwd=cwd,env={'PATH':os.environ.get('PATH','/usr/bin:/bin'),
                                       'PYTHONDONTWRITEBYTECODE':'1'},
                          capture_output=True,text=True,timeout=20)


class AcceptanceTests(unittest.TestCase):
    def test_cli_exercises_required_contracts_but_never_claims_verification(self):
        result=child();self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        d=json.loads(result.stdout)
        self.assertEqual(d['status'],'OFFLINE_ACCEPTANCE_PASS')
        self.assertEqual(d['verification_status'],'NOT_VERIFIED')
        self.assertEqual(d['check_count'],11)
        self.assertEqual(len(set(d['checks'])),11)
        self.assertEqual(d['usage'],'SYNTHETIC_TEST')
        self.assertEqual(d['provider_kind'],'IN_MEMORY_FAKE')
        for key in ['durable_storage_verified','separate_cloud_runtime_verified',
                    'real_external_storage_used','external_upload_performed']:
            self.assertIs(d[key],False)
        self.assertEqual(d['new_real_prospective_records'],0)

    def test_all_nine_broken_implementations_are_detected_fail_closed(self):
        for fault in harness.FAULTS:
            with self.subTest(fault=fault):
                result=child('--fault',fault)
                self.assertEqual(result.returncode,1,result.stdout+result.stderr)
                d=json.loads(result.stdout)
                self.assertEqual(d['status'],'OFFLINE_ACCEPTANCE_FAIL')
                self.assertEqual(d['verification_status'],'NOT_VERIFIED')
                self.assertFalse(d['durable_storage_verified'])
                self.assertFalse(d['separate_cloud_runtime_verified'])

    def test_cli_has_no_remote_database_credentials_or_output_path_options(self):
        for option in ['--provider','--endpoint','--database','--token','--output','--deploy','--scheduler']:
            with self.subTest(option=option):
                self.assertEqual(child(option,'forbidden-input').returncode,2)

    def test_clean_cwd_needs_no_source_workspace_state_and_creates_no_files(self):
        # Source CODE is still available: explicitly not a second runtime test.
        with tempfile.TemporaryDirectory() as folder:
            result=child(cwd=folder)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual(list(Path(folder).iterdir()),[])
            self.assertFalse(json.loads(result.stdout)['separate_cloud_runtime_verified'])

    def test_actual_audit_guard_blocks_network_shell_and_production_imports(self):
        code='''import sys,socket,subprocess,os,importlib
sys.path.insert(0,sys.argv[1])
from tests.faz39_offline_acceptance import offline_guard
sys.addaudithook(offline_guard)
actions=[lambda:socket.socket(),lambda:socket.getaddrinfo('example.invalid',443),
lambda:subprocess.run([sys.executable,'-c','pass']),lambda:os.system('true'),
lambda:importlib.import_module('main'),lambda:importlib.import_module('providers'),
lambda:importlib.import_module('telegram'),lambda:importlib.import_module('dynamic_scheduler')]
for action in actions:
 try:action()
 except PermissionError:pass
 else:raise AssertionError('offline guard allowed operation')
print('OFFLINE_GUARD_PASS')'''
        r=subprocess.run([sys.executable,'-I','-c',code,str(ROOT)],capture_output=True,text=True,timeout=10)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(r.stdout.strip(),'OFFLINE_GUARD_PASS')

    def test_stream_overflow_consumes_at_most_limit_plus_one(self):
        stream=harness.TrackedStream(b'x'*8192)
        with self.assertRaisesRegex(harness.AcceptanceFailure,'LIMIT_EXCEEDED'):
            harness.bounded_stream(stream,31)
        self.assertEqual(stream.transferred,32)
        self.assertTrue(all(0<n<=16 for n in stream.requests))

    def test_stream_exact_length_and_empty_body_are_handled_without_unbounded_read(self):
        for raw,limit in [(b'',1),(b'x'*33,33),(b'abcd',5)]:
            with self.subTest(size=len(raw)):
                stream=harness.TrackedStream(raw)
                self.assertEqual(harness.bounded_stream(stream,limit),raw)
                self.assertTrue(all(n>0 for n in stream.requests))

    def test_stream_lying_chunk_size_wrong_types_or_invalid_limits_are_refused(self):
        class BadStream:
            def __init__(self,value):self.value=value
            def read(self,size):return self.value
        for value in [b'x'*50,'not-bytes',None]:
            with self.subTest(value=type(value).__name__),self.assertRaisesRegex(harness.AcceptanceFailure,'CONTRACT'):
                harness.bounded_stream(BadStream(value),4)
        for limit in [True,0,-1,float('inf')]:
            with self.subTest(limit=limit),self.assertRaisesRegex(harness.AcceptanceFailure,'LIMIT_REQUIRED'):
                harness.bounded_stream(harness.TrackedStream(b''),limit)

    def test_stream_exception_never_returns_partial_content_as_success(self):
        class PartitionedStream:
            def __init__(self):self.calls=0
            def read(self,size):
                self.calls+=1
                if self.calls==1:return b'first'
                raise ConnectionError('SIMULATED_PARTITION')
        with self.assertRaises(ConnectionError):harness.bounded_stream(PartitionedStream(),32)

    def test_stale_pin_and_sql_replica_rollback_cannot_override_retained_high_water(self):
        fx=fake.ContractTests();fx.setUp();before=deepcopy(fx.pin)
        externally_retained=replace(fx.anchor,generation=2,pin_sha256=c.digest(fx.next_pin()))
        # A restored/lagged DB can supply the valid old signed pin. Trust anchor
        # must come from outside that rollback domain, not that DB's old row.
        with self.assertRaisesRegex(c.Refused,'STALE_OR_FORKED'):
            fx.plan(anchor=externally_retained)
        self.assertEqual(fx.pin,before)

    def test_unknown_write_can_commit_after_a_strong_negative_read(self):
        fx=fake.ContractTests();fx.setUp();backend=fake.FakeBackend();store=fx.store(backend)
        pending=[]
        def inflight(key,value):pending.append((key,value));raise TimeoutError('SIMULATED_INFLIGHT')
        original=backend.put_if_absent;backend.put_if_absent=inflight
        with self.assertRaises(TimeoutError):store.put_if_absent('probe',b'original')
        with self.assertRaises(FileNotFoundError):store.read('probe',32)
        backend.put_if_absent=original;original(*pending.pop())
        self.assertFalse(store.put_if_absent('probe',b'original'))
        with self.assertRaises(c.Refused):store.put_if_absent('probe',b'overwrite')
        self.assertEqual(backend.objects['probe'],b'original')

    def test_fake_provider_success_claim_is_rejected_even_when_other_flags_are_false(self):
        for status in ['VERIFIED','CROSS_RUNTIME_VERIFIED','PROVIDER_VERIFIED','REMOTE_RECOVERY_VERIFIED']:
            with self.subTest(status=status),self.assertRaisesRegex(harness.AcceptanceFailure,'CANNOT_VERIFY'):
                harness.unverified(dict(status=status,durable_storage_verified=False,
                                        separate_cloud_runtime_verified=False))

    def test_public_root_sameness_and_replacement_fail_the_acceptance_gate(self):
        for fault in ['same-trust-admin','swapped-trust-root']:
            with self.subTest(fault=fault),self.assertRaises(harness.AcceptanceFailure):
                harness.exercise(fault)


if __name__=='__main__':unittest.main()

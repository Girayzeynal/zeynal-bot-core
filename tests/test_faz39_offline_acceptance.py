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
from unittest.mock import patch

import faz39_checkpoint_contract as c
from tests import faz39_offline_acceptance as harness
from tests import test_faz39_checkpoint_contract as fake

ROOT=Path(__file__).resolve().parents[1]

# Independent expected outputs, not a CLI dispatch from fault name to diagnosis.
FAULT_REJECTIONS = {
    'overwrite': ('AcceptanceFailure','IMMUTABLE_CONDITIONAL_CREATE','immutable_create'),
    'unbounded-read': ('AcceptanceFailure','UNBOUNDED_STREAM_ACCEPTED','bounded_stream'),
    'missing-durable-proof': ('Refused','DURABLE_ACK_EVIDENCE_MISSING','durable_ack'),
    'unconditional-cas': ('AcceptanceFailure','DISTRIBUTED_CAS_MODEL_VIOLATION','pin_cas'),
    'same-runtime': ('Refused','SAME_RUNTIME_OR_FILESYSTEM','runtime_isolation'),
    'same-trust-admin': ('AcceptanceFailure','INDEPENDENT_ADMIN_BOUNDARIES_MISSING','trust_roots'),
    'false-verified': ('AcceptanceFailure','FAKE_PROVIDER_CANNOT_VERIFY','runtime_isolation'),
    'swapped-trust-root': ('AcceptanceFailure','TRUST_ROOT_SUBSTITUTION','trust_roots'),
    'unsafe-lost-ack': ('AcceptanceFailure','LOST_ACK_WAS_FALSE_SUCCESS','lost_ack'),
}


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
                self.assertEqual((d['error_type'],d.get('reason_code'),d.get('rejection_stage')),
                                 FAULT_REJECTIONS[fault])
                self.assertIs(d.get('recognized_rejection'),True)
                self.assertEqual(d.get('rejection_origin'),'CONTRACT_POLICY_REFUSAL' if
                                 fault in ('missing-durable-proof','same-runtime') else 'ACCEPTANCE_ASSERTION')

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

    def assert_actual_refusal(self,fault,stage,code,completed):
        trace=harness.AcceptanceTrace();failures=[];attestations=[]
        original_require=c.require;original_attested=c.attested
        def observed_require(condition,reason):
            if trace.stage==stage and not condition:failures.append(reason)
            return original_require(condition,reason)
        def observed_attestation(raw,purpose,*args):
            result=original_attested(raw,purpose,*args)
            if trace.stage==stage:attestations.append((purpose,deepcopy(result)))
            return result
        with patch.object(c,'require',side_effect=observed_require), \
             patch.object(c,'attested',side_effect=observed_attestation):
            with self.assertRaises(c.Refused) as caught:harness.exercise(fault,trace=trace)
        self.assertIs(type(caught.exception),c.Refused)
        self.assertEqual(str(caught.exception),code)
        self.assertEqual(failures,[code])
        self.assertEqual(trace.stage,stage)
        self.assertEqual(len(trace.checks),completed)
        result=harness.failure_report(caught.exception,trace)
        self.assertEqual(result['reason_code'],code)
        self.assertIs(result['recognized_rejection'],True)
        self.assertEqual(result['rejection_origin'],'CONTRACT_POLICY_REFUSAL')
        return attestations

    def test_missing_durable_proof_fails_required_field_gate_after_valid_attestation(self):
        attestations=self.assert_actual_refusal('missing-durable-proof','durable_ack',
                                                'DURABLE_ACK_EVIDENCE_MISSING',2)
        receipts=[p for purpose,p in attestations if purpose=='FAZ39_DURABLE_ACK']
        self.assertEqual(len(receipts),1)
        self.assertNotIn('provider_receipt_sha256',receipts[0])
        self.assertEqual(set(receipts[0]),{'target_id','object_sha256','storage_identity','simulation'})
        self.assertIs(receipts[0]['simulation'],True)

    def test_same_runtime_fails_identity_guard_after_valid_attestation(self):
        attestations=self.assert_actual_refusal('same-runtime','runtime_isolation',
                                                'SAME_RUNTIME_OR_FILESYSTEM',8)
        payloads=[p for purpose,p in attestations if purpose=='FAZ39_RUNTIME_EVIDENCE']
        self.assertEqual(len(payloads),1)
        source,destination=payloads[0]['source'],payloads[0]['destination']
        self.assertEqual(source['runtime_id'],destination['runtime_id'])
        for field in ['run_id','filesystem_identity','storage_identity']:
            self.assertNotEqual(source[field],destination[field])

    def test_underlying_nine_fault_exceptions_keep_their_original_types_and_codes(self):
        for fault,(kind,code,stage) in FAULT_REJECTIONS.items():
            trace=harness.AcceptanceTrace()
            with self.subTest(fault=fault):
                expected=c.Refused if kind=='Refused' else harness.AcceptanceFailure
                with self.assertRaises(expected) as caught:harness.exercise(fault,trace=trace)
                self.assertIs(type(caught.exception),expected)
                self.assertEqual(str(caught.exception),code)
                self.assertEqual(trace.stage,stage)

    def test_incidental_errors_cannot_impersonate_policy_or_acceptance_failures(self):
        for stage,known in [('durable_ack','DURABLE_ACK_EVIDENCE_MISSING'),
                            ('runtime_isolation','SAME_RUNTIME_OR_FILESYSTEM')]:
            for error in [KeyError(known),TypeError(known),ValueError(known),RuntimeError(known),
                          PermissionError('synthetic-private-message')]:
                trace=harness.AcceptanceTrace();trace.enter(stage)
                with self.subTest(stage=stage,kind=type(error).__name__):
                    report=harness.failure_report(error,trace)
                    self.assertEqual(report['error_type'],type(error).__name__)
                    self.assertEqual(report['reason_code'],'UNEXPECTED_EXCEPTION')
                    self.assertEqual(report['rejection_origin'],'UNEXPECTED_RUNTIME_ERROR')
                    self.assertIs(report['recognized_rejection'],False)
                    self.assertEqual(report['rejection_stage'],stage)
                    self.assertNotIn('synthetic-private-message',json.dumps(report))

    def test_known_refusal_in_wrong_stage_is_not_recognized_or_relabelled(self):
        trace=harness.AcceptanceTrace();trace.enter('runtime_isolation')
        report=harness.failure_report(c.Refused('DURABLE_ACK_EVIDENCE_MISSING'),trace)
        self.assertEqual(report['error_type'],'Refused')
        self.assertEqual(report['reason_code'],'DURABLE_ACK_EVIDENCE_MISSING')
        self.assertEqual(report['rejection_stage'],'runtime_isolation')
        self.assertIs(report['recognized_rejection'],False)

    def test_unknown_refusal_and_assertion_text_are_sanitized_without_changing_type(self):
        trace=harness.AcceptanceTrace();trace.enter('durable_ack')
        for cls,fallback in [(c.Refused,'UNEXPECTED_CONTRACT_REFUSAL'),
                             (harness.AcceptanceFailure,'UNEXPECTED_ACCEPTANCE_ASSERTION')]:
            with self.subTest(cls=cls.__name__):
                report=harness.failure_report(cls('synthetic-private-message'),trace)
                self.assertEqual(report['error_type'],cls.__name__)
                self.assertEqual(report['reason_code'],fallback)
                self.assertIs(report['recognized_rejection'],False)
                self.assertNotIn('synthetic-private-message',json.dumps(report))

    def test_refusal_subclass_cannot_spoof_the_exact_contract_guard(self):
        class DerivedRefusal(c.Refused):pass
        trace=harness.AcceptanceTrace();trace.enter('durable_ack')
        report=harness.failure_report(DerivedRefusal('DURABLE_ACK_EVIDENCE_MISSING'),trace)
        self.assertEqual(report['error_type'],'DerivedRefusal')
        self.assertEqual(report['reason_code'],'UNEXPECTED_EXCEPTION')
        self.assertIs(report['recognized_rejection'],False)

    def test_cli_incidental_errors_at_target_guard_stay_unexpected(self):
        code='''import sys
sys.path.insert(0,sys.argv[1])
from tests import faz39_offline_acceptance as h
import faz39_checkpoint_contract as c
fault=sys.argv[2]
original=c.require
def incident(condition,reason):
 if not condition and reason=='DURABLE_ACK_EVIDENCE_MISSING':raise KeyError('synthetic-private-message')
 if not condition and reason=='SAME_RUNTIME_OR_FILESYSTEM':raise TypeError('synthetic-private-message')
 return original(condition,reason)
c.require=incident
sys.argv=['offline-acceptance','--fault',fault]
raise SystemExit(h.main())'''
        for fault,kind,stage,count in [('missing-durable-proof','KeyError','durable_ack',2),
                                       ('same-runtime','TypeError','runtime_isolation',8)]:
            with self.subTest(fault=fault):
                r=subprocess.run([sys.executable,'-I','-c',code,str(ROOT),fault],
                                 capture_output=True,text=True,timeout=20)
                self.assertEqual(r.returncode,1,r.stdout+r.stderr)
                report=json.loads(r.stdout)
                self.assertEqual(report['error_type'],kind)
                self.assertEqual(report['reason_code'],'UNEXPECTED_EXCEPTION')
                self.assertEqual(report['rejection_stage'],stage)
                self.assertEqual(report['check_count'],count)
                self.assertIs(report['recognized_rejection'],False)
                self.assertEqual(report['verification_status'],'NOT_VERIFIED')
                self.assertNotIn('synthetic-private-message',r.stdout)

    def test_diagnostics_are_identical_across_repeated_nine_fault_runs(self):
        for fault in harness.FAULTS:
            with self.subTest(fault=fault):
                first=child('--fault',fault);second=child('--fault',fault)
                self.assertEqual(first.returncode,1);self.assertEqual(second.returncode,1)
                self.assertEqual(json.loads(first.stdout),json.loads(second.stdout))

    def test_trace_records_real_progress_and_reuse_cannot_inflate_checks(self):
        trace=harness.AcceptanceTrace();result=harness.exercise(trace=trace)
        self.assertEqual(trace.stage,'inflight_write')
        self.assertEqual(trace.checks,result['checks']);self.assertEqual(len(trace.checks),11)
        with self.assertRaisesRegex(harness.AcceptanceFailure,'FRESH_TRACE_REQUIRED'):
            harness.exercise(trace=trace)
        self.assertEqual(len(trace.checks),11)


if __name__=='__main__':unittest.main()

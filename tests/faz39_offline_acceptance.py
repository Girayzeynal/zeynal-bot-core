"""Executable OFFLINE-ONLY acceptance oracle. All providers/trust roots are FAKE.

python -I tests/faz39_offline_acceptance.py
No addresses, credential discovery, input databases or filesystem outputs exist.
Passing this oracle NEVER proves external durability or independent recovery.
"""
import argparse
import io
import json
from pathlib import Path
import sys

FAULTS = ('overwrite', 'unbounded-read', 'missing-durable-proof', 'unconditional-cas',
          'same-runtime', 'same-trust-admin', 'false-verified', 'swapped-trust-root',
          'unsafe-lost-ack')


class AcceptanceFailure(ValueError):
    pass


def require(condition, code):
    if not condition:raise AcceptanceFailure(code)


def offline_guard(event, args):
    if event.startswith('socket.') or event in {
            'subprocess.Popen','os.system','os.exec','os.posix_spawn','os.fork','pty.spawn'}:
        raise PermissionError('OFFLINE_NETWORK_OR_PROCESS_DENIED')
    if event == 'import' and args[0].split('.')[0] in {
            'main','telegram','dynamic_scheduler','providers','faz39_sandbox','faz39_transfer'}:
        raise PermissionError('OFFLINE_PRODUCTION_IMPORT_DENIED')


class TrackedStream(io.BytesIO):
    def __init__(self, raw):
        super().__init__(raw);self.requests=[];self.transferred=0

    def read(self, size=-1):
        self.requests.append(size)
        result=super().read(size);self.transferred+=len(result)
        return result


def bounded_stream(stream, maximum_bytes):
    """Bound decoded bytes while reading, independently of Content-Length/ETag."""
    require(type(maximum_bytes) is int and maximum_bytes > 0,'STREAM_LIMIT_REQUIRED')
    chunks=[];count=0
    while True:
        request=min(16,maximum_bytes-count+1)
        raw=stream.read(request)
        require(type(raw) is bytes and len(raw)<=request,'STREAM_CONTRACT_VIOLATION')
        if not raw:return b''.join(chunks)
        count+=len(raw)
        require(count<=maximum_bytes,'STREAM_LIMIT_EXCEEDED')
        chunks.append(raw)


def expect(error, action, code):
    try:action()
    except error:return
    raise AcceptanceFailure(code)


def unverified(value):
    permitted={'PIN_HEAD_ADVANCED','PIN_ALREADY_CURRENT','RESTORE_PLAN_VALIDATED_NOT_EXECUTED',
               'EVIDENCE_SCHEMA_VALID_NOT_INDEPENDENTLY_VERIFIED',
               'EVIDENCE_PUBLISHED_NOT_INDEPENDENTLY_VERIFIED'}
    require(value.get('durable_storage_verified') is False and
            value.get('separate_cloud_runtime_verified') is False and
            value.get('status') in permitted,'FAKE_PROVIDER_CANNOT_VERIFY')


def exercise(fault=None):
    # Only pure standard-library contract code and deterministic test fixtures.
    from concurrent.futures import ThreadPoolExecutor
    from copy import deepcopy
    from dataclasses import replace
    import hashlib
    import threading
    import faz39_checkpoint_contract as c
    from tests import test_faz39_checkpoint_contract as fake

    require(fault is None or fault in FAULTS,'UNKNOWN_FAULT')
    fx=fake.ContractTests();fx.setUp();passed=[]
    backend=fake.FakeBackend();store=fx.store(backend)
    if fault=='overwrite':
        def overwrite(key,value):backend.objects[key]=value;return True
        backend.put_if_absent=overwrite
    require(store.put_if_absent('synthetic-probe',b'original') is True,'FIRST_CREATE')
    require(store.put_if_absent('synthetic-probe',b'original') is False,'IMMUTABLE_CONDITIONAL_CREATE')
    expect(c.Refused,lambda:store.put_if_absent('synthetic-probe',b'changed!'),'CONFLICT_NOT_REFUSED')
    require(backend.objects['synthetic-probe']==b'original','ORIGINAL_OBJECT_CHANGED')
    passed.append('immutable_conditional_create_and_exact_readback')

    stream=TrackedStream(b'x'*500)
    reader=(lambda s,limit:s.read()) if fault=='unbounded-read' else bounded_stream
    expect(AcceptanceFailure,lambda:reader(stream,31),'UNBOUNDED_STREAM_ACCEPTED')
    require(stream.transferred<=32 and all(0<n<=16 for n in stream.requests),'STREAM_NOT_BOUNDED')
    require(bounded_stream(TrackedStream(b'abcd'),4)==b'abcd','EXACT_STREAM_LENGTH')
    passed.append('decoded_stream_limit_without_trusting_metadata')

    receipt=dict(target_id=store.target_id,object_sha256=hashlib.sha256(b'original').hexdigest(),
                 provider_receipt_sha256='9'*64,storage_identity='synthetic-durable-oracle',simulation=True)
    if fault=='missing-durable-proof':del receipt['provider_receipt_sha256']
    observed=c.attested(fake.envelope(receipt,'FAZ39_DURABLE_ACK'),'FAZ39_DURABLE_ACK',fx.policy,fx.attestor)
    c.fields(observed,'target_id object_sha256 provider_receipt_sha256 storage_identity simulation','DURABLE_ACK_EVIDENCE_MISSING')
    c.hex_id(observed['provider_receipt_sha256'])
    require(observed['simulation'] is True and observed['target_id']==store.target_id and
            observed['object_sha256']==hashlib.sha256(backend.objects['synthetic-probe']).hexdigest(),
            'DURABLE_ACK_BINDING')
    passed.append('simulated_durable_ack_receipt_bound_to_exact_bytes')

    class RaceAuthority(fake.FakeAuthority):
        def __init__(self,current):
            super().__init__(current);self.barrier=threading.Barrier(2);self.seen=threading.local()
        def current(self,*args):
            result=super().current(*args)
            if not getattr(self.seen,'ready',False):
                self.seen.ready=True;self.barrier.wait(timeout=5)
            return result
        def compare_and_swap(self,*args):
            if fault!='unconditional-cas':return super().compare_and_swap(*args)
            with self.lock:self.value=args[-1];self.writes+=1;return True
    authority=RaceAuthority(fx.raw)
    candidates=[fake.envelope(fx.next_pin(storage_identity='synthetic-fork-'+str(i))) for i in range(2)]
    def writer(raw):
        try:
            result=c.advance_pin(authority,fx.anchor,raw,**fx.kw);unverified(result)
            return result['status']
        except c.Refused:return 'REFUSED'
    with ThreadPoolExecutor(max_workers=2) as pool:outcomes=list(pool.map(writer,candidates))
    require(authority.writes==1 and outcomes.count('PIN_HEAD_ADVANCED')==1 and
            outcomes.count('REFUSED')==1,'DISTRIBUTED_CAS_MODEL_VIOLATION')
    passed.append('concurrent_monotonic_cas_and_same_generation_fork_rejection')

    authority=fake.FakeAuthority(fx.raw);original=authority.compare_and_swap
    def lost_ack(*args):original(*args);raise ConnectionError('SIMULATED_LOST_ACK')
    authority.compare_and_swap=lost_ack;candidate=fake.envelope(fx.next_pin())
    def uncertain():
        try:return c.advance_pin(authority,fx.anchor,candidate,**fx.kw)
        except ConnectionError:
            if fault=='unsafe-lost-ack':return {'status':'SUCCESS'}
            raise
    expect(ConnectionError,uncertain,'LOST_ACK_WAS_FALSE_SUCCESS')
    require(authority.writes==1,'LOST_ACK_MUST_NOT_IMPLY_NO_WRITE')
    authority.compare_and_swap=original
    retry=c.advance_pin(authority,fx.anchor,candidate,**fx.kw)
    require(retry['status']=='PIN_ALREADY_CURRENT','EXACT_ACK_RETRY');unverified(retry)
    passed.append('lost_ack_uncertainty_and_exact_retry')

    high=replace(fx.anchor,generation=2,pin_sha256=c.digest(fx.next_pin()))
    expect(c.Refused,lambda:fx.plan(anchor=high),'STALE_PIN_ACCEPTED')
    expect(c.Refused,lambda:fx.plan(fake.envelope(dict(fx.pin,source_runtime_id='synthetic-fork'))),
           'SAME_GENERATION_FORK_ACCEPTED')
    jumped=dict(fx.next_pin(),generation=3)
    expect(c.Refused,lambda:c.advance_pin(authority,fx.anchor,fake.envelope(jumped),**fx.kw),
           'GENERATION_JUMP_ACCEPTED')
    passed.append('stale_pin_fork_and_generation_jump_refused')

    # These are FAKE administrative identities/public fingerprints, not live roots.
    roles=dict(object_admin='synthetic-object-owner',pin_admin='synthetic-pin-owner',
               signing_admin='synthetic-signing-owner')
    if fault=='same-trust-admin':roles['signing_admin']=roles['object_admin']
    require(len(set(roles.values()))==3,'INDEPENDENT_ADMIN_BOUNDARIES_MISSING')
    installed_root=hashlib.sha256(b'FAKE-public-root-outside-checkpoint').hexdigest()
    supplied_root='0'*64 if fault=='swapped-trust-root' else installed_root
    require(supplied_root==installed_root,'TRUST_ROOT_SUBSTITUTION')
    expect(c.Refused,lambda:fx.plan(policy=replace(fx.policy,issuer_id='untrusted-issuer')),
           'UNTRUSTED_ISSUER_ACCEPTED')
    expect(c.Refused,lambda:fx.plan(policy=replace(fx.policy,attestation_scope='INDEPENDENT')),
           'FAKE_ATTESTOR_PROMOTED')
    passed.append('simulated_independent_roots_and_issuer_pinning')

    expect(c.Refused,lambda:fx.plan(now=fake.NOW+3),'STALE_UTC_ACCEPTED')
    expect(c.Refused,lambda:fx.plan(policy=replace(fx.policy,clock_challenge_sha256='f'*64)),
           'UTC_CHALLENGE_REPLAY_ACCEPTED')
    unverified(fx.plan());passed.append('fresh_utc_and_request_challenge_binding')

    p,observation=fx.evidence()
    if fault=='same-runtime':p['destination']['runtime_id']=p['source']['runtime_id']
    result=fx.validate_evidence(p,observation)
    if fault=='false-verified':result.update(status='CROSS_RUNTIME_VERIFIED',durable_storage_verified=True)
    unverified(result)
    require(result['cross_runtime_status']=='NOT_VERIFIED','FAKE_EVIDENCE_PROMOTED')
    for field in ('runtime_id','run_id','filesystem_identity','storage_identity'):
        bad=deepcopy(p);bad['destination'][field]=bad['source'][field]
        expect(c.Refused,lambda:fx.validate_evidence(bad),'SHARED_RUNTIME_OR_STORAGE_ACCEPTED')
    bad=deepcopy(p);bad['storage']['durability']='EPHEMERAL'
    expect(c.Refused,lambda:fx.validate_evidence(bad),'EPHEMERAL_STORAGE_ACCEPTED')
    passed.append('two_runtime_identity_requirements_without_verification_claim')

    backend=fake.FakeBackend();evidence_store=fx.store(backend)
    first=fx.publish(evidence_store,p);second=fx.publish(evidence_store,p)
    require(first['created'] is True and second['created'] is False,'OUTCOME_RETRY_NOT_IDEMPOTENT')
    bad=deepcopy(p);bad['destination']['filesystem_identity']='synthetic-metadata-change'
    expect(c.Refused,lambda:fx.publish(evidence_store,bad),'SECOND_OUTCOME_ACCEPTED')
    require(len(backend.objects)==1,'OUTCOME_COUNT_INFLATED')
    unverified(first);unverified(second);passed.append('one_immutable_outcome_per_attempt')

    # A negative read does not prove a timed-out request cannot commit later.
    pending=fake.FakeBackend();delayed=('inflight-probe',b'late-committed-bytes')
    expect(FileNotFoundError,lambda:pending.read(delayed[0],64),'NEGATIVE_READ_EXPECTED')
    pending.put_if_absent(*delayed)
    require(pending.put_if_absent(*delayed) is False and pending.read(delayed[0],64)==delayed[1],
            'INFLIGHT_WRITE_RETRY_UNSAFE')
    passed.append('negative_read_does_not_resolve_inflight_write')

    return dict(status='OFFLINE_ACCEPTANCE_PASS',verification_status='NOT_VERIFIED',
                usage='SYNTHETIC_TEST',checks=passed,check_count=len(passed),
                provider_kind='IN_MEMORY_FAKE',trust_root_kind='DETERMINISTIC_FAKE',
                durable_storage_verified=False,separate_cloud_runtime_verified=False,
                real_external_storage_used=False,external_upload_performed=False,
                new_real_prospective_records=0)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fault',choices=FAULTS)
    args=parser.parse_args()
    sys.addaudithook(offline_guard)
    # -I excludes cwd/PYTHONPATH; only this repository's fixed test sources enter.
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    try:
        result=exercise(args.fault);code=0
    except Exception as exc:
        result=dict(status='OFFLINE_ACCEPTANCE_FAIL',verification_status='NOT_VERIFIED',
                    error_type=type(exc).__name__,durable_storage_verified=False,
                    separate_cloud_runtime_verified=False,external_upload_performed=False,
                    new_real_prospective_records=0)
        code=1
    print(json.dumps(result,sort_keys=True));return code


if __name__=='__main__':raise SystemExit(main())

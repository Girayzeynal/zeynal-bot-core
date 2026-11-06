"""Deterministic FAKE authority/provider faults; no remote crypto/storage proof."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import threading
import unittest
from unittest.mock import patch

import faz39_checkpoint_contract as c

NOW = 1793944800


class FakeAttestor:
    """Deliberately NOT a signature implementation; usable only in test scope."""
    scope='SYNTHETIC_TEST'
    issuer_id='synthetic-independent-authority'

    def verify(self,purpose,payload,attestation):
        return attestation == self.attestation(purpose,payload)

    @staticmethod
    def attestation(purpose,payload):
        return dict(scheme='INDEPENDENT_ATTESTATION',issuer_id=FakeAttestor.issuer_id,
                    key_id='synthetic-no-private-key',
                    proof=hashlib.sha256(purpose.encode()+b'\0'+payload).hexdigest())


def envelope(payload,purpose='FAZ39_TRUSTED_PIN'):
    return c.canonical(dict(payload=payload,attestation=FakeAttestor.attestation(purpose,c.canonical(payload))))


class FakeAuthority:
    """A thread lock is a FAKE CAS contract oracle, not a distributed lock."""
    def __init__(self,current):
        self.value=current;self.lock=threading.Lock();self.writes=0;self.calls=[]

    def current(self,target,ledger,limit):
        with self.lock:
            self.calls.append('current');return self.value

    def compare_and_swap(self,target,ledger,expected,candidate):
        with self.lock:
            self.calls.append('cas')
            if c.digest(c.document(self.value)['payload'])!=expected:return False
            old=c.document(self.value)['payload'];new=c.document(candidate)['payload']
            if new['generation']!=old['generation']+1 or new['previous_pin_sha256']!=expected:return False
            self.value=candidate;self.writes+=1;return True


class FakeBackend:
    scope='EXTERNAL';target_id='synthetic-offline-store'
    def __init__(self):self.objects={};self.calls=[];self.lock=threading.Lock()
    def read(self,key,maximum_bytes):
        with self.lock:
            self.calls.append(('read',key))
            if key not in self.objects:raise FileNotFoundError(key)
            return self.objects[key]
    def put_if_absent(self,key,value):
        with self.lock:
            self.calls.append(('put',key))
            if key in self.objects:return False
            self.objects[key]=value;return True


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.attestor=FakeAttestor()
        self.policy=c.ExternalPolicy(True,FakeBackend.target_id,self.attestor.issuer_id,'SYNTHETIC_TEST',
                                     'SYNTHETIC_TEST',clock_challenge_sha256='e'*64)
        self.manifest=dict(schema_version=1,protocol='FAZ39_RECOVERY_TRANSFER',source_commit='a'*40,
                           ledger=dict(ledger_id='b'*32,mode='SYNTHETIC_TEST'))
        self.manifest_bytes=c.canonical(self.manifest)
        self.pin=dict(schema_version=1,generation=1,previous_pin_sha256=None,
                      manifest_sha256=hashlib.sha256(self.manifest_bytes).hexdigest(),source_commit='a'*40,
                      target_id=self.policy.target_id,ledger_id='b'*32,issued_utc=NOW-20,
                      expires_utc=NOW+200,source_runtime_id='synthetic-source-runtime',
                      storage_identity='synthetic-persistent-store')
        self.raw=envelope(self.pin)
        self.anchor=c.TrustAnchor(self.policy.target_id,'b'*32,1,c.digest(self.pin))
        self.clock=dict(schema_version=1,observed_utc=NOW,lower_utc=NOW,upper_utc=NOW,
                        valid_until_utc=NOW+2,evidence_sha256='c'*64,challenge_sha256='e'*64)
        self.ticket=envelope(self.clock,'FAZ39_UTC')
        self.kw=dict(policy=self.policy,attestor=self.attestor,ticket=self.ticket,now=NOW)
        self.contract=dict(schema_version=1,target_id=self.policy.target_id,
                           capabilities={k:True for k in c.REQUIRED_CAPABILITIES},evidence_sha256='d'*64)
        self.contract_bytes=envelope(self.contract,'FAZ39_ADAPTER_CONTRACT')

    def plan(self,raw=None,anchor=None,manifest=None,**overrides):
        return c.verify_restore_plan(self.raw if raw is None else raw,self.anchor if anchor is None else anchor,
                                    self.manifest_bytes if manifest is None else manifest,**dict(self.kw,**overrides))

    def next_pin(self,**updates):
        return dict(self.pin,generation=2,previous_pin_sha256=self.anchor.pin_sha256,**updates)

    def store(self,backend=None,contract=None,**overrides):
        return c.CheckedExternalStore(backend or FakeBackend(),contract or self.contract_bytes,
                                      **dict(policy=self.policy,attestor=self.attestor,**overrides))

    def test_defaults_disabled_before_any_provider_or_authority_io(self):
        backend=FakeBackend();authority=FakeAuthority(self.raw)
        with self.assertRaisesRegex(c.Refused,'DISABLED'):
            c.CheckedExternalStore(backend,self.contract_bytes)
        with self.assertRaisesRegex(c.Refused,'DISABLED'):
            c.advance_pin(authority,self.anchor,envelope(self.next_pin()),ticket=self.ticket,now=NOW)
        self.assertEqual(backend.calls,[]);self.assertEqual(authority.calls,[])

    def test_verifier_is_required_and_cannot_be_selected_by_payload(self):
        with self.assertRaisesRegex(c.Refused,'ATTESTOR_REQUIRED'):self.plan(attestor=None)
        for usage in ['RESEARCH_EXTERNAL','PRODUCTION','DISABLED']:
            with self.subTest(usage=usage),self.assertRaises(c.Refused):
                self.plan(policy=replace(self.policy,usage=usage))
        with self.assertRaises(c.Refused):self.plan(policy=replace(self.policy,issuer_id='other'))
        with self.assertRaisesRegex(c.Refused,'SCOPE_OR_ISSUER'):
            self.plan(policy=replace(self.policy,attestation_scope='INDEPENDENT'))

    def test_prospective_or_real_ledgers_are_refused_even_with_a_valid_test_attestation(self):
        manifest=dict(self.manifest,ledger=dict(self.manifest['ledger'],mode='PROSPECTIVE'))
        raw=c.canonical(manifest)
        pin=dict(self.pin,manifest_sha256=hashlib.sha256(raw).hexdigest())
        anchor=replace(self.anchor,pin_sha256=c.digest(pin))
        with self.assertRaisesRegex(c.Refused,'USAGE_ISOLATION'):
            self.plan(envelope(pin),anchor,raw)

    def test_unsigned_missing_or_forged_attestation_fails(self):
        for raw in [c.canonical(self.pin),c.canonical(dict(payload=self.pin)),
                    c.canonical(dict(payload=self.pin,attestation=None))]:
            with self.subTest(raw=raw[:30]),self.assertRaises(c.Refused):self.plan(raw)
        e=c.document(self.raw);e['attestation']['proof']='fabricated'
        with self.assertRaisesRegex(c.Refused,'NOT_VERIFIED'):self.plan(c.canonical(e))
        e=c.document(self.raw);e['attestation']['scheme']='UNSIGNED_LOCAL'
        with self.assertRaisesRegex(c.Refused,'PROVENANCE'):self.plan(c.canonical(e))

    def test_attestation_purpose_prevents_cross_protocol_replay(self):
        with self.assertRaisesRegex(c.Refused,'NOT_VERIFIED'):
            self.plan(envelope(self.pin,'FAZ39_RUNTIME_EVIDENCE'))

    def test_valid_synthetic_pin_never_claims_remote_attestation_or_restore(self):
        p=self.plan()
        self.assertEqual(p['status'],'RESTORE_PLAN_VALIDATED_NOT_EXECUTED')
        self.assertEqual(p['pin_provenance'],'SYNTHETIC_TEST')
        self.assertFalse(p['durable_storage_verified']);self.assertFalse(p['separate_cloud_runtime_verified'])

    def test_missing_duplicate_nonfinite_oversize_and_wrong_pin_fields(self):
        for raw in [b'',b'{}',b'{"x":1,"x":2}',b'{"x":NaN}',b'{"x":Infinity}',b'['*80,
                    b'x'*(c.MAX_DOCUMENT+1),b'\xff']:
            with self.subTest(raw=raw[:15]),self.assertRaises(c.Refused):self.plan(raw)
        for field,value in [('generation',True),('generation',0),('source_commit','a'*39),
                            ('manifest_sha256','x'*64),('ledger_id','b'*31),
                            ('issued_utc',False),('previous_pin_sha256','0'*64)]:
            with self.subTest(field=field),self.assertRaises(c.Refused):
                self.plan(envelope(dict(self.pin,**{field:value})))

    def test_source_commit_ledger_target_and_manifest_substitution_are_refused(self):
        for field,value in [('source_commit','f'*40),('ledger',dict(ledger_id='f'*32,mode='SYNTHETIC_TEST'))]:
            changed=dict(self.manifest,**{field:value});raw=c.canonical(changed)
            pin=dict(self.pin,manifest_sha256=hashlib.sha256(raw).hexdigest())
            anchor=replace(self.anchor,pin_sha256=c.digest(pin))
            with self.subTest(field=field),self.assertRaisesRegex(c.Refused,'IDENTITY'):
                self.plan(envelope(pin),anchor,raw)
        with self.assertRaisesRegex(c.Refused,'DIGEST'):
            self.plan(manifest=self.manifest_bytes+b' ')
        with self.assertRaisesRegex(c.Refused,'TARGET'):
            self.plan(envelope(dict(self.pin,target_id='unapproved-target')))

    def test_valid_old_pin_and_same_generation_fork_cannot_override_high_water(self):
        newer=self.next_pin();high=replace(self.anchor,generation=2,pin_sha256=c.digest(newer))
        with self.assertRaisesRegex(c.Refused,'STALE_OR_FORKED'):self.plan(anchor=high)
        fork=dict(self.pin,source_runtime_id='forked-source')
        with self.assertRaisesRegex(c.Refused,'STALE_OR_FORKED'):self.plan(envelope(fork))
        with self.assertRaisesRegex(c.Refused,'HIGH_WATER'):self.plan(anchor={})

    def test_future_expired_pin_and_exact_time_boundary(self):
        for changes in [dict(issued_utc=NOW+1),dict(expires_utc=NOW-1)]:
            p=dict(self.pin,**changes);a=replace(self.anchor,pin_sha256=c.digest(p))
            with self.subTest(changes=changes),self.assertRaisesRegex(c.Refused,'EXPIRED_OR_FUTURE'):
                self.plan(envelope(p),a)
        p=dict(self.pin,expires_utc=NOW);a=replace(self.anchor,pin_sha256=c.digest(p))
        self.assertEqual(self.plan(envelope(p),a)['generation'],1)
        with self.assertRaisesRegex(c.Refused,'EXPIRED_OR_FUTURE'):
            self.plan(envelope(p),a,now=NOW+1)

    def test_utc_requires_attestation_and_rejects_skew_uncertainty_or_staleness(self):
        for now in [NOW-3,NOW+3,float('nan'),float('inf'),True]:
            with self.subTest(now=now),self.assertRaises(c.Refused):self.plan(now=now)
        for changes in [dict(upper_utc=NOW+3),dict(valid_until_utc=NOW+11),dict(observed_utc=NOW-1)]:
            ticket=envelope(dict(self.clock,**changes),'FAZ39_UTC')
            with self.subTest(changes=changes),self.assertRaises(c.Refused):self.plan(ticket=ticket)
        with self.assertRaises(c.Refused):self.plan(ticket=envelope(self.clock))

    def test_old_signed_utc_ticket_cannot_authorize_another_request_challenge(self):
        with self.assertRaisesRegex(c.Refused,'CHALLENGE_REPLAY'):
            self.plan(policy=replace(self.policy,clock_challenge_sha256='f'*64))

    def test_independent_scope_requires_callable_clock_and_monotonic_lease(self):
        # Only exercise the scope/lease checks. This FAKE is NOT remote crypto.
        self.attestor.scope='INDEPENDENT'
        policy=replace(self.policy,attestation_scope='INDEPENDENT')
        with self.assertRaisesRegex(c.Refused,'LIVE_CLOCK_SOURCE'):
            self.plan(policy=policy)
        with self.assertRaisesRegex(c.Refused,'MONOTONIC_CLOCK_LEASE'):
            self.plan(policy=policy,now=lambda:NOW)
        with patch.object(c.time,'monotonic',return_value=100):
            for limit in [99,100,111,float('nan')]:
                with self.subTest(limit=limit),self.assertRaisesRegex(c.Refused,'MONOTONIC_CLOCK_LEASE'):
                    self.plan(policy=replace(policy,clock_deadline_monotonic=limit),now=lambda:NOW)
            result=self.plan(policy=replace(policy,clock_deadline_monotonic=105),now=lambda:NOW)
            self.assertFalse(result['separate_cloud_runtime_verified'])

    def test_wall_clock_rollback_cannot_rearm_expired_monotonic_utc_lease(self):
        self.attestor.scope='INDEPENDENT'
        policy=replace(self.policy,attestation_scope='INDEPENDENT',clock_deadline_monotonic=105)
        with patch.object(c.time,'monotonic',side_effect=[100,106]):
            with self.assertRaisesRegex(c.Refused,'MONOTONIC_CLOCK_LEASE'):
                self.plan(policy=policy,now=lambda:NOW)

    def test_contract_requires_all_capabilities_and_attested_evidence(self):
        for capability in c.REQUIRED_CAPABILITIES:
            p=deepcopy(self.contract);p['capabilities'][capability]=False
            backend=FakeBackend()
            with self.subTest(capability=capability),self.assertRaisesRegex(c.Refused,'UNSUPPORTED'):
                self.store(backend,envelope(p,'FAZ39_ADAPTER_CONTRACT'))
            self.assertEqual(backend.calls,[])
        with self.assertRaisesRegex(c.Refused,'NOT_VERIFIED'):
            self.store(contract=envelope(self.contract))

    def test_contract_target_and_backend_identity_cannot_silently_fallback(self):
        backend=FakeBackend();backend.scope='LOCAL_STAGING'
        with self.assertRaisesRegex(c.Refused,'IDENTITY'):self.store(backend)
        backend.scope='EXTERNAL';backend.target_id='other'
        with self.assertRaisesRegex(c.Refused,'IDENTITY'):self.store(backend)
        self.assertEqual(backend.calls,[])

    def test_adapter_conditional_create_idempotency_conflict_and_bounded_read(self):
        backend=FakeBackend();store=self.store(backend)
        self.assertTrue(store.put_if_absent('probe',b'original'))
        self.assertFalse(store.put_if_absent('probe',b'original'))
        with self.assertRaisesRegex(c.Refused,'CONFLICT'):store.put_if_absent('probe',b'changed!')
        with self.assertRaisesRegex(c.Refused,'LIMIT'):store.read('probe',1)
        self.assertEqual(backend.objects['probe'],b'original')
        with self.assertRaisesRegex(c.Refused,'BOUNDED'):store.read('probe',True)

    def test_adapter_lost_write_ack_partial_upload_and_power_loss_are_uncertain(self):
        backend=FakeBackend();store=self.store(backend);original=backend.put_if_absent
        def lost_ack(key,value):original(key,value);raise ConnectionError('synthetic lost ACK')
        backend.put_if_absent=lost_ack
        with self.assertRaises(ConnectionError):store.put_if_absent('probe',b'payload')
        backend.put_if_absent=original
        self.assertFalse(store.put_if_absent('probe',b'payload'))
        backend.read=lambda *_:b'partial'
        with self.assertRaisesRegex(c.Refused,'CONFLICT'):store.put_if_absent('probe',b'payload')
        backend.read=lambda *_:(_ for _ in ()).throw(TimeoutError('synthetic partition'))
        with self.assertRaises(TimeoutError):store.put_if_absent('probe',b'payload')

    def test_adapter_invalid_response_and_eventual_visibility_do_not_succeed(self):
        backend=FakeBackend();store=self.store(backend)
        backend.put_if_absent=lambda *_:1
        with self.assertRaisesRegex(c.Refused,'RESPONSE'):store.put_if_absent('x',b'bytes')
        backend.put_if_absent=lambda *_:True
        backend.read=lambda *_:(_ for _ in ()).throw(FileNotFoundError('not visible yet'))
        with self.assertRaises(FileNotFoundError):store.put_if_absent('x',b'bytes')

    def test_acknowledged_but_volatile_provider_loses_data_and_is_refused(self):
        backend=FakeBackend();store=self.store(backend);original=backend.put_if_absent
        def simulated_power_loss(key,value):
            original(key,value);backend.objects.clear();return True
        backend.put_if_absent=simulated_power_loss
        with self.assertRaises(FileNotFoundError):store.put_if_absent('probe',b'payload')

    def test_invalid_pin_cas_response_never_reports_advance(self):
        authority=FakeAuthority(self.raw);authority.compare_and_swap=lambda *_:1
        with self.assertRaisesRegex(c.Refused,'CAS_RESPONSE'):
            c.advance_pin(authority,self.anchor,envelope(self.next_pin()),**self.kw)

    def test_cas_rejection_is_a_conflict_without_force_overwrite(self):
        authority=FakeAuthority(self.raw);authority.compare_and_swap=lambda *_:False
        with self.assertRaisesRegex(c.Refused,'CAS_CONFLICT'):
            c.advance_pin(authority,self.anchor,envelope(self.next_pin()),**self.kw)
        self.assertEqual(authority.value,self.raw)

    def test_pin_generation_chain_and_boolean_anchor_are_rejected_before_authority_io(self):
        authority=FakeAuthority(self.raw)
        for p in [dict(self.next_pin(),generation=3),dict(self.next_pin(),previous_pin_sha256='0'*64)]:
            with self.subTest(p=p['generation']),self.assertRaisesRegex(c.Refused,'CHAIN'):
                c.advance_pin(authority,self.anchor,envelope(p),**self.kw)
        with self.assertRaisesRegex(c.Refused,'HIGH_WATER'):
            c.advance_pin(authority,replace(self.anchor,generation=True),envelope(self.next_pin()),**self.kw)
        self.assertEqual(authority.calls,[])

    def test_pin_cas_success_and_idempotent_retry(self):
        authority=FakeAuthority(self.raw);p=envelope(self.next_pin())
        self.assertEqual(c.advance_pin(authority,self.anchor,p,**self.kw)['status'],'PIN_HEAD_ADVANCED')
        self.assertEqual(c.advance_pin(authority,self.anchor,p,**self.kw)['status'],'PIN_ALREADY_CURRENT')
        self.assertEqual(authority.writes,1)

    def test_concurrent_forked_writers_only_one_cas_wins(self):
        authority=FakeAuthority(self.raw)
        candidates=[envelope(self.next_pin(storage_identity='synthetic-store-'+str(i))) for i in range(2)]
        def run(raw):
            try:return c.advance_pin(authority,self.anchor,raw,**self.kw)['status']
            except c.Refused:return 'REFUSED'
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,candidates))
        self.assertEqual(results.count('PIN_HEAD_ADVANCED'),1)
        self.assertEqual(results.count('REFUSED'),1);self.assertEqual(authority.writes,1)

    def test_pin_lost_ack_retry_and_stale_read_back_fail_closed(self):
        authority=FakeAuthority(self.raw);p=envelope(self.next_pin());original=authority.compare_and_swap
        def lost_ack(*args):original(*args);raise ConnectionError('synthetic post-CAS disconnect')
        authority.compare_and_swap=lost_ack
        with self.assertRaises(ConnectionError):c.advance_pin(authority,self.anchor,p,**self.kw)
        authority.compare_and_swap=original
        self.assertEqual(c.advance_pin(authority,self.anchor,p,**self.kw)['status'],'PIN_ALREADY_CURRENT')
        authority=FakeAuthority(self.raw);authority.compare_and_swap=lambda *_:True
        with self.assertRaisesRegex(c.Refused,'STALE_OR_FORKED'):
            c.advance_pin(authority,self.anchor,p,**self.kw)

    def test_partition_or_clock_expiry_before_cas_publishes_nothing(self):
        authority=FakeAuthority(self.raw);authority.current=lambda *_:(_ for _ in ()).throw(TimeoutError())
        with self.assertRaises(TimeoutError):c.advance_pin(authority,self.anchor,envelope(self.next_pin()),**self.kw)
        self.assertEqual(authority.writes,0)
        authority=FakeAuthority(self.raw);clock=[NOW];original=authority.current
        def delayed(*args):value=original(*args);clock[0]+=3;return value
        authority.current=delayed
        with self.assertRaisesRegex(c.Refused,'STALE_UTC'):
            c.advance_pin(authority,self.anchor,envelope(self.next_pin()),**dict(self.kw,now=lambda:clock[0]))
        self.assertEqual(authority.writes,0)

    def test_clock_expiry_after_cas_is_uncertain_and_cannot_report_success(self):
        authority=FakeAuthority(self.raw);clock=[NOW];original=authority.compare_and_swap
        def delayed(*args):value=original(*args);clock[0]+=3;return value
        authority.compare_and_swap=delayed
        with self.assertRaisesRegex(c.Refused,'STALE_UTC'):
            c.advance_pin(authority,self.anchor,envelope(self.next_pin()),**dict(self.kw,now=lambda:clock[0]))
        self.assertEqual(authority.writes,1)

    def evidence(self):
        observation=dict(sqlite_sha256='1'*64,audit_sha256='2'*64,integrity='ok',ledger_id=self.pin['ledger_id'])
        p=dict(schema_version=1,usage='SYNTHETIC_TEST',
               source=dict(runtime_id=self.pin['source_runtime_id'],run_id='synthetic-source-run',filesystem_identity='synthetic-global-fs-a',storage_identity='synthetic-source-disk'),
               destination=dict(runtime_id='synthetic-destination-runtime',run_id='synthetic-destination-run',filesystem_identity='synthetic-global-fs-b',storage_identity='synthetic-destination-disk'),
               storage=dict(target_id=self.policy.target_id,identity=self.pin['storage_identity'],durability='PERSISTENT'),
               manifest_sha256=self.pin['manifest_sha256'],pin_sha256=self.anchor.pin_sha256,
               generation=1,source_commit=self.pin['source_commit'],ledger_id=self.pin['ledger_id'],restore=deepcopy(observation),
               source_isolation=dict(source_accessible=False,production_accessible=False,evidence_sha256='3'*64),
               started_utc=NOW-10,completed_utc=NOW-1,utc_evidence_sha256=self.clock['evidence_sha256'],outcome='RESTORE_COMPLETE')
        return p,observation

    def validate_evidence(self,p,observation=None):
        return c.validate_runtime_evidence(envelope(p,'FAZ39_RUNTIME_EVIDENCE'),self.raw,self.anchor,
                                          self.manifest_bytes,self.evidence()[1] if observation is None else observation,**self.kw)

    def test_evidence_schema_never_promotes_synthetic_claims_to_cross_runtime(self):
        p,observation=self.evidence();before=deepcopy(p)
        result=self.validate_evidence(p,observation)
        self.assertEqual(result['cross_runtime_status'],'NOT_VERIFIED')
        self.assertFalse(result['durable_storage_verified']);self.assertFalse(result['separate_cloud_runtime_verified'])
        self.assertEqual(p,before)

    def test_same_runtime_run_or_filesystem_is_not_independent(self):
        for field in ['runtime_id','run_id','filesystem_identity','storage_identity']:
            p,_=self.evidence();p['destination'][field]=p['source'][field]
            with self.subTest(field=field),self.assertRaisesRegex(c.Refused,'SAME_RUNTIME'):
                self.validate_evidence(p)

    def test_ephemeral_storage_source_access_and_production_access_are_refused(self):
        for change in ['ephemeral','source_accessible','production_accessible']:
            p,_=self.evidence()
            if change=='ephemeral':p['storage']['durability']='EPHEMERAL'
            else:p['source_isolation'][change]=True
            with self.subTest(change=change),self.assertRaises(c.Refused):self.validate_evidence(p)

    def test_restore_checksum_audit_hash_integrity_and_ledger_are_bound(self):
        for field,value in [('sqlite_sha256','4'*64),('audit_sha256','5'*64),('integrity','corrupt'),('ledger_id','6'*32)]:
            p,_=self.evidence();p['restore'][field]=value
            with self.subTest(field=field),self.assertRaisesRegex(c.Refused,'OBSERVATION'):
                self.validate_evidence(p)

    def test_replayed_evidence_wrong_generation_utc_or_incomplete_outcome_is_refused(self):
        for field,value in [('generation',2),('generation',True),('manifest_sha256','0'*64),('pin_sha256','0'*64),
                            ('utc_evidence_sha256','0'*64),('outcome','RESTORE_STARTED'),('completed_utc',NOW+1)]:
            p,_=self.evidence();p[field]=value
            with self.subTest(field=field),self.assertRaises(c.Refused):self.validate_evidence(p)

    def test_claimed_success_flags_and_unsigned_evidence_are_not_accepted(self):
        p,_=self.evidence();p['separate_cloud_runtime_verified']=True
        with self.assertRaisesRegex(c.Refused,'FIELDS'):self.validate_evidence(p)
        p,_=self.evidence()
        with self.assertRaisesRegex(c.Refused,'ENVELOPE'):
            c.validate_runtime_evidence(c.canonical(p),self.raw,self.anchor,self.manifest_bytes,self.evidence()[1],**self.kw)

    def publish(self,store,p,**overrides):
        return c.publish_runtime_evidence(store,envelope(p,'FAZ39_RUNTIME_EVIDENCE'),self.raw,self.anchor,
                                          self.manifest_bytes,self.evidence()[1],**dict(self.kw,**overrides))

    def test_immutable_outcome_retry_is_idempotent_and_conflicting_bytes_preserve_original(self):
        backend=FakeBackend();store=self.store(backend);p,_=self.evidence()
        first=self.publish(store,p);second=self.publish(store,p)
        self.assertTrue(first['created']);self.assertFalse(second['created'])
        self.assertEqual(first['key'],second['key'])
        original=deepcopy(backend.objects)
        p['source_isolation']['evidence_sha256']='7'*64
        with self.assertRaisesRegex(c.Refused,'CONFLICT'):self.publish(store,p)
        self.assertEqual(backend.objects,original)
        self.assertEqual(first['cross_runtime_status'],'NOT_VERIFIED')

    def test_changed_destination_metadata_does_not_create_a_second_attempt_outcome(self):
        backend=FakeBackend();store=self.store(backend);p,_=self.evidence()
        self.publish(store,p);before=deepcopy(backend.objects)
        p['destination']['filesystem_identity']='synthetic-destination-fs-altered'
        with self.assertRaisesRegex(c.Refused,'CONFLICT'):self.publish(store,p)
        self.assertEqual(backend.objects,before)

    def test_concurrent_evidence_writers_cannot_replace_one_attempt_outcome(self):
        backend=FakeBackend();store=self.store(backend)
        candidates=[]
        for value in ['7'*64,'8'*64]:
            p,_=self.evidence();p['source_isolation']['evidence_sha256']=value;candidates.append(p)
        def run(p):
            try:return self.publish(store,p)['created']
            except c.Refused:return 'REFUSED'
        with ThreadPoolExecutor(max_workers=2) as pool:result=list(pool.map(run,candidates))
        self.assertEqual(result.count(True),1);self.assertEqual(result.count('REFUSED'),1)
        self.assertEqual(len(backend.objects),1)

    def test_lost_outcome_ack_is_uncertain_then_exact_retry_is_safe(self):
        backend=FakeBackend();store=self.store(backend);p,_=self.evidence();original=backend.put_if_absent
        def lost_ack(*args):original(*args);raise ConnectionError('synthetic evidence ACK lost')
        backend.put_if_absent=lost_ack
        with self.assertRaises(ConnectionError):self.publish(store,p)
        backend.put_if_absent=original
        self.assertFalse(self.publish(store,p)['created'])

    def test_bad_evidence_or_wrong_policy_never_writes_an_outcome(self):
        backend=FakeBackend();store=self.store(backend);p,_=self.evidence()
        p['source_isolation']['production_accessible']=True
        with self.assertRaises(c.Refused):self.publish(store,p)
        self.assertEqual(backend.calls,[])
        p,_=self.evidence();store.policy=replace(self.policy,issuer_id='wrong-issuer')
        with self.assertRaisesRegex(c.Refused,'POLICY_MISMATCH'):self.publish(store,p)
        self.assertEqual(backend.calls,[])

    def test_evidence_ack_crossing_clock_deadline_does_not_report_publication_success(self):
        backend=FakeBackend();store=self.store(backend);p,_=self.evidence();clock=[NOW]
        original=backend.put_if_absent
        def delayed(*args):value=original(*args);clock[0]+=3;return value
        backend.put_if_absent=delayed
        with self.assertRaisesRegex(c.Refused,'STALE_UTC'):self.publish(store,p,now=lambda:clock[0])
        self.assertEqual(len(backend.objects),1)

    def test_evidence_verification_delay_cannot_publish_with_expired_pin(self):
        self.pin['expires_utc']=NOW+1;self.raw=envelope(self.pin)
        self.anchor=replace(self.anchor,pin_sha256=c.digest(self.pin))
        p,_=self.evidence();clock=[NOW];original=self.attestor.verify
        def delayed(purpose,payload,attestation):
            result=original(purpose,payload,attestation)
            if purpose=='FAZ39_RUNTIME_EVIDENCE':clock[0]+=2
            return result
        self.attestor.verify=delayed;backend=FakeBackend();store=self.store(backend)
        with self.assertRaisesRegex(c.Refused,'EXPIRED_OR_FUTURE'):
            self.publish(store,p,now=lambda:clock[0])
        self.assertEqual(backend.calls,[])


if __name__=='__main__':unittest.main()

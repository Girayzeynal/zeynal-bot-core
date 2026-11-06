"""Disabled-by-default external recovery contracts. No SDK, credentials or network.

Injected providers/attestors are trust dependencies, never discovered from JSON,
environment or a restore payload. Synthetic verifier acceptance is not remote
attestation. No function in this module grants CROSS_RUNTIME_VERIFIED status.
"""
from dataclasses import dataclass
import hashlib
import json
import math
import re
import time
from typing import Protocol

MAX_DOCUMENT = 65536
REQUIRED_CAPABILITIES = {
    'atomic_create_if_absent', 'bounded_read', 'read_after_write',
    'immutable_objects', 'durable_ack', 'linearizable_pin_cas',
}


class Refused(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise Refused(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def document(raw):
    require(type(raw) is bytes and 0 < len(raw) <= MAX_DOCUMENT, 'DOCUMENT_SIZE_OR_TYPE')
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'DUPLICATE_DOCUMENT_KEY')
            result[key] = value
        return result
    def invalid(value):
        raise Refused('NONFINITE_DOCUMENT_NUMBER')
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise Refused('INVALID_DOCUMENT') from exc


def fields(value, expected, code):
    require(type(value) is dict and set(value) == set(expected.split()), code)


def hex_id(value, size=64):
    require(type(value) is str and re.fullmatch('[0-9a-f]{'+str(size)+'}', value) is not None,
            'INVALID_DIGEST_OR_ID')
    return value


def name(value):
    require(type(value) is str and re.fullmatch('[A-Za-z0-9_.:-]{1,128}', value) is not None,
            'INVALID_NONSECRET_IDENTITY')
    return value


@dataclass(frozen=True)
class ExternalPolicy:
    enabled: bool = False
    target_id: str | None = None
    issuer_id: str | None = None
    usage: str = 'DISABLED'
    attestation_scope: str = 'UNCONFIGURED'
    clock_challenge_sha256: str | None = None
    clock_deadline_monotonic: float | None = None


@dataclass(frozen=True)
class TrustAnchor:
    """Current high-water mark from an independently trusted control plane.

    Never obtain this from the checkpoint, object listing or supplied pin itself.
    An old but genuine signature cannot override this generation/digest pair.
    """
    target_id: str
    ledger_id: str
    generation: int
    pin_sha256: str


class Attestor(Protocol):
    scope: str  # SYNTHETIC_TEST or INDEPENDENT; NOT asserted by payload data
    issuer_id: str

    def verify(self, purpose: str, payload: bytes, attestation: dict) -> bool: ...


class ExternalCheckpointStore(Protocol):
    """No list/latest operation; implementations must prove these semantics.

    True/False is an immutable conditional create, never an upsert. Read limits
    must be enforced while streaming, not after buffering an unbounded response.
    Timeout/lost ACK may occur after publication and must propagate as uncertain.
    """
    scope: str  # EXTERNAL
    target_id: str
    def read(self, key: str, maximum_bytes: int) -> bytes: ...
    def put_if_absent(self, key: str, value: bytes) -> bool: ...


class IndependentPinAuthority(Protocol):
    """Separate trust namespace; CAS must be linearizable across machines.

    Provider-side enforcement must reject generation jumps/rollback/forks.
    Lost ACKs require exact read-back; never force-replace or trust stale listing.
    """
    def current(self, target_id: str, ledger_id: str, maximum_bytes: int) -> bytes: ...
    def compare_and_swap(self, target_id: str, ledger_id: str,
                         expected_pin_sha256: str, next_pin: bytes) -> bool: ...


def enabled(policy, attestor):
    require(type(policy) is ExternalPolicy and policy.enabled is True,
            'EXTERNAL_CONTRACT_DISABLED')
    name(policy.target_id); name(policy.issuer_id)
    # This readiness gate cannot authorize transport of existing/live ledgers.
    require(policy.usage == 'SYNTHETIC_TEST', 'SYNTHETIC_DATA_ONLY')
    require(attestor is not None and callable(getattr(attestor, 'verify', None)),
            'INDEPENDENT_ATTESTOR_REQUIRED')
    require(policy.attestation_scope in ('SYNTHETIC_TEST','INDEPENDENT'), 'ATTESTOR_SCOPE_REQUIRED')
    require(getattr(attestor, 'scope', None) == policy.attestation_scope and
            getattr(attestor, 'issuer_id', None) == policy.issuer_id, 'ATTESTOR_SCOPE_OR_ISSUER')


def attested(raw, purpose, policy, attestor):
    enabled(policy, attestor)
    envelope = document(raw)
    fields(envelope, 'payload attestation', 'ATTESTED_ENVELOPE_REQUIRED')
    a = envelope['attestation']
    fields(a, 'scheme issuer_id key_id proof', 'DETACHED_ATTESTATION_REQUIRED')
    require(a['scheme'] in ('DETACHED_SIGNATURE', 'INDEPENDENT_ATTESTATION') and
            a['issuer_id'] == policy.issuer_id, 'ATTESTATION_PROVENANCE_REQUIRED')
    name(a['key_id'])
    require(type(a['proof']) is str and 0 < len(a['proof']) <= 8192, 'ATTESTATION_PROOF_REQUIRED')
    require(attestor.verify(purpose, canonical(envelope['payload']), a) is True,
            'ATTESTATION_NOT_VERIFIED')
    return envelope['payload']


def utc_interval(ticket, now, policy, attestor):
    require(policy.attestation_scope != 'INDEPENDENT' or callable(now), 'LIVE_CLOCK_SOURCE_REQUIRED')
    def deadline():
        if policy.attestation_scope == 'INDEPENDENT':
            limit=policy.clock_deadline_monotonic
            require(type(limit) in (int,float) and math.isfinite(limit) and
                    0 < limit-time.monotonic() <= 10, 'MONOTONIC_CLOCK_LEASE_EXPIRED_OR_MISSING')
    deadline()
    p = attested(ticket, 'FAZ39_UTC', policy, attestor)
    deadline()
    fields(p, 'schema_version observed_utc lower_utc upper_utc valid_until_utc evidence_sha256 challenge_sha256', 'UTC_FIELDS')
    hex_id(policy.clock_challenge_sha256)
    require(p['challenge_sha256']==policy.clock_challenge_sha256,'UTC_CHALLENGE_REPLAY')
    require(type(p['schema_version']) is int and p['schema_version'] == 1, 'UTC_SCHEMA')
    require(all(type(p[k]) is int and p[k] > 0 for k in
                ('observed_utc','lower_utc','upper_utc','valid_until_utc')), 'UTC_TIMESTAMPS')
    now = now() if callable(now) else now
    require(type(now) in (int,float) and math.isfinite(now), 'INVALID_WALL_CLOCK')
    lo, hi = p['lower_utc'], p['upper_utc']
    require(lo <= p['observed_utc'] <= hi and 0 <= hi-lo <= 2 and
            hi <= p['valid_until_utc'] <= hi+10, 'UTC_UNCERTAINTY')
    require(lo-2 <= now <= min(p['valid_until_utc'], hi+2), 'CLOCK_SKEW_OR_STALE_UTC')
    hex_id(p['evidence_sha256'])
    return lo, hi


def pin_payload(raw, policy, attestor):
    p = attested(raw, 'FAZ39_TRUSTED_PIN', policy, attestor)
    fields(p, 'schema_version generation previous_pin_sha256 manifest_sha256 source_commit '
           'target_id ledger_id issued_utc expires_utc source_runtime_id storage_identity', 'PIN_FIELDS')
    require(type(p['schema_version']) is int and p['schema_version'] == 1 and
            type(p['generation']) is int and p['generation'] >= 1, 'PIN_SCHEMA_OR_GENERATION')
    require((p['generation'] == 1 and p['previous_pin_sha256'] is None) or
            (p['generation'] > 1 and p['previous_pin_sha256'] is not None), 'PIN_PREDECESSOR')
    if p['previous_pin_sha256'] is not None:hex_id(p['previous_pin_sha256'])
    hex_id(p['manifest_sha256']); hex_id(p['source_commit'],40); hex_id(p['ledger_id'],32)
    name(p['target_id']); name(p['source_runtime_id']); name(p['storage_identity'])
    require(p['target_id'] == policy.target_id, 'PIN_TARGET_MISMATCH')
    require(type(p['issued_utc']) is int and type(p['expires_utc']) is int and
            0 < p['issued_utc'] < p['expires_utc'] <= p['issued_utc']+300, 'PIN_VALIDITY')
    return p


def validate_anchor(anchor):
    require(type(anchor) is TrustAnchor and type(anchor.generation) is int and anchor.generation >= 1,
            'EXTERNAL_HIGH_WATER_MARK_REQUIRED')
    hex_id(anchor.pin_sha256); hex_id(anchor.ledger_id,32); name(anchor.target_id)


def anchor_matches(p, anchor):
    validate_anchor(anchor)
    require((p['target_id'],p['ledger_id'],p['generation'],digest(p)) ==
            (anchor.target_id,anchor.ledger_id,anchor.generation,anchor.pin_sha256),
            'STALE_OR_FORKED_PIN')


def fresh_pin(p, ticket, now, policy, attestor):
    lo, hi = utc_interval(ticket, now, policy, attestor)
    wall = now() if callable(now) else now
    require(type(wall) in (int,float) and math.isfinite(wall), 'INVALID_WALL_CLOCK')
    require(p['issued_utc'] <= min(lo,wall) and max(hi,wall) <= p['expires_utc'],
            'PIN_EXPIRED_OR_FUTURE')


def verify_restore_plan(pin, anchor, manifest, *, ticket, now, policy=ExternalPolicy(), attestor=None):
    """Pre-I/O trust gate. Existing import_bundle still validates full bundle/audit.

    The caller must obtain anchor independently, recheck after provider waits,
    and never turn this structural plan into a durability/cross-runtime claim.
    """
    p = pin_payload(pin, policy, attestor); anchor_matches(p, anchor)
    fresh_pin(p, ticket, now, policy, attestor)
    m = document(manifest)
    require(hashlib.sha256(manifest).hexdigest() == p['manifest_sha256'], 'MANIFEST_DIGEST_MISMATCH')
    require(type(m) is dict and m.get('protocol') == 'FAZ39_RECOVERY_TRANSFER' and
            type(m.get('schema_version')) is int and m['schema_version'] == 1, 'MANIFEST_SCHEMA')
    require(m.get('source_commit') == p['source_commit'] and type(m.get('ledger')) is dict and
            m['ledger'].get('ledger_id') == p['ledger_id'], 'PIN_MANIFEST_IDENTITY_MISMATCH')
    require(m['ledger'].get('mode') == 'SYNTHETIC_TEST',
            'PIN_USAGE_ISOLATION')
    fresh_pin(p,ticket,now,policy,attestor)
    return dict(status='RESTORE_PLAN_VALIDATED_NOT_EXECUTED', generation=p['generation'],
                pin_sha256=digest(p), manifest_sha256=p['manifest_sha256'],
                pin_provenance='SYNTHETIC_TEST' if policy.attestation_scope == 'SYNTHETIC_TEST' else 'VERIFIER_ACCEPTED',
                durable_storage_verified=False, separate_cloud_runtime_verified=False)


def advance_pin(authority, previous, candidate, *, ticket, now,
                policy=ExternalPolicy(), attestor=None):
    """Conditional head publication; a missing ACK/read-back is NOT success.

    Test/local authority implementations are not distributed locks. The real
    authority must persist its own high-water mark and enforce linearizable CAS.
    """
    p = pin_payload(candidate, policy, attestor)
    validate_anchor(previous)
    require((p['target_id'],p['ledger_id'],p['generation'],p['previous_pin_sha256']) ==
            (previous.target_id,previous.ledger_id,previous.generation+1,previous.pin_sha256),
            'PIN_GENERATION_OR_CHAIN_MISMATCH')
    fresh_pin(p, ticket, now, policy, attestor)
    next_anchor = TrustAnchor(p['target_id'],p['ledger_id'],p['generation'],digest(p))
    current = pin_payload(authority.current(p['target_id'],p['ledger_id'],MAX_DOCUMENT), policy, attestor)
    if digest(current) == next_anchor.pin_sha256:
        anchor_matches(current,next_anchor)
        status = 'PIN_ALREADY_CURRENT'
    else:
        anchor_matches(current,previous)
        fresh_pin(p,ticket,now,policy,attestor)
        changed = authority.compare_and_swap(p['target_id'],p['ledger_id'],previous.pin_sha256,candidate)
        require(type(changed) is bool, 'PIN_CAS_RESPONSE_INVALID')
        require(changed, 'PIN_CAS_CONFLICT')
        status = 'PIN_HEAD_ADVANCED'
    observed = pin_payload(authority.current(p['target_id'],p['ledger_id'],MAX_DOCUMENT),policy,attestor)
    anchor_matches(observed,next_anchor)
    fresh_pin(p,ticket,now,policy,attestor)
    return dict(status=status,generation=p['generation'],pin_sha256=digest(p),
                durable_storage_verified=False,separate_cloud_runtime_verified=False)


class CheckedExternalStore:
    """Optional adapter facade; disabled until policy + attested contract exist.

    No transport implementation is supplied. A declaration is only as trustworthy
    as the independently installed verifier and its provider capability evidence.
    The collector, CLI and sandbox do not instantiate this facade.
    """
    scope = 'EXTERNAL'

    def __init__(self, backend, contract, *, policy=ExternalPolicy(), attestor=None):
        p = attested(contract,'FAZ39_ADAPTER_CONTRACT',policy,attestor)
        fields(p,'schema_version target_id capabilities evidence_sha256','ADAPTER_CONTRACT_FIELDS')
        require(type(p['schema_version']) is int and p['schema_version'] == 1 and
                p['target_id'] == policy.target_id, 'ADAPTER_CONTRACT_TARGET')
        require(type(p['capabilities']) is dict and set(p['capabilities']) == REQUIRED_CAPABILITIES and
                all(v is True for v in p['capabilities'].values()), 'ADAPTER_CAPABILITIES_UNSUPPORTED')
        hex_id(p['evidence_sha256'])
        require(getattr(backend,'scope',None) == 'EXTERNAL' and
                getattr(backend,'target_id',None) == policy.target_id, 'ADAPTER_IDENTITY_MISMATCH')
        self.backend=backend; self.target_id=policy.target_id; self.policy=policy

    def read(self, key, maximum_bytes):
        require(type(maximum_bytes) is int and maximum_bytes > 0,'BOUNDED_READ_REQUIRED')
        raw = self.backend.read(key,maximum_bytes)
        require(type(raw) is bytes and len(raw) <= maximum_bytes,'ADAPTER_READ_LIMIT_VIOLATION')
        return raw

    def put_if_absent(self, key, value):
        require(type(value) is bytes,'OBJECT_BYTES_REQUIRED')
        result=self.backend.put_if_absent(key,value)
        require(type(result) is bool,'ADAPTER_CREATE_RESPONSE_INVALID')
        require(self.read(key,len(value)) == value,'ADAPTER_READ_AFTER_WRITE_CONFLICT')
        return result


def validate_runtime_evidence(raw, pin, anchor, manifest, observation, *, ticket, now,
                              policy=ExternalPolicy(), attestor=None):
    """Validate a detached immutable outcome, never self-certify its truth.

    observation must come from the destination's actual pinned restore/audit,
    not from this evidence payload. Runtime/storage isolation attestations must
    still be independently investigated; even valid synthetic evidence is false
    for durable_storage_verified/separate_cloud_runtime_verified.
    """
    plan=verify_restore_plan(pin,anchor,manifest,ticket=ticket,now=now,policy=policy,attestor=attestor)
    p=attested(raw,'FAZ39_RUNTIME_EVIDENCE',policy,attestor)
    fields(p,'schema_version usage source destination storage manifest_sha256 pin_sha256 '
           'generation source_commit ledger_id restore source_isolation started_utc completed_utc '
           'utc_evidence_sha256 outcome','RUNTIME_EVIDENCE_FIELDS')
    require(type(p['schema_version']) is int and p['schema_version']==1 and p['usage']==policy.usage,
            'RUNTIME_EVIDENCE_SCHEMA_OR_USAGE')
    trusted_pin=pin_payload(pin,policy,attestor)
    for side in ('source','destination'):
        fields(p[side],'runtime_id run_id filesystem_identity storage_identity','RUNTIME_IDENTITY_FIELDS')
        for v in p[side].values():name(v)
    require(p['source']['runtime_id']==trusted_pin['source_runtime_id'],'SOURCE_RUNTIME_MISMATCH')
    require(all(p['source'][k]!=p['destination'][k] for k in
                ('runtime_id','run_id','filesystem_identity','storage_identity')),'SAME_RUNTIME_OR_FILESYSTEM')
    fields(p['storage'],'target_id identity durability','STORAGE_EVIDENCE_FIELDS')
    require(p['storage']==dict(target_id=policy.target_id,identity=trusted_pin['storage_identity'],
                               durability='PERSISTENT'),'EPHEMERAL_OR_WRONG_STORAGE')
    require(type(p['generation']) is int and
            (p['manifest_sha256'],p['pin_sha256'],p['generation'],p['source_commit'],p['ledger_id']) ==
            (plan['manifest_sha256'],plan['pin_sha256'],plan['generation'],
             trusted_pin['source_commit'],trusted_pin['ledger_id']),'EVIDENCE_PIN_MISMATCH')
    fields(p['restore'],'sqlite_sha256 audit_sha256 integrity ledger_id','RESTORE_OBSERVATION_FIELDS')
    fields(observation,'sqlite_sha256 audit_sha256 integrity ledger_id','OBSERVED_RESTORE_REQUIRED')
    hex_id(p['restore']['sqlite_sha256']); hex_id(p['restore']['audit_sha256'])
    require(p['restore']==observation and observation['integrity']=='ok' and
            observation['ledger_id']==trusted_pin['ledger_id'],'RESTORE_OBSERVATION_MISMATCH')
    fields(p['source_isolation'],'source_accessible production_accessible evidence_sha256','ISOLATION_FIELDS')
    require(p['source_isolation']['source_accessible'] is False and
            p['source_isolation']['production_accessible'] is False,'SOURCE_OR_PRODUCTION_NOT_ISOLATED')
    hex_id(p['source_isolation']['evidence_sha256']);hex_id(p['utc_evidence_sha256'])
    utc=attested(ticket,'FAZ39_UTC',policy,attestor)
    require(p['utc_evidence_sha256']==utc['evidence_sha256'],'UTC_EVIDENCE_BINDING')
    lo,hi=utc_interval(ticket,now,policy,attestor)
    require(type(p['started_utc']) is int and type(p['completed_utc']) is int and
            trusted_pin['issued_utc'] <= p['started_utc'] <= p['completed_utc'] <= lo and
            hi <= trusted_pin['expires_utc'],'EVIDENCE_CHRONOLOGY')
    require(p['outcome']=='RESTORE_COMPLETE','RESTORE_NOT_COMPLETE')
    fresh_pin(trusted_pin,ticket,now,policy,attestor)
    return dict(status='EVIDENCE_SCHEMA_VALID_NOT_INDEPENDENTLY_VERIFIED',evidence_sha256=digest(p),
                envelope_sha256=hashlib.sha256(raw).hexdigest(),usage=policy.usage,
                immutable_outcome=p['outcome'],durable_storage_verified=False,
                separate_cloud_runtime_verified=False,cross_runtime_status='NOT_VERIFIED')


def publish_runtime_evidence(store, raw, pin, anchor, manifest, observation, *, ticket, now,
                             policy=ExternalPolicy(), attestor=None):
    """One immutable outcome per destination run/pin, outside the restore payload.

    A different outcome for the same attempt conflicts instead of creating a
    second apparent success. CAS/write ACK failures are allowed to propagate;
    exact-byte retry is safe but never an independent durability attestation.
    """
    result=validate_runtime_evidence(raw,pin,anchor,manifest,observation,
                                    ticket=ticket,now=now,policy=policy,attestor=attestor)
    require(type(store) is CheckedExternalStore and store.policy==policy,'EVIDENCE_STORE_POLICY_MISMATCH')
    p=document(raw)['payload']
    # Filesystem/storage claims are immutable outcome metadata, not a way to
    # invent another attempt for the same actual destination runtime/run.
    attempt=dict(destination_runtime_id=p['destination']['runtime_id'],
                 destination_run_id=p['destination']['run_id'],
                 pin_sha256=p['pin_sha256'],generation=p['generation'])
    key='evidence/'+digest(attempt)+'.json'
    created=store.put_if_absent(key,raw)
    # Re-evaluate UTC after provider waits; a late ACK cannot certify completion.
    fresh_pin(pin_payload(pin,policy,attestor),ticket,now,policy,attestor)
    return dict(result,status='EVIDENCE_PUBLISHED_NOT_INDEPENDENTLY_VERIFIED',
                created=created,key=key,provider_io_requested=True)

"""Field-bound public archive witnesses, distinct from local retrieval timestamps.

Only native archive decoders create these runtime objects. A JSON field claiming an
old publication time cannot by itself change availability. No score model lives here.
"""
from dataclasses import dataclass

from core.team_identity import digest


def fields(record, scope):
    identity = {k: record[k] for k in ('league', 'season', 'fixture_id', 'fixture_start_utc', 'home_team_id', 'away_team_id')}
    clocks = record['source'] if scope == 'BOX' else record
    identity['local_clocks'] = {k:clocks[k] for k in ('observed_at_utc','ingested_at_utc')}
    if scope == 'CORE': identity.update(final_scores=record['final_scores'], periods=record['periods'])
    elif scope == 'BOX': identity.update(teams=record['teams'], regulation_eligible=record['regulation_eligible'])
    elif scope != 'FIXTURE': raise ValueError('UNKNOWN_ARCHIVED_FIELD_SCOPE')
    return identity


@dataclass(frozen=True)
class Witness:
    scope: str
    available_at_utc: int
    fields_sha256: str
    source_sha256: str
    evidence_id: str
    authority: str


class ArchivedRecord(dict):
    """JSON serialization preserves audit fields, never the trusted runtime capability."""
    pass


def certify(record, *, scope, at, source_sha256, evidence_id, authority):
    if type(at) is not int or at <= 0: raise ValueError('VALID_ARCHIVE_WITNESS_CLOCK_REQUIRED')
    if scope != 'FIXTURE' and at <= record['fixture_start_utc']:
        raise ValueError('FINAL_CONTENT_WITNESSED_BEFORE_FIXTURE')
    out = ArchivedRecord(record)
    proof = Witness(scope, at, digest(fields(out, scope)), source_sha256, evidence_id, authority)
    out._witness = proof
    out['archive_evidence'] = dict(scope=scope, available_at_utc=at, source_sha256=source_sha256,
        fields_sha256=proof.fields_sha256, evidence_id=evidence_id, authority=authority)
    return out


def witnessed_time(record, scope):
    proof = getattr(record, '_witness', None)
    if not isinstance(proof, Witness) or proof.scope != scope: return None
    if digest(fields(record, scope)) != proof.fields_sha256: raise ValueError('ARCHIVED_FIELDS_CHANGED_AFTER_VERIFICATION')
    return proof.available_at_utc


def effective_time(record, scope):
    local = max(record['observed_at_utc'], record['ingested_at_utc'])
    archive = witnessed_time(record, scope)
    return local if archive is None else min(local, archive)


def effective_box_time(box):
    archive = witnessed_time(box, 'BOX')
    local = max(box['source']['observed_at_utc'], box['source']['ingested_at_utc'])
    return local if archive is None else min(local, archive)

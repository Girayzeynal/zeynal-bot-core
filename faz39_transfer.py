"""Provider-neutral checkpoint protocol; CLI/defaults perform LOCAL staging only.

No network provider, credential discovery, automatic upload or scheduler is
installed. An external adapter requires a separately authorized explicit policy.
"""
import argparse
from contextlib import contextmanager
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import tarfile
import tempfile
from typing import Protocol
import uuid

from faz39 import Refused, require
from faz39_recovery import restore
from faz35 import validate_config
from prediction_inputs import canonical_json, digest

MAX_BUNDLE = 32 * 1024 * 1024
MAX_SQLITE = 128 * 1024 * 1024
MAX_MANIFEST = 65536
LOCAL_ONLY = dict(mode='LOCAL_ONLY', external_target=None, upload_enabled=False)


class ObjectStore(Protocol):
    """Adapters MUST supply bounded reads and atomic immutable create, not upsert.

    Returning False means the key exists; the protocol verifies its exact bytes.
    Eventual read-after-write failures remain incomplete and may be retried.
    """
    scope: str  # LOCAL_STAGING or EXTERNAL; not a durability attestation
    target_id: str  # opaque non-secret alias, never a credential/signed URL

    def read(self, key: str, maximum_bytes: int) -> bytes: ...
    def put_if_absent(self, key: str, value: bytes) -> bool: ...


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _pin(value):
    require(isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None,
            'TRUSTED_SHA256_REQUIRED')
    return value


def _json(raw):
    require(type(raw) is bytes and len(raw) <= MAX_MANIFEST, 'MANIFEST_SIZE_OR_TYPE')
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'DUPLICATE_MANIFEST_KEY')
            result[key] = value
        return result
    def invalid(value):
        raise Refused('NONFINITE_MANIFEST_NUMBER')
    return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=invalid)


def _policy(store, policy, *, write):
    p = dict(LOCAL_ONLY if policy is None else policy)
    require(set(p) == set(LOCAL_ONLY) and type(p['upload_enabled']) is bool, 'TRANSFER_POLICY_INVALID')
    require(getattr(store, 'scope', None) in ('LOCAL_STAGING', 'EXTERNAL'), 'STORE_SCOPE_UNSUPPORTED')
    require(isinstance(getattr(store, 'target_id', None), str) and
            re.fullmatch('[A-Za-z0-9_.:-]{1,128}', store.target_id) is not None, 'TARGET_ALIAS_INVALID')
    if store.scope == 'LOCAL_STAGING':
        require(p == LOCAL_ONLY, 'LOCAL_STAGING_POLICY_REQUIRED')
    else:
        require(p['mode'] == 'EXTERNAL' and p['external_target'] == store.target_id,
                'EXTERNAL_TARGET_NOT_AUTHORIZED')
        require(not write or p['upload_enabled'] is True, 'EXTERNAL_UPLOAD_DISABLED')
    require(callable(getattr(store, 'read', None)) and
            callable(getattr(store, 'put_if_absent', None)), 'STORE_CONTRACT_UNSUPPORTED')


def _file_bytes(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= MAX_BUNDLE, 'BUNDLE_SIZE_OR_TYPE')
        raw = stream.read(MAX_BUNDLE + 1)
        require(len(raw) == info.st_size, 'BUNDLE_CHANGED_OR_TOO_LARGE')
        return raw


class _ExpandedReader:
    """Also bound hidden tar/PAX metadata before tarfile can buffer it."""
    def __init__(self, source):
        self.source = source
        self.remaining = MAX_SQLITE + MAX_MANIFEST + 1024 * 1024

    def read(self, size=-1):
        count = self.remaining + 1 if size < 0 else min(size, self.remaining + 1)
        raw = self.source.read(count)
        self.remaining -= len(raw)
        require(self.remaining >= 0, 'EXPANDED_BUNDLE_TOO_LARGE')
        return raw


def _manifest_for(raw, bundle_sha):
    require(type(raw) is bytes and 0 < len(raw) <= MAX_BUNDLE and _sha(raw) == _pin(bundle_sha),
            'BUNDLE_SHA256_OR_LENGTH_MISMATCH')
    files, inner = {}, None
    # Bound decompression and member count BEFORE invoking the existing restorer.
    with gzip.GzipFile(fileobj=io.BytesIO(raw), mode='rb') as expanded, \
         tarfile.open(fileobj=_ExpandedReader(expanded), mode='r|') as archive:
        for member in archive:
            require(member.isfile() and member.name in ('manifest.json', 'faz39.sqlite') and
                    member.name not in files, 'UNSAFE_OR_DUPLICATE_BUNDLE_MEMBER')
            limit = MAX_MANIFEST if member.name == 'manifest.json' else MAX_SQLITE
            require(0 < member.size <= limit, 'EXPANDED_BUNDLE_TOO_LARGE')
            body = archive.extractfile(member).read(limit + 1)
            require(len(body) == member.size, 'BUNDLE_MEMBER_LENGTH_MISMATCH')
            files[member.name] = dict(sha256=_sha(body), size_bytes=len(body))
            if member.name == 'manifest.json':
                inner = _json(body)
    require(set(files) == {'manifest.json', 'faz39.sqlite'} and isinstance(inner, dict), 'BUNDLE_CONTENTS')
    require(type(inner.get('schema_version')) is int and inner['schema_version'] == 1 and
            inner.get('files') == {'faz39.sqlite': files['faz39.sqlite']['sha256']} and
            isinstance(inner.get('source_version'), str) and
            re.fullmatch('[0-9a-f]{40}', inner['source_version']) is not None and
            inner.get('external_uploaded') is False, 'INNER_MANIFEST_INVALID')
    with tempfile.TemporaryDirectory(prefix='faz39-transfer-audit-') as folder:
        root = Path(folder); bundle = root/'bundle.tar.gz'; bundle.write_bytes(raw); bundle.chmod(0o600)
        result = restore(bundle, root/'restored', bundle_sha)
        database = root/'restored/faz39.sqlite'
        with sqlite3.connect(database.as_uri()+'?mode=ro', uri=True) as db:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            identity = db.execute('SELECT ledger_id FROM faz39_identity WHERE singleton=1').fetchone() if 'faz39_identity' in tables else None
    return dict(schema_version=1, protocol='FAZ39_RECOVERY_TRANSFER',
        source_commit=inner['source_version'],
        bundle=dict(sha256=bundle_sha, size_bytes=len(raw), key='objects/'+bundle_sha+'.tar.gz'),
        files=files, ledger=dict(mode=result['audit']['mode'], ledger_id=identity[0] if identity else None,
                                audit_sha256=digest(result['audit'])))


def _get(store, key, limit):
    raw = store.read(key, limit)
    require(type(raw) is bytes and len(raw) <= limit, 'STORE_READ_SIZE_OR_TYPE')
    return raw


def _put_checked(store, key, raw, limit):
    created = store.put_if_absent(key, raw)
    require(type(created) is bool, 'STORE_CREATE_RESPONSE_INVALID')
    require(_get(store, key, limit) == raw, 'STORED_OBJECT_CONFLICT_OR_CORRUPTION')
    return created


def export_bundle(bundle, expected_bundle_sha256, store: ObjectStore, *, policy=None):
    """Immutable objects first, commit marker LAST. Same bytes give the same ID."""
    _policy(store, policy, write=True)  # no adapter IO before authorization
    raw = _file_bytes(bundle); manifest = _manifest_for(raw, expected_bundle_sha256)
    encoded = canonical_json(manifest).encode(); require(len(encoded) <= MAX_MANIFEST, 'MANIFEST_TOO_LARGE')
    sha = _sha(encoded)
    commit = canonical_json(dict(schema_version=1, manifest_sha256=sha,
                                 manifest_bytes=len(encoded))).encode()
    created = []
    for key, value, limit in ((manifest['bundle']['key'], raw, MAX_BUNDLE),
            ('manifests/'+sha+'.json', encoded, MAX_MANIFEST),
            ('commits/'+sha+'.json', commit, MAX_MANIFEST)):
        if _put_checked(store, key, value, limit):
            created.append(key)
    return dict(status='EXPORTED' if 'commits/'+sha+'.json' in created else 'ALREADY_EXPORTED', manifest_sha256=sha,
        bundle_sha256=expected_bundle_sha256, created_keys=created, adapter_scope=store.scope,
        external_transfer_requested=store.scope == 'EXTERNAL', durable_storage_verified=False,
        separate_cloud_runtime_verified=False)


def import_bundle(store: ObjectStore, destination, expected_manifest_sha256, *, policy=None):
    """A trusted external pin is required; never choose an untrusted 'latest'."""
    _policy(store, policy, write=False); sha = _pin(expected_manifest_sha256)
    if Path(destination).exists():
        raise FileExistsError(destination)
    try:
        commit = _json(_get(store, 'commits/'+sha+'.json', MAX_MANIFEST))
    except FileNotFoundError as exc:
        raise Refused('EXPORT_INCOMPLETE_OR_MISSING') from exc
    require(isinstance(commit,dict) and set(commit) == {'schema_version', 'manifest_sha256', 'manifest_bytes'} and
            type(commit['schema_version']) is int and commit['schema_version'] == 1 and
            commit['manifest_sha256'] == sha and type(commit['manifest_bytes']) is int and
            0 < commit['manifest_bytes'] <= MAX_MANIFEST, 'COMMIT_MARKER_INVALID')
    encoded = _get(store, 'manifests/'+sha+'.json', MAX_MANIFEST)
    require(len(encoded) == commit['manifest_bytes'] and _sha(encoded) == sha, 'MANIFEST_PIN_OR_LENGTH_MISMATCH')
    manifest = _json(encoded)
    require(isinstance(manifest, dict) and type(manifest.get('schema_version')) is int and
            manifest['schema_version'] == 1 and manifest.get('protocol') == 'FAZ39_RECOVERY_TRANSFER',
            'TRANSFER_MANIFEST_SCHEMA')
    require(set(manifest) == {'schema_version','protocol','source_commit','bundle','files','ledger'} and
            isinstance(manifest['source_commit'],str) and
            re.fullmatch('[0-9a-f]{40}',manifest['source_commit']) is not None, 'TRANSFER_MANIFEST_FIELDS')
    require(isinstance(manifest['files'],dict) and
            set(manifest['files']) == {'manifest.json','faz39.sqlite'}, 'TRANSFER_FILE_FIELDS')
    for name, file in manifest['files'].items():
        limit = MAX_MANIFEST if name == 'manifest.json' else MAX_SQLITE
        require(isinstance(file,dict) and set(file) == {'sha256','size_bytes'} and
                type(file['size_bytes']) is int and 0 < file['size_bytes'] <= limit,
                'TRANSFER_FILE_LENGTH')
        _pin(file['sha256'])
    ledger = manifest['ledger']
    require(isinstance(ledger,dict) and set(ledger) == {'mode','ledger_id','audit_sha256'} and
            ledger['mode'] in ('PROSPECTIVE','SYNTHETIC_TEST') and
            (ledger['ledger_id'] is None or (isinstance(ledger['ledger_id'],str) and
             re.fullmatch('[0-9a-f]{32}',ledger['ledger_id']) is not None)), 'TRANSFER_LEDGER_FIELDS')
    _pin(ledger['audit_sha256'])
    blob = manifest['bundle']
    require(isinstance(blob,dict) and set(blob) == {'key','sha256','size_bytes'}, 'BUNDLE_REFERENCE_INVALID')
    bundle_sha = _pin(blob['sha256'])
    require(blob['key'] == 'objects/'+bundle_sha+'.tar.gz' and type(blob['size_bytes']) is int and
            0 < blob['size_bytes'] <= MAX_BUNDLE, 'BUNDLE_REFERENCE_INVALID')
    raw = _get(store, blob['key'], MAX_BUNDLE)
    require(len(raw) == blob['size_bytes'], 'BUNDLE_LENGTH_MISMATCH')
    require(_manifest_for(raw, bundle_sha) == manifest, 'MANIFEST_CONTENT_MISMATCH')
    with tempfile.TemporaryDirectory(dir=Path(destination).parent) as folder:
        stable = Path(folder)/'verified.tar.gz'; stable.write_bytes(raw); stable.chmod(0o600)
        recovered = restore(stable, destination, bundle_sha)
    return dict(status='LOCAL_RECOVERY_VERIFIED', manifest_sha256=sha, recovery=recovered,
        adapter_scope=store.scope, external_transfer_requested=store.scope == 'EXTERNAL',
        durable_storage_verified=False, separate_cloud_runtime_verified=False)


class DirectoryStore:
    """Local reference adapter; no SDK, network, environment or secret access."""
    scope = 'LOCAL_STAGING'
    target_id = 'local-staging'

    def __init__(self, directory):
        self.root = Path(directory)
        require(self.root.is_absolute(), 'ABSOLUTE_STAGING_DIRECTORY_REQUIRED')
        require(not any(p.is_symlink() for p in (self.root, *self.root.parents)), 'STAGING_SYMLINK_FORBIDDEN')
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.root.stat()
        require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) & 0o077 == 0,
                'OWNER_ONLY_STAGING_DIRECTORY_REQUIRED')
        self.identity = (info.st_dev, info.st_ino)

    @contextmanager
    def _folder(self, key, create=False):
        match = re.fullmatch(r'(objects|manifests|commits)/([0-9a-f]{64})(\.tar\.gz|\.json)', key)
        require(match is not None and ((match[1]=='objects') == (match[3]=='.tar.gz')), 'UNSAFE_OBJECT_KEY')
        root = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        folder = None
        try:
            info = os.fstat(root); require((info.st_dev, info.st_ino) == self.identity, 'STAGING_ROOT_CHANGED')
            if create:
                try:os.mkdir(match[1], mode=0o700, dir_fd=root); os.fsync(root)
                except FileExistsError:pass
            folder = os.open(match[1], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
            yield folder, match[2]+match[3]
        finally:
            if folder is not None:os.close(folder)
            os.close(root)

    def read(self, key, maximum_bytes):
        with self._folder(key) as (folder, name):
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=folder)
            with os.fdopen(fd, 'rb') as stream:
                info = os.fstat(fd)
                require(stat.S_ISREG(info.st_mode) and info.st_size <= maximum_bytes, 'STORE_OBJECT_TOO_LARGE_OR_NOT_FILE')
                raw = stream.read(maximum_bytes+1)
                require(len(raw) <= maximum_bytes, 'STORE_OBJECT_TOO_LARGE_OR_NOT_FILE')
                return raw

    def put_if_absent(self, key, value):
        require(type(value) is bytes, 'OBJECT_BYTES_REQUIRED')
        with self._folder(key, create=True) as (folder, name):
            temporary = '.pending-'+uuid.uuid4().hex
            try:
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=folder)
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(value); stream.flush(); os.fsync(stream.fileno())
                try:os.link(temporary, name, src_dir_fd=folder, dst_dir_fd=folder, follow_symlinks=False)
                except FileExistsError:return False
                os.fsync(folder)
                return True
            finally:
                try:os.unlink(temporary, dir_fd=folder)
                except FileNotFoundError:pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('export'); p.add_argument('bundle'); p.add_argument('staging_directory')
    p.add_argument('--expected-bundle-sha256', required=True); p.add_argument('--config')
    p = commands.add_parser('import'); p.add_argument('staging_directory'); p.add_argument('destination')
    p.add_argument('--expected-manifest-sha256', required=True); p.add_argument('--config')
    args = parser.parse_args()
    # The existing collector configuration still refuses external activation.
    policy = validate_config(json.loads(Path(args.config).read_text()))['storage'] if args.config else None
    store = DirectoryStore(args.staging_directory)
    if args.command == 'export':
        result = export_bundle(args.bundle, args.expected_bundle_sha256, store, policy=policy)
    else:
        result = import_bundle(store, args.destination, args.expected_manifest_sha256, policy=policy)
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == '__main__':main()

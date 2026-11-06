"""One-shot offline SYNTHETIC_TEST recovery exercise; never runs a bot/collector.

Run as a dedicated process: the audit hook is deliberately irreversible. This is
an application guard, not an OS egress policy or an external durability proof.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import tomllib

APP_PREFIX = 'zeynal-faz39-sandbox-'
SANDBOX_ENV = dict(FAZ39_SANDBOX='SYNTHETIC_TEST_ONLY', FAZ39_STORAGE_MODE='LOCAL_ONLY',
                   PYTHONDONTWRITEBYTECODE='1', PYTHONUNBUFFERED='1')
COMMAND = 'python -I /sandbox/faz39_sandbox.py'
BLOCKED_MODULES = {'main', 'telegram', 'scheduler', 'dynamic_scheduler', 'scheduler_jobs', 'app', 'bot'}
PRODUCTION_ENV = {'BASELINE_DIR', 'FAZ23_STORAGE', 'SCHEDULER_DB', 'NBA_LEDGER_ENABLED',
                  'NBA_LEDGER_PATH', 'API_SPORTS_BASE', 'ODDS_BASE', 'DATABASE_URL',
                  'FLY_VOLUME_ID', 'FLY_VOLUME_NAME', 'PORT'}


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def validate_config(path):
    config = tomllib.loads(Path(path).read_text())
    require(set(config) == {'primary_region', 'kill_signal', 'kill_timeout', 'build',
                            'env', 'processes', 'restart'}, 'SANDBOX_CONFIG_KEYS')
    require(config['build'] == {'dockerfile': 'Dockerfile.faz39-sandbox'}, 'SANDBOX_BUILD')
    require(config['env'] == SANDBOX_ENV, 'SANDBOX_ENV')
    require(config['processes'] == {'sandbox': COMMAND}, 'SANDBOX_COMMAND')
    require(config['restart'] == [{'policy': 'no', 'processes': ['sandbox']}], 'SANDBOX_RESTART')
    require(config['primary_region'] == 'ams' and config['kill_signal'] == 'SIGTERM'
            and config['kill_timeout'] == '5s', 'SANDBOX_LIFECYCLE')
    return config


def validate_environment(environment):
    require(all(environment.get(k) == v for k, v in SANDBOX_ENV.items()), 'SANDBOX_MODE_REQUIRED')
    app = environment.get('FLY_APP_NAME')
    if app is not None:
        require(re.fullmatch(APP_PREFIX + '[a-z0-9]+(?:-[a-z0-9]+)*', app) is not None,
                'SANDBOX_APP_IDENTITY_REQUIRED')
    for key, value in environment.items():
        if value and (key in PRODUCTION_ENV or re.search(
                r'TOKEN|SECRET|PASSWORD|CREDENTIAL|API[_-]?KEY|PRIVATE[_-]?KEY|TELEGRAM|SCHEDULER', key, re.I)):
            raise ValueError('SANDBOX_FORBIDDEN_ENVIRONMENT')
    require(not Path('/data').exists(), 'SANDBOX_PRODUCTION_MOUNT_PRESENT')


def offline_guard(event, args):
    if event.startswith('socket.') or event in {
            'subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn', 'os.fork', 'pty.spawn'}:
        raise PermissionError('SANDBOX_NETWORK_OR_PROCESS_FORBIDDEN')
    if event == 'import' and args[0].split('.')[0] in BLOCKED_MODULES:
        raise PermissionError('SANDBOX_PRODUCTION_IMPORT_FORBIDDEN')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rows(path):
    with sqlite3.connect(Path(path).as_uri() + '?mode=ro', uri=True) as db:
        require(db.execute('PRAGMA integrity_check').fetchone() == ('ok',), 'SANDBOX_SQLITE_INTEGRITY')
        return db.execute('SELECT id,value FROM sandbox_wal_probe ORDER BY id').fetchall()


def exercise(root, source_sha):
    # Imports occur ONLY after environment/config checks and network/process deny.
    from faz39 import ReadyStore, audit
    from prospective_cuts import CutLedger
    from faz39_recovery import snapshot
    from faz39_transfer import DirectoryStore, export_bundle, import_bundle

    database = root/'synthetic.sqlite'
    ledger = CutLedger(database, 'SYNTHETIC_TEST')
    ReadyStore(ledger)
    with sqlite3.connect(database, timeout=1) as writer:
        require(writer.execute('PRAGMA journal_mode=WAL').fetchone() == ('wal',), 'SANDBOX_WAL_REQUIRED')
        writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute('CREATE TABLE sandbox_wal_probe (id INTEGER PRIMARY KEY,value TEXT)')
        writer.execute("INSERT INTO sandbox_wal_probe VALUES (1,'SYNTHETIC_COMMITTED')")
        writer.commit()
        writer.execute('BEGIN IMMEDIATE')
        writer.execute("INSERT INTO sandbox_wal_probe VALUES (2,'SYNTHETIC_UNCOMMITTED')")
        wal_bytes = Path(str(database)+'-wal').stat().st_size
        require(wal_bytes > 0, 'SANDBOX_WAL_EMPTY')
        bundle = snapshot(database, root/'recovery.tar.gz', source_sha)['bundle']
        writer.rollback()
    writer.close()
    before = sha(database)
    store = DirectoryStore(root/'objects')
    exported = export_bundle(bundle['path'], bundle['sha256'], store)
    pin = exported['manifest_sha256']
    # Local independent namespace only; NOT an external trusted-latest-pin store.
    trusted = root/'trusted'; trusted.mkdir(mode=0o700)
    with (trusted/'manifest.sha256').open('x') as stream:
        stream.write(pin+'\n'); stream.flush(); os.fsync(stream.fileno())
    manifest = root/'objects/manifests'/(pin+'.json')
    require(sha(manifest) == pin, 'SANDBOX_MANIFEST_SHA256')
    restored = import_bundle(store, root/'restored', (trusted/'manifest.sha256').read_text().strip())
    restored_path = root/'restored/faz39.sqlite'
    require(rows(restored_path) == [(1, 'SYNTHETIC_COMMITTED')], 'SANDBOX_WAL_SNAPSHOT_MIXED')
    restored_before = sha(restored_path)
    repeat = export_bundle(bundle['path'], bundle['sha256'], store)
    require(repeat['status'] == 'ALREADY_EXPORTED' and repeat['created_keys'] == [], 'SANDBOX_EXPORT_RETRY')
    try:
        import_bundle(store, root/'restored', pin)
    except FileExistsError:
        pass
    else:
        raise ValueError('SANDBOX_RESTORE_OVERWROTE_TARGET')
    audited = audit(restored_path)
    require(audited['mode'] == 'SYNTHETIC_TEST' and audited['prospective_cuts'] == 0,
            'SANDBOX_PROSPECTIVE_DATA_FORBIDDEN')
    require(sha(restored_path) == restored_before and sha(database) == before,
            'SANDBOX_ORIGINAL_CHANGED')
    return dict(status='SANDBOX_LOCAL_RECOVERY_VERIFIED', usage='SYNTHETIC_TEST', source_sha=source_sha,
                source_sha_attestation='CALLER_OR_BUILD_SUPPLIED_NOT_GITHUB_VERIFIED',
                wal_bytes=wal_bytes, committed_rows_restored=1, uncommitted_rows_restored=0,
                bundle_sha256=bundle['sha256'], manifest_sha256=pin,
                restored_sqlite_sha256=restored_before, original_unchanged=True,
                export_retry=repeat['status'], restore_overwrite_refused=True,
                recovery=restored, integrity=audited['integrity'], storage_mode='LOCAL_ONLY',
                new_real_prospective_records=0, external_upload_performed=False,
                separate_cloud_runtime_verified=False, durable_storage_verified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-sha')
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    try:
        validate_environment(os.environ)
        validate_config(Path(__file__).with_name('fly.faz39-sandbox.toml'))
        sys.addaudithook(offline_guard)
        if args.validate_only:
            print(json.dumps(dict(status='SANDBOX_CONFIG_VALID', external_upload_performed=False)))
            return 0
        source_sha = args.source_sha or Path(__file__).with_name('source-sha.txt').read_text().strip()
        require(re.fullmatch('[0-9a-f]{40}', source_sha) is not None, 'SANDBOX_SOURCE_SHA_REQUIRED')
        os.umask(0o077)
        # No input database/path, no volume mount, no existing target reuse.
        root = Path(tempfile.mkdtemp(prefix='faz39-sandbox-', dir='/tmp')).resolve()
        require(root.parent == Path('/tmp').resolve(), 'SANDBOX_WORKSPACE_REQUIRED')
        # Isolated Python -I excludes cwd; add only this immutable image's code.
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        report = exercise(root, source_sha)
        report.update(work_directory=str(root), runner_sha256=sha(__file__))
        with (root/'report.json').open('x') as stream:
            json.dump(report, stream, sort_keys=True); stream.flush(); os.fsync(stream.fileno())
        print(json.dumps(report, sort_keys=True))
        return 0
    except (OSError, ValueError, sqlite3.Error, ImportError) as exc:
        print(json.dumps(dict(status='SANDBOX_REFUSED', error_type=type(exc).__name__,
                            reason=str(exc) if str(exc).startswith('SANDBOX_') else 'SANDBOX_CHECK_FAILED',
                            verification='NOT_VERIFIED', separate_cloud_runtime_verified=False,
                            durable_storage_verified=False)))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

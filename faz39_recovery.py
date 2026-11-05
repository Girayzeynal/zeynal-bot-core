"""Pinned LOCAL recovery of FAZ39 readiness and cuts; never uploads or rearms."""
import argparse
import json
import os
from pathlib import Path
import tempfile

from faz39 import audit, require
from research_recovery import make_bundle, restore_bundle


def snapshot(database, destination, source_sha):
    # audit is read-only and validates unconsumed readiness receipts too.
    before = audit(database)
    bundle = make_bundle({'faz39.sqlite': str(database)}, destination, source_sha)
    return dict(bundle=bundle, audit=before, external_uploaded=False,
                separate_cloud_runtime_verified=False)


def restore(bundle, destination, expected_sha256):
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    # Generic SQLite integrity is insufficient: validate FAZ39 metadata/bindings
    # in quarantine BEFORE publishing anything at the requested destination.
    with tempfile.TemporaryDirectory(dir=destination.parent) as folder:
        stage = Path(folder)/'checked'
        restore_bundle(bundle, stage, expected_sha256)
        require({p.name for p in stage.glob('*.sqlite')} == {'faz39.sqlite'},
                'UNEXPECTED_FAZ39_RECOVERY_DATABASES')
        audit(stage/'faz39.sqlite')
    result = restore_bundle(bundle, destination, expected_sha256)
    audited = audit(destination/'faz39.sqlite')
    report = dict(status='FAZ39_LOCAL_RESTORE_VERIFIED', audit=audited,
                bundle_sha256=expected_sha256, destination=str(destination),
                separate_cloud_runtime_verified=False, external_uploaded=False,
                rearms_expired_cut=False, base_restore=result['status'])
    # The FAZ39 completion marker is published only after its own full replay.
    with tempfile.NamedTemporaryFile(dir=destination, mode='w', delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(report, stream, sort_keys=True); stream.flush(); os.fsync(stream.fileno())
    try:
        os.link(temporary, destination/'FAZ39_RESTORE_VERIFIED.json')
        fd = os.open(destination, os.O_RDONLY | os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
    finally:
        temporary.unlink(missing_ok=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('snapshot'); p.add_argument('database'); p.add_argument('destination')
    p.add_argument('--source-sha', required=True)
    p = commands.add_parser('restore'); p.add_argument('bundle'); p.add_argument('destination')
    p.add_argument('--expected-sha256', required=True)
    args = parser.parse_args()
    if args.command == 'snapshot':
        result = snapshot(args.database, args.destination, args.source_sha)
    else:
        result = restore(args.bundle, args.destination, args.expected_sha256)
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == '__main__':
    main()

"""Safely stage the pinned optimized Bayesian artifact for isolated research.

No arbitrary tar extraction, no overwrite, and no production volume access.
A successful stage does NOT enable the Telegram bot or authorize deployment.
"""
import argparse
import hashlib
import json
import os
import tarfile
from pathlib import Path

from hybrid_engine.live_nba import PreparedBayes

PACKET_SHA = '9e95f0d849f530325ef881e389179796577a82c65c4aa3be798bbaa2bf3700b3'
MEMBER = 'prepared-optimized/nba-prepared-ae4e578f441770883247e648314c1a7a29c86caa76ab4aa6af006fda4b10254e.json'
MODEL_SHA = 'ae4e578f441770883247e648314c1a7a29c86caa76ab4aa6af006fda4b10254e'


def stage(packet: str, output_dir: str) -> dict:
    root = Path(output_dir).expanduser().resolve()
    production = Path('/data').resolve()
    if root == production or production in root.parents:
        raise ValueError('RESEARCH_DIRECTORY_OVERLAPS_PRODUCTION_VOLUME')
    if not root.is_dir():
        raise ValueError('RESEARCH_DIRECTORY_NOT_PRESENT')
    source = Path(packet)
    h = hashlib.sha256()
    with source.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    if h.hexdigest() != PACKET_SHA:
        raise ValueError('EVIDENCE_PACKET_SHA256_MISMATCH')
    with tarfile.open(source, 'r:gz') as archive:
        member = archive.getmember(MEMBER)
        if not member.isfile() or not 0 < member.size <= 4 * 1024 * 1024:
            raise ValueError('PREPARED_ARCHIVE_MEMBER_INVALID')
        stream = archive.extractfile(member)
        if stream is None:
            raise ValueError('PREPARED_ARCHIVE_MEMBER_UNREADABLE')
        data = stream.read(4 * 1024 * 1024 + 1)
        if len(data) != member.size:
            raise ValueError('PREPARED_ARCHIVE_MEMBER_SIZE_MISMATCH')
    wrapper = json.loads(data)
    if wrapper.get('sha256') != MODEL_SHA:
        raise ValueError('PREPARED_ARCHIVE_PIN_MISMATCH')
    target = root / Path(MEMBER).name
    # Never overwrite existing artifacts or follow a pre-existing symlink.
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, 'O_NOFOLLOW'):
        flags |= os.O_NOFOLLOW
    fd = os.open(target, flags, 0o600)
    try:
        with os.fdopen(fd, 'wb') as dest:
            dest.write(data)
        model = PreparedBayes(str(target), trusted_sha256=MODEL_SHA)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return {
        'status': 'STAGED_RESEARCH_ONLY',
        'path': str(target),
        'sha256': MODEL_SHA,
        'training_games': len(model.model.training_ids),
        'production_promotion': False,
        'calibrated': False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packet', required=True)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    try:
        result = stage(args.packet, args.output_dir)
    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError) as exc:
        print(json.dumps({'status': 'NO_GO', 'reason': type(exc).__name__}))
        raise SystemExit(1) from None
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()

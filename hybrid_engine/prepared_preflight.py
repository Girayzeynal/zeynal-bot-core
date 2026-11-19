"""Read-only offline readiness check for the NBA hybrid prepared model.

Never prints model contents, tokens, or credentials. Does not touch production
ledger, Fly machine, Telegram API, or the /data volume.
"""
import argparse
import json
import os
from pathlib import Path

from hybrid_engine.live_nba import PreparedBayes


def check(prepared_path: str, trusted_sha256: str, research_dir: str) -> dict:
    root = Path(research_dir).expanduser().resolve()
    volume = Path('/data').resolve()
    if root == volume or volume in root.parents:
        raise ValueError('RESEARCH_DIRECTORY_OVERLAPS_PRODUCTION_VOLUME')
    if not root.is_dir():
        raise ValueError('RESEARCH_DIRECTORY_NOT_PRESENT')
    if not os.access(root, os.W_OK):
        raise ValueError('RESEARCH_DIRECTORY_NOT_WRITABLE')
    model = PreparedBayes(prepared_path, trusted_sha256=trusted_sha256)
    return {
        'status': 'RESEARCH_PREPARED_ARTIFACT_VALID',
        'production_promotion': False,
        'calibrated': False,
        'artifact_sha256': trusted_sha256,
        'training_games': len(model.model.training_ids),
        'research_directory': str(root),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared-path', required=True)
    parser.add_argument('--trusted-sha256', required=True)
    parser.add_argument('--research-dir', required=True)
    args = parser.parse_args()
    try:
        result = check(args.prepared_path, args.trusted_sha256, args.research_dir)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'NO_GO', 'reason': type(exc).__name__}))
        raise SystemExit(1) from None
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()

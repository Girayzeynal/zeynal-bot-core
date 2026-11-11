"""Repair PR #79/#80 remote-tracking refs without checkout or working-tree edits.

Default is a local dry run. --apply fetches only explicit origin tracking refs,
atomically. It never edits fly.toml, local branches or index. Fetch configuration
is appended only with the explicit --configure-tracking option.
"""
import argparse
from fnmatch import fnmatchcase
import hashlib
import json
from pathlib import Path
import subprocess


BRANCHES = ('main', 'dev/archive-calibration-orchestration-20261111',
            'dev/season-fixture-audit-20261111')
REFSPECS = tuple('+refs/heads/'+b+':refs/remotes/origin/'+b for b in BRANCHES)


class RefSyncError(ValueError):
    pass


def _git(repo, *args, optional=False):
    try:
        result = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RefSyncError('GIT_COMMAND_UNAVAILABLE_OR_TIMEOUT') from exc
    if result.returncode and not (optional and result.returncode == 1):
        # Git stderr may contain authenticated remote URLs. Never echo it.
        raise RefSyncError('GIT_COMMAND_FAILED_'+str(result.returncode))
    return result.stdout


def _fingerprint(repo, *, include_fetch=True):
    config = repo/'fly.toml'
    fly = hashlib.sha256(config.read_bytes()).hexdigest() if config.is_file() else None
    commands = [('rev-parse', 'HEAD'), ('status', '--porcelain=v1', '-z'),
                ('diff', '--no-ext-diff', '--no-textconv', '--binary'),
                ('diff', '--cached', '--no-ext-diff', '--no-textconv', '--binary')]
    if include_fetch: commands.append(('config', '--get-all', 'remote.origin.fetch'))
    return dict(fly_sha256=fly, git_sha256=hashlib.sha256(b'\0'.join(
        _git(repo, *args, optional=args[0]=='config') for args in commands)).hexdigest())


def _covered(specs, branch, exact):
    return exact in specs or '+refs/heads/*:refs/remotes/origin/*' in specs or (
        branch.startswith('dev/') and '+refs/heads/dev/*:refs/remotes/origin/dev/*' in specs)


def sync_review_refs(repo='.', *, apply=False, configure_tracking=False):
    if type(apply) is not bool or type(configure_tracking) is not bool:
        raise RefSyncError('APPLY_MUST_BE_BOOLEAN')
    if configure_tracking and not apply: raise RefSyncError('CONFIGURE_REQUIRES_APPLY')
    root = Path(_git(repo, 'rev-parse', '--show-toplevel').decode().strip())
    _git(root, 'remote', 'get-url', 'origin')
    original_config=_git(root,'config','--get-all','remote.origin.fetch',optional=True)
    specs=original_config.decode().splitlines()
    if configure_tracking and any(s.startswith('^') and any(fnmatchcase('refs/heads/'+b,s[1:]) for b in BRANCHES) for s in specs):
        raise RefSyncError('NEGATIVE_FETCH_POLICY_REQUIRES_REVIEW')
    before = _fingerprint(root)
    working_before = _fingerprint(root,include_fetch=False)
    existing = {b: _git(root, 'rev-parse', '--verify', '--quiet', 'refs/remotes/origin/'+b, optional=True).decode().strip() or None
                for b in BRANCHES}
    if apply:
        try:
            _git(root, 'fetch', '--no-tags', '--atomic', 'origin', *REFSPECS)
        finally:
            if _fingerprint(root) != before:
                raise RefSyncError('WORKING_TREE_OR_FETCH_CONFIG_CHANGED')
        if configure_tracking:
            for branch,spec in zip(BRANCHES,REFSPECS):
                current=_git(root,'config','--get-all','remote.origin.fetch',optional=True).decode().splitlines()
                if not _covered(current,branch,spec): _git(root,'config','--add','remote.origin.fetch',spec)
            current=_git(root,'config','--get-all','remote.origin.fetch',optional=True).decode().splitlines()
            if not all(s in current for s in specs) or not all(_covered(current,b,s) for b,s in zip(BRANCHES,REFSPECS)):
                raise RefSyncError('FETCH_CONFIG_PRESERVATION_NOT_CONFIRMED')
    resolved = {b: _git(root, 'rev-parse', '--verify', '--quiet', 'refs/remotes/origin/'+b, optional=True).decode().strip() or None
                for b in BRANCHES}
    if apply and any(v is None for v in resolved.values()):
        raise RefSyncError('TRACKING_REF_NOT_CREATED')
    working_unchanged=_fingerprint(root,include_fetch=False)==working_before
    if not working_unchanged: raise RefSyncError('WORKING_TREE_CHANGED')
    return dict(status='REFS_SYNCHRONIZED' if apply else 'DRY_RUN_NO_NETWORK',
                before=existing, refs=resolved, missing=[b for b, v in resolved.items() if v is None],
                fetch_refspecs=list(REFSPECS), fetch_config_changed=_git(root,'config','--get-all','remote.origin.fetch',optional=True)!=original_config,
                head_index_tracked_diff_and_fly_unchanged=working_unchanged,
                fly_toml_sha256=before['fly_sha256'], checkout_performed=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', default='.')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--configure-tracking', action='store_true',help='Append missing exact fetch specs; preserve existing entries')
    args = parser.parse_args(argv)
    try:
        print(json.dumps(sync_review_refs(args.repo, apply=args.apply,configure_tracking=args.configure_tracking), sort_keys=True))
        return 0
    except (RefSyncError, OSError) as exc:
        print(json.dumps(dict(status='REF_SYNC_NOT_CONFIRMED', reason=str(exc))))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

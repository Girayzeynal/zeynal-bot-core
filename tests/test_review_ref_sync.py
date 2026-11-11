"""Actual local Git remotes, restricted clone refspecs and dirty fly.toml."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
import subprocess

from tools.sync_review_refs import BRANCHES, sync_review_refs, RefSyncError


def git(repo, *args, check=True):
    return subprocess.run(['git', '-C', str(repo), *args], check=check, capture_output=True)


class ReviewRefSyncTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.remote, self.seed, self.clone = root/'remote.git', root/'seed', root/'clone'
        self.remote.mkdir(); self.seed.mkdir()
        git(self.remote, 'init', '--bare', '--initial-branch=main')
        git(self.seed, 'init', '--initial-branch=main')
        git(self.seed, 'config', 'user.name', 'Synthetic Test')
        git(self.seed, 'config', 'user.email', 'synthetic@example.invalid')
        (self.seed/'fly.toml').write_text('app = "synthetic-test-only"\n')
        git(self.seed, 'add', 'fly.toml'); git(self.seed, 'commit', '-m', 'synthetic')
        git(self.seed, 'remote', 'add', 'origin', str(self.remote)); git(self.seed, 'push', 'origin', 'main')
        for branch in BRANCHES[1:]:
            git(self.seed, 'branch', branch); git(self.seed, 'push', 'origin', branch)
        git(root, 'clone', '--single-branch', '--branch', 'main', str(self.remote), str(self.clone))
        (self.clone/'fly.toml').write_text('app = "keep-local-modification"\n')
        (self.clone/'untracked.txt').write_text('keep me')

    def test_plain_fetch_reproduces_ambiguous_origin_dev_and_dry_run_does_not_repair(self):
        git(self.clone, 'fetch', 'origin')
        result = git(self.clone, 'diff', 'origin/'+BRANCHES[1], check=False)
        self.assertEqual(result.returncode, 128); self.assertIn(b'ambiguous argument', result.stderr)
        report = sync_review_refs(self.clone)
        self.assertEqual(report['status'], 'DRY_RUN_NO_NETWORK')
        self.assertEqual(set(report['missing']), set(BRANCHES[1:]))

    def test_apply_populates_refs_and_preserves_config_head_index_dirty_files(self):
        before = (self.clone/'fly.toml').read_bytes()
        config = git(self.clone, 'config', '--get-all', 'remote.origin.fetch').stdout
        head = git(self.clone, 'rev-parse', 'HEAD').stdout
        git(self.clone, 'add', 'fly.toml')  # preserve staged changes too
        status = git(self.clone, 'status', '--porcelain').stdout
        report = sync_review_refs(self.clone, apply=True)
        self.assertEqual(report['status'], 'REFS_SYNCHRONIZED'); self.assertEqual(report['missing'], [])
        for b in BRANCHES:
            self.assertEqual(report['refs'][b], git(self.seed, 'rev-parse', b).stdout.decode().strip())
        self.assertEqual((self.clone/'fly.toml').read_bytes(), before)
        self.assertEqual((self.clone/'untracked.txt').read_text(), 'keep me')
        self.assertEqual(git(self.clone, 'rev-parse', 'HEAD').stdout, head)
        self.assertEqual(git(self.clone, 'status', '--porcelain').stdout, status)
        self.assertEqual(git(self.clone, 'config', '--get-all', 'remote.origin.fetch').stdout, config)

    def test_repeat_fetch_refreshes_remote_sha_without_switching_local_branch(self):
        first = sync_review_refs(self.clone, apply=True)
        branch = BRANCHES[-1]
        git(self.seed, 'checkout', branch)
        (self.seed/'new.py').write_text('# synthetic\n')
        git(self.seed, 'add', 'new.py'); git(self.seed, 'commit', '-m', 'update'); git(self.seed, 'push', 'origin', branch)
        second = sync_review_refs(self.clone, apply=True)
        self.assertNotEqual(first['refs'][branch], second['refs'][branch])
        self.assertFalse((self.clone/'new.py').exists())
        self.assertEqual(git(self.clone, 'branch', '--show-current').stdout.strip(), b'main')
        self.assertEqual(second['refs'], sync_review_refs(self.clone, apply=True)['refs'])

    def test_missing_remote_branch_fails_atomically_and_keeps_fly(self):
        git(self.seed, 'push', 'origin', '--delete', BRANCHES[-1])
        before = (self.clone/'fly.toml').read_bytes()
        with self.assertRaises(RefSyncError): sync_review_refs(self.clone, apply=True)
        for b in BRANCHES[1:]:
            self.assertEqual(git(self.clone, 'show-ref', '--verify', 'refs/remotes/origin/'+b, check=False).returncode, 128)
        self.assertEqual((self.clone/'fly.toml').read_bytes(), before)

    def test_configure_appends_missing_specs_once_and_plain_fetch_then_refreshes(self):
        before=(self.clone/'fly.toml').read_bytes()
        original=git(self.clone,'config','--get-all','remote.origin.fetch').stdout.decode().splitlines()
        report=sync_review_refs(self.clone,apply=True,configure_tracking=True)
        specs=git(self.clone,'config','--get-all','remote.origin.fetch').stdout.decode().splitlines()
        self.assertTrue(report['fetch_config_changed']);self.assertTrue(set(original)<=set(specs))
        self.assertEqual(len(specs),3)
        self.assertFalse(sync_review_refs(self.clone,apply=True,configure_tracking=True)['fetch_config_changed'])
        branch=BRANCHES[-1];git(self.seed,'checkout',branch)
        (self.seed/'next.py').write_text('# synthetic second update\n')
        git(self.seed,'add','next.py');git(self.seed,'commit','-m','next');git(self.seed,'push','origin',branch)
        git(self.clone,'fetch','origin')
        self.assertEqual(git(self.clone,'rev-parse','origin/'+branch).stdout,git(self.seed,'rev-parse',branch).stdout)
        self.assertEqual((self.clone/'fly.toml').read_bytes(),before)

    def test_configure_is_explicit_and_does_not_override_negative_policy(self):
        with self.assertRaisesRegex(RefSyncError,'CONFIGURE_REQUIRES_APPLY'):
            sync_review_refs(self.clone,configure_tracking=True)
        git(self.clone,'config','--add','remote.origin.fetch','^refs/heads/dev/*')
        before=git(self.clone,'config','--get-all','remote.origin.fetch').stdout
        with self.assertRaisesRegex(RefSyncError,'NEGATIVE_FETCH_POLICY_REQUIRES_REVIEW'):
            sync_review_refs(self.clone,apply=True,configure_tracking=True)
        self.assertEqual(git(self.clone,'config','--get-all','remote.origin.fetch').stdout,before)

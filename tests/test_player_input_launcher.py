"""Exercise the real launcher with a local synthetic Git origin and no token."""
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase


class PlayerInputLauncherTests(TestCase):
    def test_batch_plan_collect_and_results_dispatch_without_token_or_bot(self):
        root=Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as tmp:
            home=Path(tmp); checkout=home/'zeynal-hybrid-844'; checkout.mkdir()
            installed=checkout/'scripts/run_isolated_test_bot.sh'; installed.parent.mkdir()
            installed.write_text((root/'scripts/run_isolated_test_bot.sh').read_text())
            def git(*args):
                return subprocess.run(['git',*args],cwd=checkout,check=True,capture_output=True,text=True,timeout=10)
            branch='feature/hybrid-market-roster-evidence-20261114'
            git('init','-b',branch)
            git('add','scripts/run_isolated_test_bot.sh')
            git('-c','user.name=Synthetic','-c','user.email=synthetic@example.invalid','commit','--allow-empty','-m','Synthetic launcher fixture')
            git('remote','add','origin',str(checkout))
            binary=checkout/'.venv/bin/python'; binary.parent.mkdir(parents=True); binary.symlink_to(sys.executable)
            package=checkout/'hybrid_engine'; package.mkdir(); (package/'__init__.py').write_text('')
            for module in ('player_inputs','player_shadow','current_roster'):
                (package/(module+'.py')).write_text('import json,sys\nprint(json.dumps(dict(argv=sys.argv[1:],module=__name__)))\n')
            env=dict(os.environ,HOME=str(home),GIT_TERMINAL_PROMPT='0')
            for flag,expected in (('--player-inputs-plan','--dry-run'),('--player-inputs-all','--all-pending'),
                                  ('--player-shadow-results','--report-ledger'),('--roster-status','--inspect')):
                with self.subTest(flag=flag):
                    args=[flag,'401910001'] if flag=='--roster-status' else [flag]
                    p=subprocess.run(['bash',str(root/'scripts/run_isolated_test_bot.sh'),*args],env=env,
                        capture_output=True,text=True,check=True,timeout=15)
                    d=json.loads(next(line for line in p.stdout.splitlines() if line.startswith('{')))
                    self.assertIn(expected,d['argv'])
                    expected_path=home/'zeynal-test-isolated/data/player-shadow'
                    if flag=='--roster-status': expected_path=expected_path/'current-roster'
                    self.assertIn(str(expected_path),d['argv'])
                    self.assertNotIn('test_bot',p.stdout)
                    if flag=='--player-inputs-all': self.assertNotIn('--dry-run',d['argv'])
            self.assertFalse((home/'.zeynal-elite-test-token').exists())


class LauncherUpdateTests(TestCase):
    """Actual Bash/Git update boundary; all Python bot endpoints are local shims."""
    def setUp(self):
        tmp=TemporaryDirectory(); self.addCleanup(tmp.cleanup); self.home=Path(tmp.name)
        self.root=Path(__file__).resolve().parents[1]
        self.origin=self.home/'publisher'; self.origin.mkdir()
        self.checkout=self.home/'zeynal-hybrid-844'
        self.branch='feature/hybrid-market-roster-evidence-20261114'
        self.current=(self.root/'scripts/run_isolated_test_bot.sh').read_text()

    def git(self,path,*args):
        return subprocess.run(['git',*args],cwd=path,check=True,capture_output=True,text=True,timeout=10)

    def setup_installation(self,old,new=None):
        self.git(self.origin,'init','-b',self.branch)
        script=self.origin/'scripts/run_isolated_test_bot.sh'; script.parent.mkdir()
        script.write_text(old); self.commit()
        self.git(self.home,'clone',str(self.origin),str(self.checkout))
        if new is not None:
            script.write_text(new); self.commit()
        binary=self.checkout/'.venv/bin/python'; binary.parent.mkdir(parents=True); binary.symlink_to(sys.executable)
        package=self.checkout/'hybrid_engine'; package.mkdir(); (package/'__init__.py').write_text('')
        for name in ('player_inputs','player_shadow','test_bot'):
            (package/(name+'.py')).write_text('import json,sys\nprint(json.dumps(dict(module='+repr(name)+',argv=sys.argv[1:])))\n')

    def commit(self):
        self.git(self.origin,'add','scripts/run_isolated_test_bot.sh')
        self.git(self.origin,'-c','user.name=Synthetic','-c','user.email=synthetic@example.invalid',
            'commit','-m','Synthetic launcher revision')

    def bootstrap_bot_shim(self):
        (self.home/'.zeynal-elite-test-token').write_text('SYNTHETIC_NOT_A_REAL_TOKEN')
        models=self.home/'zeynal-test-isolated/models'; models.mkdir(parents=True,exist_ok=True)
        (models/'nba-prepared-ae4e578f441770883247e648314c1a7a29c86caa76ab4aa6af006fda4b10254e.json').write_text('{}')

    def call(self,*args,real_module=False):
        # Override only the child test installation, not the user's environment.
        env=dict(os.environ,HOME=str(self.home),GIT_TERMINAL_PROMPT='0')
        if real_module:
            env['PYTHONPATH']=str(self.root)
        return subprocess.run(['bash',str(self.checkout/'scripts/run_isolated_test_bot.sh'),*args],
            env=env,capture_output=True,text=True,timeout=20)

    def json_reply(self,p):
        self.assertEqual(p.returncode,0,p.stderr)
        return json.loads(next(line for line in p.stdout.splitlines() if line.startswith('{')))

    def test_pinned_legacy_self_update_reproduces_wrong_bot_then_new_invocation_routes_plan(self):
        import hashlib
        legacy=(self.root/'tests/fixtures/launcher-8042f2d.sh').read_bytes()
        self.assertEqual(hashlib.sha256(legacy).hexdigest(),'42d77e81cffb9cc247ca8fe32fe94d307eaa1efc1f2f6d263374aa8171c31cd4')
        self.setup_installation(legacy.decode(),self.current)
        self.bootstrap_bot_shim()
        first=self.json_reply(self.call('--player-inputs-plan'))
        # This assertion documents OLD 8042f2d behavior in an isolated shim;
        # no actual Telegram poller or historical prediction is created.
        self.assertEqual(first['module'],'test_bot')
        self.assertEqual((self.checkout/'scripts/run_isolated_test_bot.sh').read_text(),self.current)
        (self.home/'.zeynal-elite-test-token').unlink()
        second=self.json_reply(self.call('--player-inputs-plan'))
        self.assertEqual(second['module'],'player_inputs'); self.assertIn('--dry-run',second['argv'])

    def test_changed_launcher_reexecs_once_and_preserves_requested_mode(self):
        self.setup_installation(self.current,self.current+'\n# Synthetic publisher update\n')
        p=self.call('--player-inputs-plan'); d=self.json_reply(p)
        self.assertEqual(d['module'],'player_inputs'); self.assertIn('--dry-run',d['argv'])
        self.assertEqual(p.stderr.count('RESTARTING_UPDATED_LAUNCHER'),1)
        self.assertFalse((self.home/'.zeynal-elite-test-token').exists())

    def test_reexec_preserves_numeric_fixture_argument_and_releases_polling_lock(self):
        self.setup_installation(self.current,self.current+'\n# Synthetic numeric-mode update\n')
        p=self.call('--player-inputs','401909994'); d=self.json_reply(p)
        self.assertEqual(d['module'],'player_inputs')
        self.assertIn('401909994',d['argv']); self.assertIn('--fixture-id',d['argv'])
        self.assertNotIn('TEST_BOT_ALREADY_RUNNING',p.stdout)
        self.assertEqual(p.stderr.count('RESTARTING_UPDATED_LAUNCHER'),1)

    def test_unknown_mode_does_not_fall_through_to_configured_bot(self):
        self.setup_installation(self.current); self.bootstrap_bot_shim()
        p=self.call('--player-inputs-plna')
        self.assertEqual(p.returncode,2); self.assertIn('UNKNOWN_LAUNCHER_OPTION',p.stderr)
        self.assertNotIn('"module": "test_bot"',p.stdout)
        self.assertNotIn('SYNTHETIC_NOT_A_REAL_TOKEN',p.stdout+p.stderr)

    def test_extra_arguments_do_not_silently_start_a_different_mode(self):
        self.setup_installation(self.current); self.bootstrap_bot_shim()
        for args in (('--player-inputs-plan','unexpected'),('--player-shadow-results','unexpected'),
                     ('--player-inputs','401909994','unexpected')):
            with self.subTest(args=args):
                p=self.call(*args)
                self.assertEqual(p.returncode,2); self.assertIn('INVALID_LAUNCHER_ARGUMENTS',p.stderr)
                self.assertNotIn('"module":',p.stdout)

    def test_plan_reaches_real_python_cli_and_keeps_actual_sqlite_bytes(self):
        from tests.test_ledger_reports import fixture
        self.setup_installation(self.current)
        # No shim package: run the actual module and dependencies, with no token.
        for p in (self.checkout/'hybrid_engine').glob('*.py'): p.unlink()
        ledger=self.home/'zeynal-test-isolated/data/live-nba/nba-hybrid.sqlite'
        ledger.parent.mkdir(parents=True); fixture(ledger,settled=False)
        before=ledger.read_bytes(); reply=self.json_reply(self.call('--player-inputs-plan',real_module=True))
        self.assertEqual(reply['format'],'PLAYER_INPUT_BATCH_V1'); self.assertEqual(reply['status'],'DRY_RUN')
        self.assertTrue(reply['database_bytes_unchanged']); self.assertEqual(ledger.read_bytes(),before)
        self.assertFalse((self.home/'zeynal-test-isolated/data/player-shadow').exists())
        self.assertFalse((self.home/'.zeynal-elite-test-token').exists())

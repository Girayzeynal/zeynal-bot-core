"""New worktree code must never silently run the old checkout's modules."""
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase


class IntegratedLauncherTests(TestCase):
    def setUp(self):
        temp=TemporaryDirectory();self.addCleanup(temp.cleanup);self.home=Path(temp.name)
        self.old=self.home/'zeynal-hybrid-844';self.new=self.home/'integration worktree'
        binary=self.old/'.venv/bin/python';binary.parent.mkdir(parents=True);binary.symlink_to(sys.executable)
        original=Path(__file__).resolve().parents[1]/'scripts/run_isolated_test_bot.sh'
        self.script=self.new/'scripts/run_isolated_test_bot.sh';self.script.parent.mkdir(parents=True)
        self.script.write_bytes(original.read_bytes())
        for checkout,marker in ((self.old,'WRONG_OLD_MODULE'),(self.new,'NEW_WORKTREE_MODULE')):
            for package,module in (('hybrid_engine','device_verification'),('scripts','settle_all_leagues')):
                folder=checkout/package;folder.mkdir(exist_ok=True)
                (folder/'__init__.py').write_text('')
                (folder/(module+'.py')).write_text('import json,sys\nprint(json.dumps(dict(marker='+repr(marker)+',argv=sys.argv[1:])))')

    def call(self,*args):
        env=dict(os.environ,HOME=str(self.home),PYTHONPATH='')
        return subprocess.run(['bash',str(self.script),*args],env=env,capture_output=True,text=True,timeout=10)

    def test_readonly_modes_borrow_venv_but_run_new_worktree_modules_without_git_token_or_lock(self):
        for flag in ('--verification-review','--results-review','--settle-results'):
            with self.subTest(flag=flag):
                p=self.call(flag);self.assertEqual(p.returncode,0,p.stderr);r=json.loads(p.stdout)
                self.assertEqual(r['marker'],'NEW_WORKTREE_MODULE')
                self.assertIn(str(self.home/'zeynal-test-isolated/data'),r['argv'])
                self.assertEqual('--apply' in r['argv'],flag=='--settle-results')
        self.assertFalse((self.home/'.zeynal-elite-test-token').exists())
        self.assertFalse((self.home/'zeynal-test-isolated').exists())

    def test_extra_arguments_cannot_silently_settle_or_start_bot(self):
        for flag in ('--verification-review','--results-review','--settle-results'):
            p=self.call(flag,'extra');self.assertEqual(p.returncode,2)
            self.assertIn('INVALID_LAUNCHER_ARGUMENTS',p.stderr);self.assertEqual(p.stdout,'')

    def test_worktree_without_either_interpreter_has_actionable_failure(self):
        (self.old/'.venv/bin/python').unlink()
        p=self.call('--verification-review');self.assertEqual(p.returncode,2)
        self.assertIn('ISOLATED_PYTHON_NOT_FOUND',p.stderr)

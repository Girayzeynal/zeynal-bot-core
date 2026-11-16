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
            def git(*args):
                return subprocess.run(['git',*args],cwd=checkout,check=True,capture_output=True,text=True,timeout=10)
            branch='feature/hybrid-market-roster-evidence-20261114'
            git('init','-b',branch)
            git('-c','user.name=Synthetic','-c','user.email=synthetic@example.invalid','commit','--allow-empty','-m','Synthetic launcher fixture')
            git('remote','add','origin',str(checkout))
            binary=checkout/'.venv/bin/python'; binary.parent.mkdir(parents=True); binary.symlink_to(sys.executable)
            package=checkout/'hybrid_engine'; package.mkdir(); (package/'__init__.py').write_text('')
            for module in ('player_inputs','player_shadow'):
                (package/(module+'.py')).write_text('import json,sys\nprint(json.dumps(dict(argv=sys.argv[1:],module=__name__)))\n')
            env=dict(os.environ,HOME=str(home),GIT_TERMINAL_PROMPT='0')
            for flag,expected in (('--player-inputs-plan','--dry-run'),('--player-inputs-all','--all-pending'),
                                  ('--player-shadow-results','--report-ledger')):
                with self.subTest(flag=flag):
                    p=subprocess.run(['bash',str(root/'scripts/run_isolated_test_bot.sh'),flag],env=env,
                        capture_output=True,text=True,check=True,timeout=15)
                    d=json.loads(next(line for line in p.stdout.splitlines() if line.startswith('{')))
                    self.assertIn(expected,d['argv'])
                    self.assertIn(str(home/'zeynal-test-isolated/data/player-shadow'),d['argv'])
                    self.assertNotIn('test_bot',p.stdout)
                    if flag=='--player-inputs-all': self.assertNotIn('--dry-run',d['argv'])
            self.assertFalse((home/'.zeynal-elite-test-token').exists())

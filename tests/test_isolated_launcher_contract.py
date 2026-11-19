"""Protect the single-command UserLAnd launcher from unsafe regressions."""
import pathlib
import subprocess
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]
SCRIPT=ROOT/'scripts'/'run_isolated_test_bot.sh'

class IsolatedLauncherTests(unittest.TestCase):
    def test_bash_syntax(self):
        subprocess.run(['bash','-n',str(SCRIPT)],check=True,capture_output=True)
    def test_isolated_identity_and_pinned_model(self):
        body=SCRIPT.read_text()
        for required in ('git merge --ff-only FETCH_HEAD',
                         'flock -n 9',
                         'TEST_BOT_ALREADY_RUNNING',
                         'WRONG_BRANCH','TEST_TOKEN_FILE_MISSING',
                         'PINNED_MODEL_FILE_MISSING',
                         'ZEYNAL_TEST_BOT_TOKEN',
                         'ZEYNAL_TEST_BOT_ID','ZEYNAL_TEST_CHAT_ID',
                         '--nba-model-sha ae4e578f441770883247e648314c1a7a29c86caa76ab4aa6af006fda4b10254e',
                         '--result-poll-seconds 300',
                         'exec "${test_python}" -m hybrid_engine.test_bot'):
            with self.subTest(required=required):
                self.assertIn(required,body)
        self.assertNotIn('fly deploy',body)
        self.assertNotIn('git reset --hard',body)

if __name__=='__main__':
    unittest.main()

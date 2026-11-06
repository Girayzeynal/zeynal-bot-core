"""Offline sandbox preparation only; no Fly CLI, remote store or live forecasts."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

import faz39_sandbox as sandbox

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT/'fly.faz39-sandbox.toml'
SHA = 'a'*40  # Synthetic test label, never a GitHub attestation.


def environment():
    # Never inherit a developer/CI token into this offline child process.
    return dict(PATH=os.environ.get('PATH', '/usr/bin:/bin'), LANG='C.UTF-8', **sandbox.SANDBOX_ENV)


def child(*args, env=None, script=None):
    return subprocess.run([sys.executable, '-I', str(script or ROOT/'faz39_sandbox.py'), *args],
                          env=environment() if env is None else env,
                          text=True, capture_output=True, timeout=40)


class SandboxTests(unittest.TestCase):
    def test_configuration_is_one_shot_without_app_volume_service_or_secrets(self):
        config = sandbox.validate_config(CONFIG)
        self.assertEqual(config['processes'], {'sandbox': sandbox.COMMAND})
        self.assertFalse({'app','mounts','services','http_service','deploy','statics'} & set(config))
        self.assertEqual(config['restart'], [{'policy':'no','processes':['sandbox']}])

    def test_production_resources_and_unknown_config_keys_are_refused(self):
        config = tomllib.loads(CONFIG.read_text())
        production = tomllib.loads((ROOT/'fly.toml').read_text())
        additions = dict(app=production['app'], mounts=production['mounts'],
                         http_service=production['http_service'], services=[],
                         deploy={'release_command':'python main.py'}, secrets={})
        for key, value in additions.items():
            with self.subTest(key=key), patch.object(sandbox.tomllib, 'loads', return_value=dict(config, **{key:value})):
                with self.assertRaisesRegex(ValueError,'SANDBOX_CONFIG_KEYS'):sandbox.validate_config(CONFIG)

    def test_bot_command_production_dockerfile_env_and_restart_are_refused(self):
        original = tomllib.loads(CONFIG.read_text())
        for section, value in [('processes',{'sandbox':'python main.py'}),
                               ('build',{'dockerfile':'Dockerfile'}),
                               ('env',dict(sandbox.SANDBOX_ENV, TELEGRAM_BOT_TOKEN='synthetic')),
                               ('restart',[{'policy':'always','processes':['sandbox']}])]:
            config = dict(original, **{section:value})
            with self.subTest(section=section), patch.object(sandbox.tomllib,'loads',return_value=config):
                with self.assertRaises(ValueError):sandbox.validate_config(CONFIG)

    def test_production_and_ambiguous_fly_app_identity_are_refused(self):
        for app in ['zeynal-bot-core','', 'zeynal-faz39-sandbox-', 'other-test', 'zeynal-faz39-sandbox-x/../production']:
            with self.subTest(app=app), self.assertRaisesRegex(ValueError,'SANDBOX_APP_IDENTITY_REQUIRED'):
                sandbox.validate_environment(dict(environment(),FLY_APP_NAME=app))
        sandbox.validate_environment(dict(environment(),FLY_APP_NAME='zeynal-faz39-sandbox-test-01'))

    def test_credentials_production_volume_and_scheduler_environment_are_refused(self):
        for key in ['TELEGRAM_BOT_TOKEN','FLY_API_TOKEN','AWS_SECRET_ACCESS_KEY','DATABASE_URL',
                    'NBA_LEDGER_PATH','SCHEDULER_DB','FLY_VOLUME_NAME','API_SPORTS_BASE', 'ODDS_BASE',
                    'PRODUCTION_SCHEDULER_ENABLED','TELEGRAM_WEBHOOK_URL']:
            with self.subTest(key=key), self.assertRaisesRegex(ValueError,'SANDBOX_FORBIDDEN_ENVIRONMENT'):
                sandbox.validate_environment(dict(environment(), **{key:'synthetic-not-a-secret'}))

    def test_wrong_mode_or_production_mount_is_refused_before_data_creation(self):
        env = environment(); env['FAZ39_STORAGE_MODE']='EXTERNAL'
        with self.assertRaisesRegex(ValueError,'SANDBOX_MODE_REQUIRED'):sandbox.validate_environment(env)
        with patch.object(sandbox.Path,'exists',return_value=True):
            with self.assertRaisesRegex(ValueError,'SANDBOX_PRODUCTION_MOUNT_PRESENT'):
                sandbox.validate_environment(environment())

    def test_runtime_checks_fail_closed_with_nonzero_exit(self):
        for env in [dict(environment(),FLY_APP_NAME='zeynal-bot-core'),
                    dict(environment(),TELEGRAM_BOT_TOKEN='synthetic')]:
            completed = child('--source-sha', SHA, env=env)
            self.assertEqual(completed.returncode,1)
            report=json.loads(completed.stdout)
            self.assertEqual(report['status'],'SANDBOX_REFUSED')
            self.assertFalse(report['durable_storage_verified'])
            self.assertNotIn('synthetic',completed.stdout)

    def test_no_arbitrary_input_database_destination_or_scheduler_cli(self):
        for flag in ['--database','--destination','--upload','--scheduler','--polling','--webhook']:
            with self.subTest(flag=flag):
                self.assertEqual(child(flag,'/data/production.sqlite').returncode,2)

    def test_real_audit_hook_blocks_network_processes_and_bot_imports(self):
        code = '''import sys,importlib,socket,subprocess,os
sys.path.insert(0,sys.argv[1])
import faz39_sandbox as s
sys.addaudithook(s.offline_guard)
actions=[lambda:socket.socket(),lambda:socket.getaddrinfo('example.invalid',443),
         lambda:subprocess.run([sys.executable,'-c','pass']),lambda:os.system('true'),
         lambda:importlib.import_module('main'),lambda:importlib.import_module('telegram'),
         lambda:importlib.import_module('dynamic_scheduler')]
for action in actions:
 try:action()
 except (PermissionError,ModuleNotFoundError):pass
 else:raise AssertionError('sandbox guard allowed an unsafe operation')
print('OFFLINE_GUARD_VERIFIED')'''
        result=subprocess.run([sys.executable,'-I','-c',code,str(ROOT)],env=environment(),
                              capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.strip(),'OFFLINE_GUARD_VERIFIED')

    def test_image_copy_and_context_allowlist_exclude_production_and_real_data(self):
        paths = json.loads((ROOT/'config/faz39-sandbox-image-files.json').read_text())
        dockerfile = (ROOT/'Dockerfile.faz39-sandbox').read_text()
        copied = []
        for line in dockerfile.splitlines():
            if line.startswith('COPY --chmod=0444 ['):
                copied.extend(json.loads(line.partition('[')[1]+line.partition('[')[2])[:-1])
        self.assertEqual(sorted(copied),sorted(paths))
        denied={'main.py','dynamic_scheduler.py','fly.toml','Dockerfile','requirements.txt'}
        self.assertFalse(denied & set(paths))
        for name in paths:
            self.assertTrue((ROOT/name).is_file(),name)
            self.assertNotIn('..',Path(name).parts)
            self.assertFalse(any(x in name for x in ['.sqlite','.env','.git/','__pycache__']))
        ignore=(ROOT/'Dockerfile.faz39-sandbox.dockerignore').read_text().splitlines()
        self.assertEqual([l for l in ignore if l and not l.startswith('#')][0],'**')
        include={l[1:] for l in ignore if l.startswith('!') and not l.endswith('/')}
        self.assertEqual(include,set(paths)|{'requirements.faz39-sandbox.txt',
                         'Dockerfile.faz39-sandbox','Dockerfile.faz39-sandbox.dockerignore'})
        for line in ignore:
            if line.startswith('!') and line.endswith('/'):
                self.assertIn(line[1:]+'**',ignore)
        self.assertNotIn('COPY .',dockerfile)
        self.assertIn('USER 10001:10001',dockerfile)
        self.assertIn('CMD ["python", "-I", "/sandbox/faz39_sandbox.py"]',dockerfile)

    def test_sandbox_dependencies_exclude_telegram_sdk(self):
        deps=(ROOT/'requirements.faz39-sandbox.txt').read_text().lower()
        self.assertNotIn('telegram',deps)
        self.assertNotIn('fly',deps)

    def test_ci_builds_image_and_runs_without_network_or_persistent_mount(self):
        workflow=(ROOT/'.github/workflows/python-tests.yml').read_text()
        self.assertIn('--file Dockerfile.faz39-sandbox',workflow)
        self.assertIn('--build-arg FAZ39_SOURCE_SHA=',workflow)
        self.assertIn('--network=none --read-only --cap-drop=ALL',workflow)
        self.assertIn('--tmpfs /tmp:',workflow)
        self.assertNotIn('fly deploy',workflow)

    def test_isolated_selected_sources_wal_transfer_restore_and_hash_proof(self):
        # Emulate ONLY the selected image files in a fresh local directory.
        # This is NOT a container or a second Cloud runtime.
        with tempfile.TemporaryDirectory(prefix='faz39-image-test-') as folder:
            stage=Path(folder)
            for name in json.loads((ROOT/'config/faz39-sandbox-image-files.json').read_text()):
                target=stage/name;target.parent.mkdir(exist_ok=True,parents=True)
                shutil.copyfile(ROOT/name,target)
            (stage/'source-sha.txt').write_text(SHA)
            result=child(script=stage/'faz39_sandbox.py')
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            report=json.loads(result.stdout); work=Path(report['work_directory'])
            self.addCleanup(shutil.rmtree,work)
            self.assertEqual(report['status'],'SANDBOX_LOCAL_RECOVERY_VERIFIED')
            self.assertEqual(report['source_sha'],SHA)
            self.assertGreater(report['wal_bytes'],0)
            self.assertEqual(report['committed_rows_restored'],1)
            self.assertEqual(report['uncommitted_rows_restored'],0)
            self.assertEqual(report['export_retry'],'ALREADY_EXPORTED')
            self.assertTrue(report['restore_overwrite_refused'])
            self.assertTrue(report['original_unchanged'])
            self.assertEqual(report['new_real_prospective_records'],0)
            for field in ['durable_storage_verified','separate_cloud_runtime_verified','external_upload_performed']:
                self.assertIs(report[field],False)
            pin=report['manifest_sha256']
            self.assertEqual(hashlib.sha256((work/'objects/manifests'/f'{pin}.json').read_bytes()).hexdigest(),pin)
            with sqlite3.connect(work/'restored/faz39.sqlite') as db:
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(),('ok',))
                self.assertEqual(db.execute('SELECT COUNT(*) FROM sandbox_wal_probe').fetchone(),(1,))
                self.assertEqual(db.execute('SELECT mode FROM faz33_meta').fetchone(),('SYNTHETIC_TEST',))
                self.assertEqual(db.execute('SELECT COUNT(*) FROM faz33_cuts').fetchone(),(0,))

    def test_missing_or_invalid_source_sha_never_claims_verification(self):
        for value in ['', 'unknown', 'a'*39, 'A'*40]:
            result=child('--source-sha',value)
            self.assertEqual(result.returncode,1,result.stdout)
            self.assertEqual(json.loads(result.stdout)['verification'],'NOT_VERIFIED')

    def test_validate_only_does_not_claim_recovery(self):
        result=child('--validate-only')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        report=json.loads(result.stdout)
        self.assertEqual(report,dict(status='SANDBOX_CONFIG_VALID',external_upload_performed=False))


if __name__=='__main__':unittest.main()

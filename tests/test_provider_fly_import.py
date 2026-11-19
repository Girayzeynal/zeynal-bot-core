"""Synthetic CLI responses only. No Fly or provider credentials are accessed."""
import base64
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from hybrid_engine.provider_access import credentials
from hybrid_engine.provider_fly_import import transfer,MACHINE,MARKER,REMOTE


class FakeFly:
    def __init__(self):
        self.calls=[];self.state='started';self.values={'ODDS_API_KEY':'SYNTHETIC_ODDS','API_SPORTS_KEY':'SYNTHETIC_SPORTS'}
        self.returncode=0;self.packet=None
    def __call__(self,args,**kwargs):
        self.calls.append((args,kwargs))
        if 'list' in args:
            body=json.dumps([dict(id=MACHINE,state=self.state)])
        else:
            encoded=base64.b64encode(json.dumps(self.values).encode()).decode()
            body='Connecting to machine...\n'+MARKER+encoded+'\n' if self.packet is None else self.packet
        return SimpleNamespace(returncode=self.returncode,stdout=body.encode(),stderr=b'')


class ReadOnlyFlyImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.target=Path(self.tmp.name)/'private.env';self.fly=FakeFly()
    def run_transfer(self):return transfer(self.target,runner=self.fly,fly='fly')
    def test_only_authorized_running_machine_read_and_no_values_in_report(self):
        r=self.run_transfer()
        self.assertEqual(credentials({},self.target),{'THE_ODDS_API':'SYNTHETIC_ODDS','API_BASKETBALL':'SYNTHETIC_SPORTS'})
        self.assertNotIn('SYNTHETIC',json.dumps(r));self.assertFalse(r['production_changed'])
        self.assertFalse(r['staged_secrets_activated']);self.assertEqual(len(self.fly.calls),2)
        args,kwargs=self.fly.calls[1]
        self.assertIn(MACHINE,args);self.assertIn('--command',args)
        self.assertTrue(kwargs['capture_output']);self.assertFalse(kwargs['check'])
        self.assertNotIn('SYNTHETIC',' '.join(args))
    def test_stopped_machine_never_ssh_or_start(self):
        self.fly.state='stopped'
        with self.assertRaisesRegex(ValueError,'NO_START_ATTEMPTED'):self.run_transfer()
        self.assertEqual(len(self.fly.calls),1);self.assertFalse(self.target.exists())
    def test_deployed_odds_only_does_not_activate_staged_api_sports(self):
        self.fly.values={'ODDS_API_KEY':'SYNTHETIC_ODDS'}
        r=self.run_transfer();self.assertEqual(r['providers']['API_BASKETBALL'],'KEY_NOT_FOUND_IN_LOCAL_SOURCE_OR_TEST_CONFIG')
        self.assertFalse(r['staged_secrets_activated'])
    def test_token_or_unknown_field_packet_refused(self):
        self.fly.values['TELEGRAM_BOT_TOKEN']='DO_NOT_IMPORT'
        with self.assertRaisesRegex(ValueError,'ALLOWLIST'):self.run_transfer()
        self.assertFalse(self.target.exists())
    def test_missing_or_duplicate_packet_refused(self):
        for packet in ['no marker','\n'.join([MARKER+'e30=',MARKER+'e30='])]:
            self.fly.packet=packet
            with self.assertRaisesRegex(ValueError,'PACKET_NOT_RECEIVED'):self.run_transfer()
            self.assertFalse(self.target.exists())
    def test_fly_auth_failure_is_safe(self):
        self.fly.returncode=1
        with self.assertRaisesRegex(ValueError,'READ_ONLY_FLY_COMMAND_FAILED'):self.run_transfer()
        self.assertFalse(self.target.exists())
    def test_no_readable_key_does_not_make_empty_file(self):
        self.fly.values={}
        self.assertEqual(self.run_transfer()['status'],'NO_PROVIDER_KEYS_READABLE_FROM_RUNNING_MACHINE')
        self.assertFalse(self.target.exists())
    def test_remote_program_is_valid_python_with_no_mutating_calls(self):
        import ast
        ast.parse(REMOTE)
        for forbidden in ['os.system','subprocess','unlink','remove(','write(','sqlite','requests.']:
            self.assertNotIn(forbidden,REMOTE)


if __name__=='__main__':unittest.main()

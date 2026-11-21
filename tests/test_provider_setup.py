"""Synthetic local key migration only; no production or authenticated traffic."""
import json
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import unittest

from hybrid_engine.provider_access import credentials
from hybrid_engine.provider_setup import import_local


class LocalProviderSetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.source=self.root/'.env';self.target=self.root/'private.env'

    def test_import_only_data_keys_without_source_change_or_output_values(self):
        body='TELEGRAM_BOT_TOKEN=DO_NOT_COPY\nexport ODDS_API_KEY="SYNTHETIC_ODDS" # note\nAPI_SPORTS_KEY=SYNTHETIC_SPORTS\n'
        self.source.write_text(body)
        result=import_local(self.source,self.target)
        self.assertEqual(self.source.read_text(),body)
        self.assertNotIn('DO_NOT_COPY',self.target.read_text())
        self.assertNotIn('SYNTHETIC',json.dumps(result))
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode),0o600)
        self.assertEqual(credentials({},self.target),{'THE_ODDS_API':'SYNTHETIC_ODDS','API_BASKETBALL':'SYNTHETIC_SPORTS'})

    def test_no_data_keys_does_not_create_empty_configuration(self):
        self.source.write_text('TELEGRAM_BOT_TOKEN=DO_NOT_COPY\nOTHER_KEY=value\n')
        self.assertEqual(import_local(self.source,self.target)['status'],'NO_PROVIDER_KEYS_FOUND_IN_LOCAL_SOURCE')
        self.assertFalse(self.target.exists())

    def test_repeated_import_is_idempotent(self):
        self.source.write_text('THE_ODDS_API_KEY=SYNTHETIC_ODDS\n')
        import_local(self.source,self.target);before=self.target.stat().st_mtime_ns
        self.assertEqual(import_local(self.source,self.target)['status'],'ALREADY_CONFIGURED_UNCHANGED')
        self.assertEqual(self.target.stat().st_mtime_ns,before)

    def test_conflict_never_replaces_existing_test_key(self):
        self.source.write_text('ODDS_API_KEY=SYNTHETIC_ODDS\n');import_local(self.source,self.target)
        before=self.target.read_bytes();self.source.write_text('ODDS_API_KEY=DIFFERENT\n')
        with self.assertRaisesRegex(ValueError,'CONFLICT_UNCHANGED'):import_local(self.source,self.target)
        self.assertEqual(self.target.read_bytes(),before)

    def test_missing_second_provider_can_be_added_without_changing_first(self):
        self.source.write_text('ODDS_API_KEY=SYNTHETIC_ODDS\n');import_local(self.source,self.target)
        self.source.write_text('API_BASKETBALL_KEY=SYNTHETIC_SPORTS\n');import_local(self.source,self.target)
        self.assertEqual(credentials({},self.target),{'THE_ODDS_API':'SYNTHETIC_ODDS','API_BASKETBALL':'SYNTHETIC_SPORTS'})

    def test_conflicting_aliases_and_shell_substitution_refused(self):
        for body in ['ODDS_API_KEY=one\nTHE_ODDS_API_KEY=two\n','ODDS_API_KEY=$(id)\n','ODDS_API_KEY=`id`\n']:
            self.source.write_text(body)
            with self.assertRaises(ValueError):import_local(self.source,self.target)
            self.assertFalse(self.target.exists())

    def test_symlink_source_or_destination_refused(self):
        real=self.root/'real';real.write_text('ODDS_API_KEY=SYNTHETIC_ODDS\n')
        self.source.symlink_to(real)
        with self.assertRaises(ValueError):import_local(self.source,self.target)
        self.source.unlink();self.source.write_text(real.read_text());self.target.symlink_to(real)
        with self.assertRaises(ValueError):import_local(self.source,self.target)
        self.assertEqual(real.read_text(),'ODDS_API_KEY=SYNTHETIC_ODDS\n')

    def test_same_source_destination_refused(self):
        self.source.write_text('ODDS_API_KEY=SYNTHETIC_ODDS\n')
        with self.assertRaisesRegex(ValueError,'MUST_DIFFER'):import_local(self.source,self.source)


if __name__=='__main__':unittest.main()

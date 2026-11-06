"""Real local SQLite bundles through FAKE external contract; no remote calls."""
from dataclasses import replace
import hashlib
from pathlib import Path
import sqlite3
import unittest

import faz39_checkpoint_contract as c
from faz39_transfer import export_bundle,import_bundle
from tests import test_faz39_storage as storage
from tests import test_faz39_checkpoint_contract as fake


class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.local=storage.StorageTests();await self.local.asyncSetUp()
        for function,args,kwargs in self.local._cleanups:self.addCleanup(function,*args,**kwargs)
        self.local._cleanups.clear()
        self.contract=fake.ContractTests();self.contract.setUp()
        self.backend=fake.FakeBackend();self.store=self.contract.store(self.backend)
        self.policy=dict(mode='EXTERNAL',external_target=self.store.target_id,upload_enabled=True)
        b=self.local.bundle
        self.export=export_bundle(b['path'],b['sha256'],self.store,policy=self.policy)
        self.key='manifests/'+self.export['manifest_sha256']+'.json'
        self.manifest=self.backend.objects[self.key]
        self.pin=dict(self.contract.pin,manifest_sha256=self.export['manifest_sha256'],
                      ledger_id=self.local.store.ledger_id)
        self.raw=fake.envelope(self.pin)
        self.anchor=replace(self.contract.anchor,ledger_id=self.pin['ledger_id'],pin_sha256=c.digest(self.pin))

    def plan(self):
        return c.verify_restore_plan(self.raw,self.anchor,self.manifest,**self.contract.kw)

    async def test_trust_plan_then_full_existing_sqlite_import_without_production_io(self):
        plan=self.plan()
        self.assertEqual(plan['status'],'RESTORE_PLAN_VALIDATED_NOT_EXECUTED')
        target=self.local.fx.root/'contract-restored'
        result=import_bundle(self.store,target,self.pin['manifest_sha256'],policy=dict(self.policy,upload_enabled=False))
        self.assertEqual(result['recovery']['audit']['mode'],'SYNTHETIC_TEST')
        self.assertEqual(result['recovery']['audit']['prospective_cuts'],0)
        self.assertFalse(result['separate_cloud_runtime_verified'])
        with sqlite3.connect(target/'faz39.sqlite') as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(),('ok',))
            self.assertEqual(db.execute('SELECT ledger_id FROM faz39_identity').fetchone(),(self.pin['ledger_id'],))
        repeat=export_bundle(self.local.bundle['path'],self.local.bundle['sha256'],self.store,policy=self.policy)
        self.assertEqual(repeat['status'],'ALREADY_EXPORTED')

    async def test_trust_gate_failure_does_not_touch_existing_sqlite_or_adapter(self):
        source=Path(self.local.fx.ledger.path);before=hashlib.sha256(source.read_bytes()).hexdigest()
        self.backend.calls.clear();self.anchor=replace(self.anchor,generation=2)
        with self.assertRaisesRegex(c.Refused,'STALE_OR_FORKED'):self.plan()
        self.assertEqual(self.backend.calls,[])
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),before)

    async def test_valid_attested_pin_cannot_make_a_corrupt_bundle_safe(self):
        self.plan();key='objects/'+self.local.bundle['sha256']+'.tar.gz'
        self.backend.objects[key]=self.backend.objects[key][:-1]+b'x'
        target=self.local.fx.root/'corrupt-target'
        with self.assertRaises(ValueError):
            import_bundle(self.store,target,self.pin['manifest_sha256'],policy=self.policy)
        self.assertFalse(target.exists())

    async def test_missing_commit_after_valid_pin_is_still_an_incomplete_upload(self):
        self.plan();del self.backend.objects['commits/'+self.pin['manifest_sha256']+'.json']
        target=self.local.fx.root/'incomplete-target'
        with self.assertRaisesRegex(ValueError,'INCOMPLETE_OR_MISSING'):
            import_bundle(self.store,target,self.pin['manifest_sha256'],policy=self.policy)
        self.assertFalse(target.exists())

    async def test_manifest_payload_substitution_cannot_bypass_the_trusted_gate(self):
        self.manifest=self.manifest+b' '
        with self.assertRaisesRegex(c.Refused,'DIGEST'):self.plan()


if __name__=='__main__':unittest.main()

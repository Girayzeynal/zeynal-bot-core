"""Local/memory protocol and real SQLite WAL tests; all records are synthetic."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tarfile
import threading
import time
import unittest
from unittest.mock import patch

from faz25 import backup
from faz34 import cut_proofs
from faz39 import Refused, audit, require
from faz39_recovery import snapshot, restore
from faz39_transfer import DirectoryStore, export_bundle, import_bundle, LOCAL_ONLY
from prediction_inputs import canonical_json, digest
from tests import test_faz39 as fixtures


class MemoryStore:
    scope = 'LOCAL_STAGING'
    target_id = 'memory-test'

    def __init__(self):
        self.objects = {}; self.calls = []; self.lock = threading.Lock()

    def read(self, key, maximum_bytes):
        with self.lock:
            self.calls.append(('read', key))
            if key not in self.objects:raise FileNotFoundError(key)
            raw = self.objects[key]
            require(len(raw) <= maximum_bytes, 'TEST_STORE_READ_LIMIT')
            return raw

    def put_if_absent(self, key, value):
        with self.lock:
            self.calls.append(('put', key))
            if key in self.objects:return False
            self.objects[key] = value
            return True


class StorageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fxcase = fixtures.ReadinessTests(); await self.fxcase.asyncSetUp()
        for function, args, kwargs in self.fxcase._cleanups:self.addCleanup(function, *args, **kwargs)
        self.fxcase._cleanups.clear()
        self.fx = self.fxcase.fx; self.p = self.fxcase.p; self.store = self.fxcase.store
        self.p.update(schema_version=2, ledger_id=self.store.ledger_id,
                      config_sha256=self.store.config_hash(self.fxcase.config()))
        self.receipt = self.store.put(self.p)
        self.bundle = snapshot(self.fx.ledger.path, self.fx.root/'source.tar.gz', 'a'*40)['bundle']
        self.memory = MemoryStore()

    def export(self, store=None, bundle=None):
        b = bundle or self.bundle
        return export_bundle(b['path'], b['sha256'], store or self.memory)

    async def test_default_configuration_is_local_only_and_network_free(self):
        config = json.loads((Path(__file__).resolve().parents[1]/'config/faz39-local.example.json').read_text())
        self.assertEqual(config['storage'], LOCAL_ONLY)
        result = self.export()
        self.assertFalse(result['external_transfer_requested'])
        self.assertFalse(result['durable_storage_verified'])
        self.assertFalse(result['separate_cloud_runtime_verified'])

    async def test_collector_configuration_still_cannot_enable_external_upload(self):
        from faz35 import validate_config
        config=self.fxcase.config()
        config['storage']=dict(mode='EXTERNAL',external_target='memory-test',upload_enabled=True)
        with self.assertRaisesRegex(ValueError,'no authorized external target'):validate_config(config)

    async def test_default_external_policy_refuses_before_any_adapter_io(self):
        self.memory.scope = 'EXTERNAL'
        for action in (lambda:self.export(), lambda:import_bundle(self.memory,self.fx.root/'out','0'*64)):
            with self.assertRaisesRegex(Refused,'EXTERNAL_TARGET_NOT_AUTHORIZED'):action()
        self.assertEqual(self.memory.calls, [])

    async def test_external_target_and_upload_authorization_are_both_required(self):
        self.memory.scope = 'EXTERNAL'
        policies = [dict(mode='EXTERNAL',external_target='wrong',upload_enabled=True),
                    dict(mode='EXTERNAL',external_target=self.memory.target_id,upload_enabled=False)]
        for p in policies:
            with self.assertRaises(Refused):
                export_bundle(self.bundle['path'],self.bundle['sha256'],self.memory,policy=p)
        self.assertEqual(self.memory.calls, [])

    async def test_provider_contract_can_be_exercised_without_a_network_provider(self):
        # EXTERNAL is an in-memory fake here, never an enabled runtime config.
        self.memory.scope = 'EXTERNAL'
        policy = dict(mode='EXTERNAL',external_target=self.memory.target_id,upload_enabled=True)
        exported = export_bundle(self.bundle['path'],self.bundle['sha256'],self.memory,policy=policy)
        read_only = dict(policy,upload_enabled=False)
        result = import_bundle(self.memory,self.fx.root/'memory-external-fake',exported['manifest_sha256'],policy=read_only)
        self.assertEqual(result['status'],'LOCAL_RECOVERY_VERIFIED')
        self.assertFalse(result['separate_cloud_runtime_verified'])

    async def test_export_is_idempotent_and_commit_is_published_last(self):
        first = self.export(); second = self.export()
        self.assertEqual(second['status'],'ALREADY_EXPORTED')
        self.assertEqual(first['manifest_sha256'],second['manifest_sha256'])
        self.assertEqual(len(self.memory.objects),3)
        puts = [key for op,key in self.memory.calls if op=='put']
        self.assertTrue(puts[2].startswith('commits/'))
        raw = self.memory.objects['manifests/'+first['manifest_sha256']+'.json']
        manifest = json.loads(raw)
        self.assertEqual(manifest['source_commit'],'a'*40)
        self.assertEqual(manifest['bundle']['size_bytes'],Path(self.bundle['path']).stat().st_size)
        self.assertEqual(manifest['ledger']['ledger_id'],self.store.ledger_id)

    async def test_directory_roundtrip_preserves_original_cut_and_receipt(self):
        runner = self.fxcase.runner(); self.fx.clock.now=fixtures.fixtures.BASE+3
        await fixtures.faz39.capture_armed(runner)
        before = cut_proofs(self.fx.ledger.path)
        b = snapshot(self.fx.ledger.path,self.fx.root/'recorded.tar.gz','a'*40)['bundle']
        store = DirectoryStore(self.fx.root/'local-objects')
        exported = self.export(store,b)
        result = import_bundle(store,self.fx.root/'imported',exported['manifest_sha256'])
        database = self.fx.root/'imported/faz39.sqlite'
        self.assertEqual(cut_proofs(database),before)
        self.assertEqual(result['recovery']['audit']['synthetic_cuts'],1)
        self.assertEqual(result['recovery']['audit']['prospective_cuts'],0)
        self.assertFalse(result['separate_cloud_runtime_verified'])
        self.assertEqual(audit(database)['integrity'],'ok')

    async def test_wrong_bundle_pin_writes_no_objects(self):
        with self.assertRaises(Refused):export_bundle(self.bundle['path'],'0'*64,self.memory)
        self.assertEqual(self.memory.calls,[])

    async def test_wrong_manifest_pin_cannot_select_another_checkpoint(self):
        self.export()
        with self.assertRaisesRegex(Refused,'EXPORT_INCOMPLETE_OR_MISSING'):
            import_bundle(self.memory,self.fx.root/'wrong-pin','0'*64)
        self.assertFalse((self.fx.root/'wrong-pin').exists())

    async def test_existing_restore_target_is_never_overwritten(self):
        exported = self.export(); target=self.fx.root/'existing'; target.mkdir()
        (target/'keep').write_text('preserve'); self.memory.calls.clear()
        with self.assertRaises(FileExistsError):import_bundle(self.memory,target,exported['manifest_sha256'])
        self.assertEqual((target/'keep').read_text(),'preserve');self.assertEqual(self.memory.calls,[])

    async def test_partial_transfer_is_not_importable_and_retry_is_safe(self):
        expected=self.export()['manifest_sha256'];broken=MemoryStore();original=broken.put_if_absent
        def fail_second(key,value):
            if key.startswith('manifests/'):raise ConnectionError('synthetic disconnect')
            return original(key,value)
        broken.put_if_absent=fail_second
        with self.assertRaises(ConnectionError):self.export(broken)
        self.assertEqual(len(broken.objects),1)
        with self.assertRaisesRegex(Refused,'EXPORT_INCOMPLETE_OR_MISSING'):
            import_bundle(broken,self.fx.root/'partial',expected)
        broken.put_if_absent=original;completed=self.export(broken)
        self.assertEqual(completed['manifest_sha256'],expected);self.assertEqual(len(broken.objects),3)

    async def test_conflicting_existing_blob_is_not_replaced_or_committed(self):
        key='objects/'+self.bundle['sha256']+'.tar.gz';self.memory.objects[key]=b'corruption'
        with self.assertRaisesRegex(Refused,'STORED_OBJECT_CONFLICT'):self.export()
        self.assertEqual(self.memory.objects[key],b'corruption')
        self.assertFalse(any(key.startswith('commits/') for key in self.memory.objects))

    async def test_failed_read_after_write_never_publishes_commit_marker(self):
        original=self.memory.read
        def wrong(key,limit):
            if key.startswith('objects/'):return b'wrong acknowledged bytes'
            return original(key,limit)
        self.memory.read=wrong
        with self.assertRaisesRegex(Refused,'STORED_OBJECT_CONFLICT'):self.export()
        self.assertFalse(any(key.startswith('commits/') for key in self.memory.objects))

    async def test_commit_manifest_byte_length_is_checked_before_restore(self):
        exported=self.export();sha=exported['manifest_sha256'];key='commits/'+sha+'.json'
        marker=json.loads(self.memory.objects[key]);marker['manifest_bytes']+=1
        self.memory.objects[key]=canonical_json(marker).encode()
        with self.assertRaisesRegex(Refused,'MANIFEST_PIN_OR_LENGTH_MISMATCH'):
            import_bundle(self.memory,self.fx.root/'bad-length',sha)
        self.assertFalse((self.fx.root/'bad-length').exists())

    async def test_manifest_and_blob_corruption_refuse_before_destination_creation(self):
        exported=self.export();sha=exported['manifest_sha256'];original=deepcopy(self.memory.objects)
        for key in ('manifests/'+sha+'.json','objects/'+self.bundle['sha256']+'.tar.gz'):
            self.memory.objects=deepcopy(original);self.memory.objects[key]+=b'corruption'
            with self.assertRaises((ValueError,KeyError)):
                import_bundle(self.memory,self.fx.root/'corrupt-output',sha)
            self.assertFalse((self.fx.root/'corrupt-output').exists())

    async def test_rehashed_manifest_cannot_lie_about_size_source_or_usage(self):
        exported=self.export();raw=self.memory.objects['manifests/'+exported['manifest_sha256']+'.json']
        for mutate in (lambda p:p['bundle'].update(size_bytes=p['bundle']['size_bytes']+1),
                       lambda p:p.update(source_commit='b'*40),
                       lambda p:p['ledger'].update(mode='PROSPECTIVE'),
                       lambda p:p['files']['faz39.sqlite'].update(size_bytes=float(p['files']['faz39.sqlite']['size_bytes'])),
                       lambda p:p['files']['faz39.sqlite'].update(sha256='0'*64)):
            p=json.loads(raw);mutate(p);encoded=canonical_json(p).encode();sha=hashlib.sha256(encoded).hexdigest()
            self.memory.objects['manifests/'+sha+'.json']=encoded
            self.memory.objects['commits/'+sha+'.json']=canonical_json(dict(schema_version=1,manifest_sha256=sha,manifest_bytes=len(encoded))).encode()
            with self.assertRaises(Refused):import_bundle(self.memory,self.fx.root/'forged',sha)
            self.assertFalse((self.fx.root/'forged').exists())

    async def test_duplicate_json_keys_and_unknown_schema_are_refused(self):
        exported=self.export();key='commits/'+exported['manifest_sha256']+'.json'
        original=self.memory.objects[key]
        self.memory.objects[key]=original.replace(b'"schema_version":1',b'"schema_version":1,"schema_version":1')
        with self.assertRaisesRegex(Refused,'DUPLICATE_MANIFEST_KEY'):
            import_bundle(self.memory,self.fx.root/'duplicate',exported['manifest_sha256'])
        marker=json.loads(original);marker['schema_version']=2;self.memory.objects[key]=json.dumps(marker).encode()
        with self.assertRaisesRegex(Refused,'COMMIT_MARKER_INVALID'):
            import_bundle(self.memory,self.fx.root/'schema',exported['manifest_sha256'])

    async def test_unsafe_archive_members_and_decompression_size_are_refused(self):
        path=self.fx.root/'unsafe.tar.gz'
        with tarfile.open(path,'w:gz') as tar:
            raw=b'outside';item=tarfile.TarInfo('../escape');item.size=len(raw);tar.addfile(item,io.BytesIO(raw))
        sha=hashlib.sha256(path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(Refused,'UNSAFE_OR_DUPLICATE'):export_bundle(path,sha,self.memory)
        with patch('faz39_transfer.MAX_SQLITE',1):
            with self.assertRaisesRegex(Refused,'EXPANDED_BUNDLE_TOO_LARGE'):self.export()
        self.assertEqual(self.memory.objects,{})

    async def test_hash_correct_but_invalid_sqlite_is_not_exported(self):
        raw=b'not a SQLite database'
        manifest=dict(schema_version=1,source_version='a'*40,external_uploaded=False,
                      files={'faz39.sqlite':hashlib.sha256(raw).hexdigest()})
        path=self.fx.root/'invalid-sqlite.tar.gz'
        with tarfile.open(path,'w:gz') as tar:
            for name,value in [('manifest.json',canonical_json(manifest).encode()),('faz39.sqlite',raw)]:
                info=tarfile.TarInfo(name);info.size=len(value);tar.addfile(info,io.BytesIO(value))
        with self.assertRaises(sqlite3.DatabaseError):
            export_bundle(path,hashlib.sha256(path.read_bytes()).hexdigest(),self.memory)
        self.assertEqual(self.memory.objects,{})

    async def test_hidden_pax_metadata_cannot_bypass_expanded_size_limit(self):
        path=self.fx.root/'large-pax.tar.gz'
        with tarfile.open(path,'w:gz',format=tarfile.PAX_FORMAT) as tar:
            info=tarfile.TarInfo('manifest.json');info.size=2
            info.pax_headers={'untrusted.metadata':'x'*(2*1024*1024)}
            tar.addfile(info,io.BytesIO(b'{}'))
        with patch('faz39_transfer.MAX_SQLITE',1024):
            with self.assertRaisesRegex(Refused,'EXPANDED_BUNDLE_TOO_LARGE'):
                export_bundle(path,hashlib.sha256(path.read_bytes()).hexdigest(),self.memory)
        self.assertEqual(self.memory.objects,{})

    async def test_local_object_keys_symlinks_permissions_and_no_overwrite(self):
        store=DirectoryStore(self.fx.root/'safe');key='objects/'+'a'*64+'.tar.gz'
        self.assertTrue(store.put_if_absent(key,b'first'))
        self.assertFalse(store.put_if_absent(key,b'second'))
        self.assertEqual(store.read(key,100),b'first')
        self.assertEqual((store.root/key).stat().st_mode & 0o777,0o600)
        with self.assertRaises(Refused):store.read('../outside',100)
        with self.assertRaises(Refused):store.read(key,1)
        link=self.fx.root/'link';link.symlink_to(store.root,target_is_directory=True)
        with self.assertRaisesRegex(Refused,'SYMLINK'):DirectoryStore(link)

    async def test_concurrent_local_exports_have_one_immutable_commit(self):
        store=DirectoryStore(self.fx.root/'parallel')
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.export(store),range(2)))
        self.assertEqual(results[0]['manifest_sha256'],results[1]['manifest_sha256'])
        self.assertEqual(sorted(result['status'] for result in results),['ALREADY_EXPORTED','EXPORTED'])
        self.assertEqual(len(list((store.root/'commits').glob('*.json'))),1)
        self.assertEqual(sum(key.startswith('commits/') for result in results for key in result['created_keys']),1)
        self.assertEqual(len(list(store.root.rglob('.pending-*'))),0)

    async def test_import_in_fresh_python_process_is_not_cross_cloud_evidence(self):
        store=DirectoryStore(self.fx.root/'process-store');result=self.export(store)
        code="import sys,json;sys.path.insert(0,sys.argv[1]);from faz39_transfer import DirectoryStore,import_bundle;print(json.dumps(import_bundle(DirectoryStore(sys.argv[2]),sys.argv[3],sys.argv[4])))"
        process=subprocess.run([sys.executable,'-I','-c',code,str(Path(__file__).resolve().parents[1]),
            str(store.root),str(self.fx.root/'new-process'),result['manifest_sha256']],
            check=True,capture_output=True,text=True,timeout=30)
        restored=json.loads(process.stdout)
        self.assertEqual(restored['status'],'LOCAL_RECOVERY_VERIFIED')
        self.assertFalse(restored['separate_cloud_runtime_verified'])
        self.assertEqual(restored['recovery']['audit']['prospective_cuts'],0)


class WalTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.b=fixtures.ReadinessTests();await self.b.asyncSetUp()
        for function,args,kwargs in self.b._cleanups:self.addCleanup(function,*args,**kwargs)
        self.b._cleanups.clear();self.fx=self.b.fx;self.p=self.b.p
        self.p.update(schema_version=2,ledger_id=self.b.store.ledger_id,
                      config_sha256=self.b.store.config_hash(self.b.config()))
        self.b.store.put(self.p)
        self.writer=sqlite3.connect(self.fx.ledger.path,timeout=1)
        self.addCleanup(self.writer.close)
        self.assertEqual(self.writer.execute('PRAGMA journal_mode=WAL').fetchone(),('wal',))
        self.writer.execute('PRAGMA wal_autocheckpoint=0')

    def alternate(self,delta):
        p=deepcopy(self.p);p['ready_utc']-=delta
        return p

    def restore_snapshot(self,name):
        b=snapshot(self.fx.ledger.path,self.fx.root/(name+'.tar.gz'),'a'*40)
        result=restore(b['bundle']['path'],self.fx.root/name,b['bundle']['sha256'])
        self.assertEqual(b['audit'],result['audit'])
        return self.fx.root/name/'faz39.sqlite',result

    async def test_committed_wal_pages_are_included_without_copying_sidecars(self):
        self.b.store.put(self.alternate(.1))
        self.assertGreater(Path(self.fx.ledger.path+'-wal').stat().st_size,0)
        database,result=self.restore_snapshot('wal-committed')
        self.assertEqual(result['audit']['faz39_ready_receipts'],2)
        self.assertEqual(audit(database)['integrity'],'ok')
        self.assertEqual(result['audit']['prospective_cuts'],0)

    async def test_open_wal_transaction_is_excluded_then_committed_atomically(self):
        self.writer.execute('CREATE TABLE wal_transaction_probe (value INTEGER)');self.writer.commit()
        p=self.alternate(.1);self.writer.execute('BEGIN IMMEDIATE')
        self.writer.execute('INSERT INTO faz39_ready VALUES (?,?)',(digest(p),canonical_json(p)))
        self.writer.execute('INSERT INTO wal_transaction_probe VALUES (1)')
        database,result=self.restore_snapshot('before-commit')
        self.assertEqual(result['audit']['faz39_ready_receipts'],1)
        with sqlite3.connect(database) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM wal_transaction_probe').fetchone()[0],0)
        self.writer.commit();database,result=self.restore_snapshot('after-commit')
        self.assertEqual(result['audit']['faz39_ready_receipts'],2)
        with sqlite3.connect(database) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM wal_transaction_probe').fetchone()[0],1)

    async def test_rollback_of_active_wal_writer_never_appears_in_backup(self):
        p=self.alternate(.1);self.writer.execute('BEGIN IMMEDIATE')
        self.writer.execute('INSERT INTO faz39_ready VALUES (?,?)',(digest(p),canonical_json(p)))
        _,result=self.restore_snapshot('rolled-back-writer');self.writer.rollback()
        self.assertEqual(result['audit']['faz39_ready_receipts'],1)
        self.assertEqual(audit(self.fx.ledger.path)['faz39_ready_receipts'],1)

    async def test_real_writer_commit_during_incremental_backup_has_no_mixed_generation(self):
        self.writer.execute('CREATE TABLE wal_generation_probe (id INTEGER PRIMARY KEY,generation INTEGER,payload BLOB)')
        self.writer.executemany('INSERT INTO wal_generation_probe VALUES (?,0,?)',[(i,b'x'*8192) for i in range(256)])
        self.writer.commit();entered=threading.Event();done=threading.Event();errors=[]
        real_connect=sqlite3.connect
        def writer():
            try:
                require(entered.wait(5),'TEST_BACKUP_DID_NOT_START')
                with real_connect(self.fx.ledger.path,timeout=1) as db:
                    db.execute('BEGIN IMMEDIATE');db.execute('UPDATE wal_generation_probe SET generation=1')
            except BaseException as exc:errors.append(exc)
            finally:done.set()
        class ObservedConnection(sqlite3.Connection):
            def backup(connection,target,**kwargs):
                original=kwargs['progress']
                def progress(status,remaining,total):
                    original(status,remaining,total)
                    if not entered.is_set():
                        entered.set();require(done.wait(5),'TEST_WRITER_DID_NOT_COMMIT')
                return super(ObservedConnection,connection).backup(target,**dict(kwargs,progress=progress))
        def connect(*args,**kwargs):return real_connect(*args,**dict(kwargs,factory=ObservedConnection))
        worker=threading.Thread(target=writer);worker.start()
        try:
            with patch('faz25.sqlite3.connect',side_effect=connect):database,_=self.restore_snapshot('concurrent-writer')
        finally:entered.set();worker.join(6)
        self.assertFalse(worker.is_alive());self.assertEqual(errors,[])
        with real_connect(database) as db:
            generations=db.execute('SELECT DISTINCT generation FROM wal_generation_probe').fetchall()
            self.assertIn(generations,([(0,)],[(1,)]))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM wal_generation_probe').fetchone()[0],256)
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(),('ok',))

    async def test_exclusive_rollback_journal_writer_times_out_without_publication(self):
        self.writer.close();self.writer=sqlite3.connect(self.fx.ledger.path,timeout=1);self.addCleanup(self.writer.close)
        self.assertEqual(self.writer.execute('PRAGMA journal_mode=DELETE').fetchone(),('delete',))
        self.writer.execute('BEGIN EXCLUSIVE');target=self.fx.root/'locked.sqlite';began=time.perf_counter()
        try:
            with self.assertRaises(TimeoutError):backup(self.fx.ledger.path,target,timeout_seconds=.2)
        finally:self.writer.rollback()
        self.assertLess(time.perf_counter()-began,3)
        self.assertFalse(target.exists());self.assertEqual(audit(self.fx.ledger.path)['integrity'],'ok')


if __name__=='__main__':unittest.main()

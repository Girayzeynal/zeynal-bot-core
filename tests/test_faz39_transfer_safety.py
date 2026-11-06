"""Local recovery failure injection; no disk filling, network or real records."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import errno
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

from faz39 import Refused, audit
from faz39_recovery import snapshot
from faz39_transfer import DirectoryStore, export_bundle, import_bundle
from tests import test_faz39_storage as fixtures


class TransferSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.b=fixtures.StorageTests();await self.b.asyncSetUp()
        for function,args,kwargs in self.b._cleanups:self.addCleanup(function,*args,**kwargs)
        self.b._cleanups.clear()
        self.fx=self.b.fx;self.bundle=self.b.bundle;self.store=DirectoryStore(self.fx.root/'objects')

    def export(self,store=None,bundle=None):
        b=bundle or self.bundle
        return export_bundle(b['path'],b['sha256'],store or self.store)

    def contents(self):
        return {str(p.relative_to(self.store.root)):hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.store.root.rglob('*') if p.is_file()}

    def assert_unpublished(self):
        self.assertEqual(list(self.store.root.glob('commits/*.json')),[])
        self.assertEqual(list(self.store.root.rglob('.pending-*')),[])

    def fd_path(self,fd):
        return Path(os.readlink('/proc/self/fd/'+str(fd)))

    async def test_missing_malformed_pin_is_refused_before_adapter_read(self):
        memory=fixtures.MemoryStore()
        for pin in (None,'','latest','0'*63,'g'*64,True):
            with self.subTest(pin=pin):
                with self.assertRaisesRegex(Refused,'TRUSTED_SHA256_REQUIRED'):
                    import_bundle(memory,self.fx.root/'missing-pin',pin)
        self.assertEqual(memory.calls,[])

    async def test_missing_correct_commit_marker_never_falls_back(self):
        result=self.export();pin=result['manifest_sha256']
        (self.store.root/'commits'/(pin+'.json')).unlink()
        with self.assertRaisesRegex(Refused,'EXPORT_INCOMPLETE_OR_MISSING'):
            import_bundle(self.store,self.fx.root/'incomplete',pin)
        self.assertFalse((self.fx.root/'incomplete').exists())
        self.assertEqual(self.export()['manifest_sha256'],pin)

    async def test_stale_valid_pin_selects_exact_checkpoint_without_latest_claim(self):
        old=self.export();p=deepcopy(self.b.p);p['ready_utc']-=.1;self.b.store.put(p)
        newer=snapshot(self.fx.ledger.path,self.fx.root/'newer.tar.gz','a'*40)['bundle']
        latest=self.export(bundle=newer)
        self.assertNotEqual(old['manifest_sha256'],latest['manifest_sha256'])
        result=import_bundle(self.store,self.fx.root/'exact-old-pin',old['manifest_sha256'])
        self.assertEqual(result['recovery']['audit']['faz39_ready_receipts'],1)
        self.assertEqual(result['checkpoint_selection'],'EXACT_TRUSTED_PIN')
        self.assertEqual(result['pin_freshness'],'NOT_ATTESTED')
        result=import_bundle(self.store,self.fx.root/'exact-new-pin',latest['manifest_sha256'])
        self.assertEqual(result['recovery']['audit']['faz39_ready_receipts'],2)

    async def test_stale_manifest_under_new_pin_is_refused(self):
        memory=fixtures.MemoryStore();old=self.export(memory);p=deepcopy(self.b.p)
        p['ready_utc']-=.1;self.b.store.put(p)
        newer=snapshot(self.fx.ledger.path,self.fx.root/'newer.tar.gz','a'*40)['bundle']
        latest=self.export(memory,newer)
        memory.objects['manifests/'+latest['manifest_sha256']+'.json']=memory.objects['manifests/'+old['manifest_sha256']+'.json']
        with self.assertRaisesRegex(Refused,'MANIFEST_PIN_OR_LENGTH_MISMATCH'):
            import_bundle(memory,self.fx.root/'stale-substitution',latest['manifest_sha256'])
        self.assertFalse((self.fx.root/'stale-substitution').exists())

    async def test_truncated_and_bitflipped_bundle_fail_closed(self):
        memory=fixtures.MemoryStore();result=self.export(memory);key='objects/'+self.bundle['sha256']+'.tar.gz'
        raw=memory.objects[key]
        for changed in (raw[:-8],bytes([raw[0]^1])+raw[1:]):
            memory.objects[key]=changed
            with self.assertRaises(Refused):import_bundle(memory,self.fx.root/'corrupt',result['manifest_sha256'])
            self.assertFalse((self.fx.root/'corrupt').exists())

    async def test_read_after_write_visibility_lag_leaves_incomplete_then_retries(self):
        memory=fixtures.MemoryStore();original=memory.read;delayed=[False]
        def invisible(key,limit):
            if key.startswith('objects/') and not delayed[0]:
                delayed[0]=True;raise FileNotFoundError('injected visibility lag')
            return original(key,limit)
        memory.read=invisible
        with self.assertRaises(FileNotFoundError):self.export(memory)
        self.assertFalse(any(key.startswith('commits/') for key in memory.objects))
        result=self.export(memory)
        self.assertEqual(result['status'],'EXPORTED');self.assertEqual(len(memory.objects),3)

    async def test_lost_commit_ack_can_retry_without_duplicate(self):
        memory=fixtures.MemoryStore();original=memory.put_if_absent;failed=[False]
        def lost_ack(key,value):
            made=original(key,value)
            if key.startswith('commits/') and not failed[0]:
                failed[0]=True;raise TimeoutError('injected lost commit acknowledgement')
            return made
        memory.put_if_absent=lost_ack
        with self.assertRaises(TimeoutError):self.export(memory)
        self.assertEqual(len(memory.objects),3)
        result=self.export(memory)
        self.assertEqual(result['status'],'ALREADY_EXPORTED')
        self.assertEqual(result['created_keys'],[])

    async def test_disk_full_before_object_link_cleans_pending_file(self):
        original=os.fsync
        def full(fd):
            p=self.fd_path(fd)
            if p.parent==self.store.root/'objects' and p.name.startswith('.pending-'):
                raise OSError(errno.ENOSPC,'injected disk full')
            return original(fd)
        with patch('faz39_transfer.os.fsync',side_effect=full):
            with self.assertRaises(OSError) as raised:self.export()
        self.assertEqual(raised.exception.errno,errno.ENOSPC)
        self.assert_unpublished();self.assertEqual(self.contents(),{})
        self.assertEqual(self.export()['status'],'EXPORTED')

    async def test_permission_error_linking_manifest_does_not_publish_commit(self):
        original=os.link
        def denied(*args,**kwargs):
            folder=kwargs.get('dst_dir_fd')
            if folder is not None and self.fd_path(folder)==self.store.root/'manifests':
                raise PermissionError(errno.EACCES,'injected manifest permission failure')
            return original(*args,**kwargs)
        with patch('faz39_transfer.os.link',side_effect=denied):
            with self.assertRaises(PermissionError):self.export()
        self.assert_unpublished()
        self.assertEqual(len(list((self.store.root/'objects').glob('*.tar.gz'))),1)
        self.assertEqual(self.export()['status'],'EXPORTED')

    async def test_post_link_directory_sync_failure_must_also_fail_on_retry(self):
        original=os.fsync
        def failed_sync(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode) and self.fd_path(fd)==self.store.root/'commits':
                raise OSError(errno.ENOSPC,'injected commit directory fsync failure')
            return original(fd)
        with patch('faz39_transfer.os.fsync',side_effect=failed_sync):
            with self.assertRaises(OSError):self.export()
            self.assertEqual(len(list((self.store.root/'commits').glob('*.json'))),1)
            with self.assertRaises(OSError):self.export()
        self.assertEqual(self.export()['status'],'ALREADY_EXPORTED')
        self.assertEqual(len(list((self.store.root/'commits').glob('*.json'))),1)

    async def test_disk_full_writing_import_staging_keeps_destination_absent(self):
        result=self.export();original=Path.write_bytes;destination=self.fx.root/'disk-full-import'
        def full(path,value):
            if path.name=='verified.tar.gz' and path.parent.parent==self.fx.root:
                raise OSError(errno.ENOSPC,'injected import staging full')
            return original(path,value)
        before=self.contents()
        with patch('faz39_transfer.Path.write_bytes',new=full):
            with self.assertRaises(OSError):import_bundle(self.store,destination,result['manifest_sha256'])
        self.assertFalse(destination.exists());self.assertEqual(before,self.contents())

    async def test_partial_restore_disk_full_has_no_verified_marker_or_overwrite(self):
        result=self.export();destination=self.fx.root/'partial-restore';original=os.fdopen
        class FailedWriter:
            def __init__(self,stream):self.stream=stream
            def __enter__(self):return self
            def __exit__(self,*args):self.stream.close()
            def write(self,value):raise OSError(errno.ENOSPC,'injected SQLite restore write full')
        def fdopen(fd,*args,**kwargs):
            path=self.fd_path(fd);stream=original(fd,*args,**kwargs)
            return FailedWriter(stream) if path==destination/'faz39.sqlite' else stream
        with patch('research_recovery.os.fdopen',side_effect=fdopen):
            with self.assertRaises(OSError):import_bundle(self.store,destination,result['manifest_sha256'])
        self.assertTrue(destination.exists())
        self.assertFalse((destination/'FAZ39_RESTORE_VERIFIED.json').exists())
        self.assertFalse((destination/'RESTORE_COMPLETE.json').exists())
        with self.assertRaises(FileExistsError):import_bundle(self.store,destination,result['manifest_sha256'])
        recovered=import_bundle(self.store,self.fx.root/'different-new-target',result['manifest_sha256'])
        self.assertEqual(recovered['status'],'LOCAL_RECOVERY_VERIFIED')

    @unittest.skipIf(os.geteuid()==0,'root bypasses ordinary permission bits')
    async def test_real_read_only_target_parent_permission_is_refused(self):
        result=self.export();parent=self.fx.root/'read-only';parent.mkdir();parent.chmod(0o500)
        try:
            with self.assertRaises(PermissionError):
                import_bundle(self.store,parent/'target',result['manifest_sha256'])
            self.assertFalse((parent/'target').exists())
        finally:parent.chmod(0o700)

    async def test_reader_cannot_import_before_concurrent_publisher_commits(self):
        expected=self.b.export()['manifest_sha256'];original=self.store.put_if_absent
        waiting=threading.Event();release=threading.Event()
        def pause(key,value):
            if key.startswith('commits/'):
                waiting.set();self.assertTrue(release.wait(5))
            return original(key,value)
        self.store.put_if_absent=pause
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(self.export)
            try:
                self.assertTrue(waiting.wait(5))
                with self.assertRaisesRegex(Refused,'EXPORT_INCOMPLETE_OR_MISSING'):
                    import_bundle(self.store,self.fx.root/'early-reader',expected)
                self.assertFalse((self.fx.root/'early-reader').exists())
            finally:release.set()
            self.assertEqual(future.result(timeout=10)['manifest_sha256'],expected)
        self.assertEqual(import_bundle(self.store,self.fx.root/'late-reader',expected)['status'],'LOCAL_RECOVERY_VERIFIED')

    async def test_concurrent_importers_share_no_partial_destination(self):
        result=self.export();barrier=threading.Barrier(2);original=self.store.read
        def synchronize(key,limit):
            if key.startswith('commits/'):barrier.wait(5)
            return original(key,limit)
        self.store.read=synchronize;destination=self.fx.root/'two-importers'
        def importer():
            try:return import_bundle(self.store,destination,result['manifest_sha256'])['status']
            except FileExistsError:return 'EXISTING_TARGET'
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:importer(),range(2)))
        self.assertEqual(sorted(results),['EXISTING_TARGET','LOCAL_RECOVERY_VERIFIED'])
        self.assertEqual(audit(destination/'faz39.sqlite')['integrity'],'ok')

    async def test_cli_io_failure_reports_unknown_publication_not_success(self):
        import contextlib
        from faz39_transfer import main
        output=io.StringIO()
        argv=['faz39_transfer','export',self.bundle['path'],str(self.store.root),
              '--expected-bundle-sha256',self.bundle['sha256']]
        with patch.object(sys,'argv',argv),patch('faz39_transfer.export_bundle',side_effect=OSError(errno.ENOSPC,'injected')),contextlib.redirect_stdout(output):
            code=main()
        report=json.loads(output.getvalue())
        self.assertEqual(code,1);self.assertEqual(report['status'],'TRANSFER_FAILED')
        self.assertEqual(report['publication_state'],'UNKNOWN_AUDIT_REQUIRED')
        self.assertFalse(report['local_recovery_verified'])
        self.assertNotIn('injected',output.getvalue())
        # Check the actual -m entry point as well as the main() return value.
        process=subprocess.run([sys.executable,'-m','faz39_transfer','import',str(self.store.root),
            str(self.fx.root/'cli-invalid-pin'),'--expected-manifest-sha256','invalid'],
            cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=20)
        self.assertEqual(process.returncode,1)
        self.assertEqual(json.loads(process.stdout)['reason'],'TRUSTED_SHA256_REQUIRED')


if __name__=='__main__':unittest.main()

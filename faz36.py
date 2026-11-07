"""Local-only checkpoint publication protocol and operational readiness audit."""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import time
import uuid

from faz25 import exclusive
from faz32 import read_store
from faz32_collect import write_json
from faz35 import validate_config,source_sha,capsule
from prediction_inputs import canonical_json,digest
from prospective_cuts import inspect,GRACE
from research_recovery import restore_bundle

IMMUTABLE_KEYS={
    'faz33_cuts':('fixture_id','horizon'),'faz33_evaluations':('fixture_id',),'faz33_fixtures':('fixture_id',),
    'faz33_meta':('mode',),'faz33_attempts':('id',),'faz34_events':('seq',),'observations':('observation_id',),'metadata':('key',),
    'predictions':('league','fixture_id'),'prediction_inputs':('league','fixture_id'),
    'outcomes':('league','fixture_id'),'outcome_evidence':('league','fixture_id'),
    'faz24_stages':('fixture_id',),'period_result_evidence':('fixture_id',)}


class StateConflict(ValueError):pass


def file_sha(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):value.update(chunk)
    return value.hexdigest()


def keep_capsule(root,bundle,expected_sha256):
    folder=root/'capsules';folder.mkdir(mode=0o700,exist_ok=True)
    target=folder/(expected_sha256+'.tar.gz')
    if target.exists():
        if file_sha(target)!=expected_sha256:raise ValueError('stored capsule corruption')
        return
    temporary=folder/('.copy-'+uuid.uuid4().hex)
    try:
        with Path(bundle).open('rb') as source,os.fdopen(os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'wb') as output:
            for chunk in iter(lambda:source.read(1024*1024),b''):output.write(chunk)
            output.flush();os.fsync(output.fileno())
        if file_sha(temporary)!=expected_sha256:raise ValueError('capsule changed during publication')
        os.link(temporary,target)
        fd=os.open(folder,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
    finally:
        if temporary.exists():temporary.unlink()


def inventory(bundle,expected_sha256):
    with tempfile.TemporaryDirectory(prefix='faz36-inventory-') as folder:
        root=Path(folder)/'restored';restored=restore_bundle(bundle,root,expected_sha256)
        records={}
        for report in restored['verification']['files']:
            name=report['name']
            with closing(sqlite3.connect((root/name).as_uri()+'?mode=ro',uri=True)) as db:
                db.row_factory=sqlite3.Row
                tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                for table,keys in IMMUTABLE_KEYS.items():
                    if table not in tables:continue
                    columns={r[1] for r in db.execute(f'PRAGMA table_info({table})')}
                    if not set(keys)<=columns:raise ValueError('unsupported immutable table identity')
                    for row in db.execute(f'SELECT * FROM {table}'):
                        values=dict(row);key=canonical_json([name,table,*[values[k] for k in keys]])
                        if key in records:raise ValueError('duplicate immutable row identity')
                        records[key]=digest(values)
    return dict(records=records,records_sha256=digest(records),source_version=restored['verification']['source_version'])


def head(directory):
    root=Path(directory);path=root/'HEAD.json'
    if not path.exists():return None
    value=json.loads(path.read_text());p=value['payload'];sha=value['sha256']
    if (digest(p)!=sha or p.get('schema_version')!=1 or p.get('scope')!='LOCAL_STAGING_ONLY'
        or p.get('external_committed') is not False or type(p.get('generation')) is not int or p['generation']<1
        or digest(p['immutable_records'])!=p['records_sha256']):raise ValueError('invalid staged HEAD')
    if (not isinstance(p.get('bundle_sha256'),str) or not re.fullmatch('[0-9a-f]{64}',p['bundle_sha256'])
        or not isinstance(p.get('source_version'),str) or not re.fullmatch('[0-9a-f]{40}',p['source_version'])
        or not isinstance(p.get('immutable_records'),dict)
        or any(not isinstance(k,str) or not isinstance(v,str) or not re.fullmatch('[0-9a-f]{64}',v) for k,v in p['immutable_records'].items())):
        raise ValueError('invalid staged HEAD identities')
    if json.loads((root/'manifests'/(sha+'.json')).read_text())!=value:raise ValueError('HEAD/immutable manifest mismatch')
    key='capsules/'+p['bundle_sha256']+'.tar.gz'
    if p['bundle_key']!=key or file_sha(root/key)!=p['bundle_sha256']:raise ValueError('HEAD capsule missing or corrupt')
    return value


def commit_stage(directory,bundle,expected_sha256,expected_parent):
    """Local CAS simulation. A local file lock is NOT a distributed lock."""
    snapshot=inventory(bundle,expected_sha256)
    if not re.fullmatch('[0-9a-f]{40}',snapshot['source_version']):raise ValueError('exact source commit required')
    root=Path(directory);root.mkdir(parents=True,exist_ok=True,mode=0o700)
    with exclusive(root/'HEAD.json') as acquired:
        if not acquired:raise BlockingIOError('local publication busy')
        previous=head(root);current=previous['sha256'] if previous else None
        if previous and previous['payload']['bundle_sha256']==expected_sha256:return dict(status='ALREADY_STAGED',manifest=previous)
        if expected_parent!=current:raise StateConflict('stale parent; restore latest state before retry')
        old=previous['payload']['immutable_records'] if previous else {}
        if any(snapshot['records'].get(k)!=v for k,v in old.items()):raise StateConflict('immutable history missing or changed')
        keep_capsule(root,bundle,expected_sha256)
        payload=dict(schema_version=1,scope='LOCAL_STAGING_ONLY',external_committed=False,
            generation=previous['payload']['generation']+1 if previous else 1,parent_sha256=current,
            bundle_sha256=expected_sha256,bundle_key='capsules/'+expected_sha256+'.tar.gz',source_version=snapshot['source_version'],created_utc=int(time.time()),
            immutable_records=snapshot['records'],records_sha256=snapshot['records_sha256'])
        value=dict(payload=payload,sha256=digest(payload));manifests=root/'manifests';manifests.mkdir(mode=0o700,exist_ok=True)
        manifest_path=manifests/(value['sha256']+'.json');write_json(manifest_path,value)
        with manifest_path.open('rb') as stream:os.fsync(stream.fileno())
        fd=os.open(manifests,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
        temporary=root/('.HEAD-'+uuid.uuid4().hex+'.json')
        try:
            write_json(temporary,value)
            with temporary.open('rb') as stream:os.fsync(stream.fileno())
            os.replace(temporary,root/'HEAD.json')
            fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY)
            try:os.fsync(fd)
            finally:os.close(fd)
        finally:
            if temporary.exists():temporary.unlink()
    return dict(status='STAGED_LOCALLY',manifest=value)


def scheduler_plan(kind):
    if kind not in ('local_timer','github_actions'):raise ValueError('unknown scheduler')
    risks=(['Host must remain running; local filesystem durability must be verified','Timer is not installed or activated'] if kind=='local_timer' else
           ['Scheduled Actions can be delayed or dropped; no punctuality guarantee','Minimum cron interval is five minutes, equal to the capture grace window',
            'Schedule runs from default branch; new feature-branch cron is not an active service','Hosted runner disks are ephemeral; flock does not coordinate separate machines'])
    return dict(kind=kind,enabled=False,ready_for_unattended_collection=False,punctuality_guaranteed=False,capture_grace_seconds=GRACE,
                recommended_local_poll_seconds=60,risks=risks,
                required=['authorized persistent state target','tested conditional HEAD update / single writer','verified restore in a separate runtime','continuous clock/network availability'])


def readiness(config,kind='local_timer'):
    c=validate_config(config)['collection'];audit=inspect(c['database']);audit.pop('examples',None)
    return dict(status='NOT_READY_FOR_DURABLE_UNATTENDED_COLLECTION',observed_utc=int(time.time()),ledger=audit,
        historical_coverage=read_store(c['research_database']).coverage(),local_command_available=True,
        durable_storage_ready=False,external_target_authorized=False,external_upload_performed=False,cross_cloud_restore_verified=False,
        scheduler=scheduler_plan(kind),local_staging_protocol='IMPLEMENTED_NOT_DISTRIBUTED',production_changed=False)


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    q=sub.add_parser('readiness');q.add_argument('config');q.add_argument('--scheduler',choices=('local_timer','github_actions'),default='local_timer')
    q=sub.add_parser('stage');q.add_argument('config');q.add_argument('directory')
    args=p.parse_args();config=validate_config(json.loads(Path(args.config).read_text()))
    if args.command=='readiness':result=readiness(config,args.scheduler)
    else:
        sha=source_sha();repo=Path(__file__).resolve().parent
        import subprocess
        if subprocess.check_output(['git','show','HEAD:faz36.py'],cwd=repo)!=(repo/'faz36.py').read_bytes():raise ValueError('committed publication protocol required')
        root=Path(args.directory);root.mkdir(parents=True,exist_ok=True,mode=0o700)
        previous=head(root);parent=previous['sha256'] if previous else None
        b=capsule(config,root/('capsule-'+uuid.uuid4().hex+'.tar.gz'),sha)['bundle']
        result=commit_stage(root,b['path'],b['sha256'],parent);result.update(bundle=b,external_upload_performed=False,durable_storage_ready=False)
    print(json.dumps(result,sort_keys=True,allow_nan=False))


if __name__=='__main__':main()

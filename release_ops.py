"""Read-only config inspection and opt-in, bounded SQLite release checkpoints."""
import argparse
from contextlib import closing
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
from uuid import uuid4


def inspect_config(path):
    try:import tomllib
    except ImportError:import tomli as tomllib
    p=Path(path);raw=p.read_bytes();c=tomllib.loads(raw.decode())
    if c.get('app')!='zeynal-bot-core':raise ValueError('WRONG_FLY_APPLICATION')
    mounts=c.get('mounts',[]);mounts=[mounts] if type(mounts) is dict else mounts
    if not any(m.get('destination')=='/data' and m.get('source') for m in mounts):
        raise ValueError('EXISTING_DATA_VOLUME_MOUNT_REQUIRED')
    db=c.get('env',{}).get('PREDICTION_LEDGER_DB','/data/prediction_ledger.sqlite')
    if not db.startswith('/data/') or '..' in Path(db).parts:raise ValueError('PERSISTENT_LEDGER_PATH_REQUIRED')
    commands=list(c.get('processes',{}).values())
    commands.append(' '.join(c.get('experimental',{}).get('cmd',[])))
    if any('dynamic_scheduler' in cmd or '&' in cmd for cmd in commands):raise ValueError('MULTIPLE_POLLING_PROCESSES_REFUSED')
    if str(c.get('env',{}).get('ENABLE_LEGACY_SCHEDULER','0'))!='0':raise ValueError('LEGACY_SCHEDULER_MUST_REMAIN_DISABLED')
    return dict(status='LOCAL_CONFIG_CHECKED_NOT_DEPLOYED',sha256=hashlib.sha256(raw).hexdigest(),
        app=c['app'],mounts=[{k:m.get(k) for k in ('source','destination')} for m in mounts],ledger=db)


def checkpoint(database,output_dir,*,timeout=5,production=False):
    if type(timeout) not in (int,float) or not 0<timeout<=30:raise ValueError('BOUNDED_CHECKPOINT_TIMEOUT_REQUIRED')
    src=Path(database).absolute();root=Path(output_dir).absolute()
    if src.resolve()!=src or root.resolve()!=root or not src.is_file():raise ValueError('SAFE_CHECKPOINT_PATHS_REQUIRED')
    if Path('/data') in src.parents or Path('/data') in root.parents:
        if not production or not os.path.ismount('/data') or Path('/data') not in src.parents or Path('/data') not in root.parents:
            raise ValueError('EXPLICIT_MOUNTED_PRODUCTION_CHECKPOINT_REQUIRED')
    root.mkdir(exist_ok=True)
    deadline=time.monotonic()+timeout;temporary=None;manifest_tmp=None
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:12]
    target=root/('ledger-'+stamp+'.sqlite');manifest=root/('ledger-'+stamp+'.manifest.json')
    def progress(status,remaining,total):
        if time.monotonic()>=deadline:raise TimeoutError('CHECKPOINT_TOTAL_TIMEOUT')
    try:
        with tempfile.NamedTemporaryFile(dir=root,prefix='.checkpoint-',delete=False) as f:temporary=Path(f.name)
        with closing(sqlite3.connect(src.as_uri()+'?mode=ro',uri=True,timeout=min(timeout,.2))) as source:
            with closing(sqlite3.connect(str(temporary))) as dest:
                source.backup(dest,pages=128,progress=progress,sleep=.01)
                if dest.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('CHECKPOINT_INTEGRITY_FAILED')
                tables={r[0] for r in dest.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                counts={name:dest.execute('SELECT COUNT(*) FROM '+name).fetchone()[0] for name in
                    ('predictions','outcomes','prediction_versions','live_analysis_snapshots','verified_analysis_results') if name in tables}
        if time.monotonic()>=deadline:raise TimeoutError('CHECKPOINT_TOTAL_TIMEOUT')
        with temporary.open('rb') as stream:os.fsync(stream.fileno())
        h=hashlib.sha256()
        with temporary.open('rb') as f:
            for chunk in iter(lambda:f.read(262144),b''):
                h.update(chunk)
                if time.monotonic()>=deadline:raise TimeoutError('CHECKPOINT_TOTAL_TIMEOUT')
        pin=h.hexdigest()
        os.link(temporary,target)
        m=dict(format='ZEYNAL_RELEASE_CHECKPOINT_V1',created_at_utc=datetime.now(timezone.utc).isoformat(),
            database=target.name,sha256=pin,sqlite_integrity='ok',counts=counts,source=str(src),
            restore_policy='IMAGE_ROLLBACK_PRESERVES_LIVE_DB_NO_AUTOMATIC_DATABASE_RESTORE')
        with tempfile.NamedTemporaryFile(dir=root,prefix='.manifest-',mode='w',delete=False) as f:
            manifest_tmp=Path(f.name);json.dump(m,f,sort_keys=True);f.flush();os.fsync(f.fileno())
        os.link(manifest_tmp,manifest)
        fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
        return dict(database=str(target),manifest=str(manifest),sha256=pin,counts=counts,source_mutated=False)
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)
        if manifest_tmp is not None:manifest_tmp.unlink(missing_ok=True)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    c=sub.add_parser('inspect');c.add_argument('config')
    b=sub.add_parser('checkpoint');b.add_argument('--database',default='/data/prediction_ledger.sqlite')
    b.add_argument('--output-dir',default='/data/release-backups');b.add_argument('--execute',action='store_true')
    b.add_argument('--production',action='store_true')
    a=p.parse_args(argv)
    try:
        if a.action=='inspect':r=inspect_config(a.config)
        elif not a.execute:r=dict(status='DRY_RUN_DATABASE_NOT_OPENED',database=a.database,output_dir=a.output_dir)
        else:r=checkpoint(a.database,a.output_dir,production=a.production)
        print(json.dumps(r,sort_keys=True));return 0
    except (ValueError,OSError,sqlite3.Error,ImportError) as exc:
        print(json.dumps(dict(status='RELEASE_CHECK_NOT_CONFIRMED',reason=str(exc))));return 2


if __name__=='__main__':raise SystemExit(main())

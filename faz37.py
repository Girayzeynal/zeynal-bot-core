"""Clock discontinuity guard and pinned local recovery; no external storage writes."""
import argparse
import asyncio
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import sqlite3
from contextlib import closing

from faz25 import exclusive
from faz32 import read_store
from faz32_collect import write_json
from faz33 import Runner
from faz35 import pilot,validate_config,source_sha,restore_pilot
from faz36 import head,inventory,file_sha,StateConflict
from prediction_inputs import digest
from prospective_cuts import CutLedger
from providers.espn_adapter import ESPNAdapter


class ClockDiscontinuity(ValueError):pass


class ClockGuard:
    def __init__(self,*,wall=None,monotonic=None,max_drift_seconds=2):
        if type(max_drift_seconds) not in (int,float) or not math.isfinite(max_drift_seconds) or max_drift_seconds<=0:raise ValueError('positive finite drift tolerance required')
        self.wall=wall or time.time;self.monotonic=monotonic or time.monotonic;self.tolerance=max_drift_seconds
        self.start_wall=self.wall();self.start_mono=self.monotonic();self.last_wall=self.start_wall;self.last_mono=self.start_mono
        if not math.isfinite(self.start_wall) or not math.isfinite(self.start_mono) or self.start_wall<=0:raise ClockDiscontinuity('invalid initial clock sample')
        self.check()

    def check(self):
        wall=self.wall();mono=self.monotonic()
        if (not math.isfinite(wall) or not math.isfinite(mono) or wall<=0 or mono<self.last_mono
            or wall+.001<self.last_wall or abs((wall-self.start_wall)-(mono-self.start_mono))>self.tolerance):
            raise ClockDiscontinuity('CLOCK_DISCONTINUITY: UTC timeline is untrusted; no prospective insert')
        self.last_wall=wall;self.last_mono=mono
        return int(wall)

    def evidence(self):
        return dict(host_wall_anchor_utc=self.start_wall,monotonic_anchor=self.start_mono,last_wall_utc=self.last_wall,
            max_drift_seconds=self.tolerance,initial_utc_independently_attested=False,policy='Reject wall/monotonic divergence and backwards wall time')


class GuardedRunner(Runner):
    def __init__(self,*args,clock_guard,**kwargs):
        super().__init__(*args,**kwargs);self.clock_guard=clock_guard
    def check_source(self):
        self.clock_guard.check();return super().check_source()
    async def fetch(self,url):
        self.clock_guard.check()
        try:return await super().fetch(url)
        finally:self.clock_guard.check()


def pinned_lineage(directory,expected_head_sha256):
    if not isinstance(expected_head_sha256,str) or not re.fullmatch('[0-9a-f]{64}',expected_head_sha256):raise ValueError('trusted external HEAD SHA-256 required')
    root=Path(directory);latest=head(root)
    if latest is None or latest['sha256']!=expected_head_sha256:raise StateConflict('HEAD does not match the trusted latest checkpoint')
    current=latest;seen=set();child=None;count=0
    while current:
        p=current['payload'];sha=current['sha256']
        if sha in seen or digest(p)!=sha or p['scope']!='LOCAL_STAGING_ONLY' or p['external_committed'] is not False:raise ValueError('invalid checkpoint lineage')
        if (type(p['generation']) is not int or p['generation']<1 or not isinstance(p['immutable_records'],dict)
            or digest(p['immutable_records'])!=p['records_sha256']):raise ValueError('invalid checkpoint generation/inventory')
        if child and (child['generation']!=p['generation']+1 or any(child['immutable_records'].get(k)!=v for k,v in p['immutable_records'].items())):
            raise StateConflict('checkpoint lineage lost or changed immutable history')
        seen.add(sha);count+=1;parent=p['parent_sha256']
        if p['generation']==1:
            if parent is not None:raise ValueError('initial checkpoint must not have parent')
            break
        if not isinstance(parent,str) or not re.fullmatch('[0-9a-f]{64}',parent):raise ValueError('missing/invalid checkpoint parent')
        child=p;current=json.loads((root/'manifests'/(parent+'.json')).read_text())
        if current['sha256']!=parent:raise ValueError('parent filename/digest mismatch')
    return dict(head=latest,verified_generations=count)


def restore_state(directory,destination,expected_head_sha256):
    root=Path(directory)
    with exclusive(root/'HEAD.json') as acquired:
        if not acquired:raise BlockingIOError('publication is busy')
        lineage=pinned_lineage(root,expected_head_sha256);p=lineage['head']['payload'];bundle=root/p['bundle_key']
        snapshot=inventory(bundle,p['bundle_sha256'])
        if snapshot['records']!=p['immutable_records'] or snapshot['source_version']!=p['source_version']:raise ValueError('checkpoint/capsule inventory mismatch')
        restored=restore_pilot(bundle,destination,p['bundle_sha256'])
        manifest=json.loads((Path(destination)/'manifest.json').read_text());databases=[]
        for name,sha in manifest['files'].items():
            path=(Path(destination)/name).resolve()
            if file_sha(path)!=sha:raise ValueError('restored database checksum mismatch')
            with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
                if db.execute('PRAGMA integrity_check').fetchone()!=('ok',):raise ValueError('restored SQLite integrity failure')
            databases.append(dict(name=name,sha256=sha,integrity='ok'))
        if head(root)['sha256']!=expected_head_sha256:raise StateConflict('HEAD changed during restore')
        proof=dict(status='PINNED_LOCAL_STATE_RESTORED',trusted_head_sha256=expected_head_sha256,generation=p['generation'],bundle_sha256=p['bundle_sha256'],source_version=p['source_version'],
            verified_generations=lineage['verified_generations'],restored_databases=databases,config_path=restored['config_path'],external_committed=False,new_cloud_runtime_tested=False)
        marker=Path(destination)/'FAZ37_VERIFIED_STATE.json';write_json(marker,proof)
        with marker.open('rb') as stream:os.fsync(stream.fileno())
        return proof


def recovery_child(directory,expected_head_sha256):
    repo=Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix='faz37-isolated-') as folder:
        root=Path(folder);source=root/'source';source.mkdir()
        for parent,children,names in os.walk(repo):
            children[:]=[c for c in children if not c.startswith('.') and c!='__pycache__']
            for name in names:
                file=Path(parent)/name
                if file.suffix!='.py' or file.is_symlink():continue
                target=source/file.relative_to(repo);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(file,target)
        policy='docs/evidence/faz33-official-season-20261105.json';(source/policy).parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(repo/policy,source/policy)
        code="import sys,json;sys.path.insert(0,sys.argv[1]);import faz37;r=faz37.restore_state(sys.argv[2],sys.argv[3],sys.argv[4]);r['implementation_path']=faz37.__file__;print(json.dumps(r,sort_keys=True))"
        proc=subprocess.run([sys.executable,'-I','-c',code,str(source),str(Path(directory).resolve()),str(root/'restored'),expected_head_sha256],cwd=source,check=True,capture_output=True,text=True,timeout=120)
        report=json.loads(proc.stdout)
        if not Path(report['implementation_path']).is_relative_to(source):raise ValueError('original workspace module used during isolated recovery')
        return dict(status='ISOLATED_PROCESS_RECOVERY_VERIFIED',proof=report,new_process=True,new_source_directory=True,new_cloud_runtime_tested=False,external_upload_performed=False)


async def guarded_pilot(config):
    c=validate_config(config)['collection'];sha=source_sha();guard=ClockGuard();api=ESPNAdapter()
    try:
        def factory():return GuardedRunner(CutLedger(c['database'],clock_check=guard.check),read_store(c['research_database']),api,model_sha=sha,verify_source=True,clock_guard=guard)
        result=await pilot(c['database'],factory,journal_path=Path(c['state_directory'])/'operations.sqlite',checkpoint_dir=Path(c['state_directory'])/'checkpoints')
        result['clock_guard']=guard.evidence();result['clock_check_utc']=guard.check()
        # Persist target decision as an operational event, never a forecast.
        plan=result.get('planning',{}).get('tick',{}).get('plan',[])
        target=next((r for r in plan if r['fixture']['provider_fixture_id']=='401909936' and r['horizon']=='T6H'),None)
        if target:
            with exclusive(c['database']) as acquired:
                if acquired:
                    from faz34 import RunJournal
                    journal=RunJournal(Path(c['state_directory'])/'operations.sqlite');past=[p for p in journal.events() if p['event']=='FAZ37_TARGET_CUT_STATUS']
                    details=dict(target,collector_sha=sha,kind='OPERATION_STATUS_NOT_PREDICTION')
                    if not past or past[-1]['details']!=details:
                        guard.check();journal.append('FAZ37-TARGET-401909936-T6H','FAZ37_TARGET_CUT_STATUS',details)
            result['target_cut']=target
        return result
    except ClockDiscontinuity as exc:
        return dict(status='CLOCK_DISCONTINUITY',error=str(exc),clock_guard=guard.evidence(),utc_timeline='UNTRUSTED',
                    new_prospective_cuts=None,required_action='Audit stored records before retry; never retime existing forecasts')
    finally:await api.aclose()


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    q=sub.add_parser('pilot');q.add_argument('config')
    q=sub.add_parser('restore-state');q.add_argument('directory');q.add_argument('destination');q.add_argument('--expected-head-sha256',required=True)
    q=sub.add_parser('verify-recovery-child');q.add_argument('directory');q.add_argument('--expected-head-sha256',required=True)
    args=p.parse_args()
    if args.command=='pilot':result=asyncio.run(guarded_pilot(json.loads(Path(args.config).read_text())))
    elif args.command=='restore-state':result=restore_state(args.directory,args.destination,args.expected_head_sha256)
    else:result=recovery_child(args.directory,args.expected_head_sha256)
    print(json.dumps(result,sort_keys=True,allow_nan=False))
    return 0 if result['status'] in ('WAITING_FOR_CUT','NO_PENDING_CUTS','TICK_COMPLETE','PROVIDER_COOLDOWN','BUSY','PINNED_LOCAL_STATE_RESTORED','ISOLATED_PROCESS_RECOVERY_VERIFIED') else 1


if __name__=='__main__':raise SystemExit(main())

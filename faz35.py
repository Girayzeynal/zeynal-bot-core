"""Development pilot: plan first, collect due cuts only, never upload data."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import time

from faz25 import exclusive
from faz32 import read_store
from faz32_collect import write_json
from faz33 import Runner
from faz34 import run_once,RunJournal
from prediction_inputs import digest
from prospective_cuts import CutLedger,inspect
from providers.espn_adapter import ESPNAdapter
from research_recovery import make_bundle,verify_bundle,restore_bundle

PROVIDER_ERRORS={'HTTP_403','HTTP_429','TIMEOUT','NETWORK_UNAVAILABLE','NETWORK_OR_PROVIDER_UNAVAILABLE'}


def validate_config(config):
    if set(config)!={'schema_version','collection','storage'} or type(config['schema_version']) is not int or config['schema_version']!=1:
        raise ValueError('unsupported pilot configuration')
    storage=config['storage']
    if set(storage)!={'mode','external_target','upload_enabled'} or storage['mode']!='LOCAL_ONLY' or storage['external_target'] is not None or storage['upload_enabled'] is not False:
        raise ValueError('no authorized external target/transfer is implemented; use LOCAL_ONLY')
    c=config['collection']
    if set(c)!={'database','research_database','state_directory','legacy_databases'}:raise ValueError('unsupported collection fields')
    for key in ('database','research_database','state_directory'):
        if not isinstance(c[key],str) or not Path(c[key]).is_absolute():raise ValueError('explicit absolute local paths required')
    if not isinstance(c['legacy_databases'],dict):raise ValueError('legacy database map required')
    paths=[Path(c['database']).resolve(),Path(c['research_database']).resolve(),(Path(c['state_directory'])/'operations.sqlite').resolve()]
    for name,path in c['legacy_databases'].items():
        if (not isinstance(name,str) or Path(name).name!=name or not name.startswith('legacy-') or not name.endswith('.sqlite')
            or not isinstance(path,str) or not Path(path).is_absolute()):raise ValueError('safe legacy basename/absolute path required')
        paths.append(Path(path).resolve())
    if len(set(paths))!=len(paths):raise ValueError('database paths must be distinct')
    return config


def source_sha():
    repo=Path(__file__).resolve().parent
    sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
    for name in ('faz35.py','faz34.py','faz33.py','prospective_cuts.py','research_recovery.py'):
        raw=subprocess.check_output(['git','show','HEAD:'+name],cwd=repo)
        if raw!=(repo/name).read_bytes():raise ValueError('clean committed pilot implementation required')
    check=object.__new__(Runner);check.model_sha=sha;check.verify_source=True;check.check_source()
    return sha


def operational_state(database,factory,journal_path,retry=None):
    with exclusive(database) as acquired:
        if not acquired:return dict(status='BUSY',recovered_run_ids=[])
        runner=factory()
        if retry:
            status,until=retry
            runner.ledger.log(status,details=dict(retry_after_utc=until,phase='FAZ35_PLAN',collector_sha=runner.model_sha))
        recovered=RunJournal(journal_path).recover() if Path(journal_path).exists() else []
        return dict(status='CHECKED',recovered_run_ids=recovered)


async def pilot(database,factory,*,journal_path,checkpoint_dir):
    planning=await run_once(database,factory,journal_path=journal_path,checkpoint_dir=checkpoint_dir,dry_run=True)
    tick=planning.get('tick',{});plan=tick.get('plan',[])
    due=[p for p in plan if p['status']=='DUE']
    retry=None
    if planning['status'] in PROVIDER_ERRORS:
        until=max(int(time.time())+60,tick.get('retry_after_utc',0));retry=(planning['status'],until)
    state=dict(status='NOT_CHECKED',recovered_run_ids=[])
    if planning['status'] not in ('BUSY','SQLITE_BUSY','RUN_FAILED'):
        try:state=operational_state(database,factory,journal_path,retry)
        except (sqlite3.Error,OSError,ValueError) as exc:
            return dict(status='STATE_CHECK_FAILED',collection_executed=False,new_prospective_cuts=0,error_type=type(exc).__name__,planning=planning)
    base=dict(planning=planning,state_check=state,planned_due_cuts=due,observed_utc=int(time.time()),collection_executed=False,
        ledger_mode=planning.get('mode'),new_prospective_cuts=0,new_cut_proofs=[],external_storage='NOT_AUTHORIZED_NOT_CONFIGURED',external_upload_performed=False,cross_cloud_restore='NOT_VERIFIED')
    if planning['status']!='DRY_RUN':
        return dict(base,status=planning['status'],new_prospective_cuts=planning.get('new_prospective_cuts'),retry_after_utc=retry[1] if retry else None)
    if not due:
        return dict(base,status='WAITING_FOR_CUT' if planning.get('next_cut_utc') else 'NO_PENDING_CUTS',next_cut_utc=planning.get('next_cut_utc'))
    # Re-discover under FAZ34's exclusive lock: a plan is never permission to backdate.
    collection=await run_once(database,factory,journal_path=journal_path,checkpoint_dir=checkpoint_dir)
    return dict(base,status=collection['status'],collection=collection,collection_executed=True,
        new_prospective_cuts=collection.get('new_prospective_cuts'),
        new_cut_proofs=collection.get('new_cut_proofs',[]) if collection.get('mode')=='PROSPECTIVE' else [],
        synthetic_cut_proofs=collection.get('new_cut_proofs',[]) if collection.get('mode')=='SYNTHETIC_TEST' else [])


def capsule(config,destination,sha):
    c=validate_config(config)['collection']
    with exclusive(c['database']) as acquired:
        if not acquired:raise RuntimeError('pilot database busy')
        inspect(c['database']);read_store(c['research_database']).coverage()
        databases={'prospective.sqlite':c['database'],'history.sqlite':c['research_database'],**c['legacy_databases']}
        journal=Path(c['state_directory'])/'operations.sqlite'
        if journal.exists():RunJournal(journal).events();databases['operations.sqlite']=str(journal)
        info=make_bundle(databases,destination,sha);verified=verify_bundle(info['path'])
    return dict(status='LOCAL_CAPSULE_VERIFIED',bundle=info,verification=verified,external_upload_performed=False,cross_cloud_restore='NOT_VERIFIED')


def restore_pilot(bundle,destination,expected_sha256):
    raw=Path(bundle).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected_sha256:raise ValueError('external backup checksum mismatch')
    checked=verify_bundle(bundle);names={r['name'] for r in checked['files']}
    if not {'prospective.sqlite','history.sqlite'}<=names:raise ValueError('not a complete pilot capsule')
    if any(n not in ('prospective.sqlite','history.sqlite','operations.sqlite') and not n.startswith('legacy-') for n in names):raise ValueError('unsupported pilot capsule database')
    restored=restore_bundle(bundle,destination,expected_sha256);root=Path(destination).resolve()
    config=dict(schema_version=1,collection=dict(database=str(root/'prospective.sqlite'),research_database=str(root/'history.sqlite'),state_directory=str(root),
        legacy_databases={n:str(root/n) for n in names if n.startswith('legacy-')}),storage=dict(mode='LOCAL_ONLY',external_target=None,upload_enabled=False))
    validate_config(config);path=root/'pilot-config.json';write_json(path,config)
    return dict(status='PILOT_RESTORED_LOCALLY',restore=restored,config_path=str(path),external_storage='NOT_AUTHORIZED_NOT_CONFIGURED',cross_cloud_restore='NOT_VERIFIED')


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    q=sub.add_parser('pilot');q.add_argument('config')
    q=sub.add_parser('capsule');q.add_argument('config');q.add_argument('destination')
    q=sub.add_parser('restore-pilot');q.add_argument('bundle');q.add_argument('destination');q.add_argument('--sha256',required=True)
    args=p.parse_args()
    if args.command=='restore-pilot':result=restore_pilot(args.bundle,args.destination,args.sha256)
    else:
        config=validate_config(json.loads(Path(args.config).read_text()));c=config['collection'];sha=source_sha()
        if args.command=='capsule':result=capsule(config,args.destination,sha)
        else:
            async def run():
                api=ESPNAdapter()
                try:
                    def factory():return Runner(CutLedger(c['database']),read_store(c['research_database']),api,model_sha=sha,verify_source=True)
                    return await pilot(c['database'],factory,journal_path=Path(c['state_directory'])/'operations.sqlite',checkpoint_dir=Path(c['state_directory'])/'checkpoints')
                finally:await api.aclose()
            result=asyncio.run(run())
    print(json.dumps(result,sort_keys=True,allow_nan=False))
    return 0 if result['status'] in ('WAITING_FOR_CUT','NO_PENDING_CUTS','TICK_COMPLETE','PROVIDER_COOLDOWN','BUSY','LOCAL_CAPSULE_VERIFIED','PILOT_RESTORED_LOCALLY') else 1


if __name__=='__main__':raise SystemExit(main())

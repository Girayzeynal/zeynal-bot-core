"""One-shot development scheduler with crash journal and verified local checkpoints."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time
import uuid

from faz25 import exclusive
from faz33 import Runner
from faz32 import read_store
from prediction_inputs import canonical_json,digest
from prospective_cuts import CutLedger,inspect
from providers.espn_adapter import ESPNAdapter
from research_recovery import make_bundle,verify_bundle


class RunJournal:
    def __init__(self,path):
        self.path=str(path)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS faz34_events (seq INTEGER PRIMARY KEY,payload TEXT,sha256 TEXT)')
            for op in ('UPDATE','DELETE'):
                db.execute(f"CREATE TRIGGER IF NOT EXISTS faz34_events_no_{op} BEFORE {op} ON faz34_events BEGIN SELECT RAISE(ABORT,'immutable operation event'); END")
            db.execute("CREATE TRIGGER IF NOT EXISTS faz34_events_no_replace BEFORE INSERT ON faz34_events WHEN EXISTS (SELECT 1 FROM faz34_events WHERE seq=NEW.seq) BEGIN SELECT RAISE(ABORT,'immutable operation event'); END")
        os.chmod(self.path,0o600)

    def connect(self):return sqlite3.connect(self.path,timeout=1)

    def events(self):
        with self.connect() as db:rows=db.execute('SELECT seq,payload,sha256 FROM faz34_events ORDER BY seq').fetchall()
        previous=None;result=[]
        for seq,raw,sha in rows:
            p=json.loads(raw)
            if digest(p)!=sha or p['previous_sha256']!=previous or p['seq']!=seq:raise ValueError('operation journal hash/sequence mismatch')
            previous=sha;result.append(p)
        return result

    def append(self,run_id,event,details=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            prior=db.execute('SELECT seq,sha256 FROM faz34_events ORDER BY seq DESC LIMIT 1').fetchone()
            p=dict(seq=(prior[0]+1 if prior else 1),run_id=run_id,event=event,observed_utc=int(time.time()),previous_sha256=prior[1] if prior else None,details=details or {})
            db.execute('INSERT INTO faz34_events VALUES (?,?,?)',(p['seq'],canonical_json(p),digest(p)))
        return p

    def recover(self):
        # The caller owns the application lock: no earlier owner is still running.
        opened=set()
        for p in self.events():
            if p['event']=='STARTED':opened.add(p['run_id'])
            elif p['event'] in ('FINISHED','INTERRUPTED'):opened.discard(p['run_id'])
        for run_id in sorted(opened):self.append(run_id,'INTERRUPTED',dict(reason='exclusive lock reacquired after incomplete run'))
        return sorted(opened)


def cut_proofs(path):
    with sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,timeout=1) as db:
        rows=db.execute('SELECT fixture_id,horizon,cutoff_utc,recorded_utc,payload,sha256 FROM faz33_cuts ORDER BY fixture_id,horizon').fetchall()
    result={}
    for fixture,horizon,cutoff,recorded,raw,sha in rows:
        p=json.loads(raw)
        if digest(p)!=sha:raise ValueError('cut digest mismatch')
        result[fixture+':'+horizon]=dict(fixture_id=fixture,horizon=horizon,cutoff_utc=cutoff,recorded_utc=recorded,prediction_sha256=sha,
            start_utc=p['fixture']['start_ts_utc'],model_sha=p['model_sha'],shadow_status=p['shadow']['status'],feature_status=p['features']['payload']['status'],source_games=len(p['features']['payload']['source_records']))
    return result


async def run_once(database,runner_factory,*,journal_path,checkpoint_dir,dry_run=False,timeout_seconds=120):
    if type(timeout_seconds) not in (int,float) or not 0<timeout_seconds<=300:raise ValueError('one-shot timeout must be within 300 seconds')
    database=Path(database)
    with exclusive(database) as acquired:
        if not acquired:return dict(status='BUSY',new_prospective_cuts=0,checkpoint=None)
        journal=None;run_id=uuid.uuid4().hex;before={};result={}
        try:
            runner=runner_factory()
            paths=[database.resolve(),Path(runner.store.path).resolve(),Path(journal_path).resolve()]
            if len(set(paths))!=3:raise ValueError('cut/history/operations paths must be distinct')
            before=cut_proofs(database)
            inspected=inspect(database);inspected.pop('examples',None)
            if not dry_run:
                journal=RunJournal(journal_path);recovered=journal.recover()
                journal.append(run_id,'STARTED',dict(model_sha=runner.model_sha,mode=runner.ledger.mode,before_sha256=digest(before),recovered_run_ids=recovered))
            else:recovered=[]
            try:tick=await asyncio.wait_for(runner._tick_locked(dry_run=dry_run),timeout=timeout_seconds)
            except asyncio.TimeoutError:tick=dict(status='RUN_TIMEOUT',actions=[])
            after=cut_proofs(database)
            if any(after.get(key)!=value for key,value in before.items()):raise ValueError('original prospective record changed')
            audited=inspect(database);audited.pop('examples',None)
            new=[v for k,v in after.items() if k not in before]
            future=[p['scheduled_cutoff_utc'] for p in tick.get('plan',[]) if p['status']=='NOT_DUE']
            result=dict(status=tick['status'],run_id=run_id,model_sha=runner.model_sha,mode=runner.ledger.mode,dry_run=dry_run,
                new_prospective_cuts=len(new) if runner.ledger.mode=='PROSPECTIVE' else 0,new_synthetic_cuts=len(new) if runner.ledger.mode=='SYNTHETIC_TEST' else 0,
                new_cut_proofs=new,original_cuts_unchanged=True,audit=audited,tick=tick,recovered_run_ids=recovered,
                next_cut_utc=min(future) if future else None,checkpoint=None,
                external_persistence='NOT_CONFIGURED',cross_codex_cloud_restore='NOT_VERIFIED')
            if journal:
                journal.append(run_id,'FINISHED',dict(status=result['status'],after_sha256=digest(after),new_cut_proofs=new))
                folder=Path(checkpoint_dir);folder.mkdir(parents=True,exist_ok=True,mode=0o700)
                try:
                    checkpoint=make_bundle({'prospective.sqlite':str(database),'history.sqlite':runner.store.path,'operations.sqlite':str(journal_path)},folder/(run_id+'.tar.gz'),runner.model_sha)
                    verified=verify_bundle(checkpoint['path'])
                    result['checkpoint']=dict(checkpoint,verification=verified,status='LOCAL_RESTORE_VERIFIED')
                    journal.append(run_id,'CHECKPOINT_VERIFIED',dict(path=checkpoint['path'],sha256=checkpoint['sha256']))
                except (OSError,ValueError,sqlite3.Error) as exc:
                    result['checkpoint']=dict(status='CHECKPOINT_FAILED',error_type=type(exc).__name__)
                    result['status']='CHECKPOINT_FAILED';journal.append(run_id,'CHECKPOINT_FAILED',dict(error_type=type(exc).__name__))
            return result
        except (OSError,ValueError,sqlite3.Error) as exc:
            code=getattr(exc,'sqlite_errorcode',None)
            status='SQLITE_BUSY' if code in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED) else 'RUN_FAILED'
            if journal:
                try:journal.append(run_id,'FINISHED',dict(status=status,error_type=type(exc).__name__))
                except sqlite3.Error:pass
            return dict(status=status,run_id=run_id,error_type=type(exc).__name__,error=str(exc),checkpoint=None,
                new_prospective_cuts=None,reason='Do not infer no writes from failure; reopen and audit before retry',cross_codex_cloud_restore='NOT_VERIFIED')


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    q=sub.add_parser('run-once');q.add_argument('database');q.add_argument('research_database');q.add_argument('state_directory');q.add_argument('--dry-run',action='store_true');q.add_argument('--shadow-model')
    q=sub.add_parser('restore');q.add_argument('bundle');q.add_argument('destination');q.add_argument('--expected-sha256',required=True)
    args=p.parse_args()
    if args.command=='restore':
        from research_recovery import restore_bundle
        result=restore_bundle(args.bundle,args.destination,args.expected_sha256)
    else:
        repo=Path(__file__).resolve().parent;sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
        state=Path(args.state_directory);state.mkdir(mode=0o700,parents=True,exist_ok=True)
        async def run():
            api=ESPNAdapter()
            try:
                def factory():return Runner(CutLedger(args.database),read_store(args.research_database),api,model_sha=sha,
                    artifact=json.loads(Path(args.shadow_model).read_text()) if args.shadow_model else None,verify_source=True)
                return await run_once(args.database,factory,journal_path=state/'operations.sqlite',checkpoint_dir=state/'checkpoints',dry_run=args.dry_run)
            finally:await api.aclose()
        result=asyncio.run(run())
    print(json.dumps(result,sort_keys=True,allow_nan=False))
    return 0 if result['status'] in ('TICK_COMPLETE','DRY_RUN','BUSY','PROVIDER_COOLDOWN','RESTORE_COMPLETE') else 1


if __name__=='__main__':raise SystemExit(main())

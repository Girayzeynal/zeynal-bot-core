"""Local latency/restart experiment using ONLY disposable SYNTHETIC_TEST data.

Git and elapsed timings use this real runtime. UTC, CI and match fixtures in the
experiment are synthetic, not external attestations or prospective predictions.
"""
import argparse
import asyncio
import json
from pathlib import Path
import subprocess
import sys

from faz39 import (local_source, CaptureGate, EvidenceLedger, ArmedRunner,
                   capture_armed, GITHUB, require)
from faz34 import cut_proofs
from faz37 import ClockGuard
from faz39_recovery import snapshot
from prediction_inputs import digest
from tests import test_faz39 as synthetic


async def probe(destination, samples=128):
    require(type(samples) is int and 100 <= samples <= 512, 'PROBE_SAMPLE_COUNT_100_TO_512')
    source = local_source()
    root = Path(destination); root.mkdir(mode=0o700, parents=False, exist_ok=False)
    fixture = synthetic.ReadinessTests(); await fixture.asyncSetUp()
    try:
        fx, p = fixture.fx, fixture.p
        p['source'] = source
        for name, update in (
            ('ref', lambda d:d['object'].update(sha=source['sha'])),
            ('runs', lambda d:d['workflow_runs'][0].update(head_sha=source['sha'], head_branch=source['branch'])),
            ('jobs', lambda d:[j.update(head_sha=source['sha']) for j in d['jobs']])):
            synthetic.replace_json(p, name, update)
        for name, url in (('ref', GITHUB+'/git/ref/heads/'+source['branch']),
                          ('runs', GITHUB+'/actions/runs?head_sha='+source['sha']+'&per_page=100')):
            old=p['proofs'][name]
            p['proofs'][name]=synthetic.proof(old['body'],url,old['observed_utc'])
        p.update(schema_version=2,ledger_id=fixture.store.ledger_id,
                 config_sha256=fixture.store.config_hash(fixture.config()),
                 original_config_sha256=digest(fixture.config()))
        fixture.store.put(p)
        guard=ClockGuard(wall=fx.clock.time,monotonic=lambda:fx.clock.now+100000)
        gate=CaptureGate(p,digest(p),synthetic.utc_proof(fx.clock.now),clock_guard=guard)
        ledger=EvidenceLedger(fx.ledger.path,'SYNTHETIC_TEST',gate)
        fx.clock.now=synthetic.fixtures.BASE+3
        timings=gate.timings
        for _ in range(samples):
            with timings.measure('git_source_standalone'):
                require(local_source()==source,'PROBE_SOURCE_CHANGED')
            with timings.measure('cut_proofs_empty'):cut_proofs(ledger.path)
            with timings.measure('ledger_has_empty'):ledger.has('900000020','T24H')
            with ledger.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                # Exercise the registered SQLite final gate without inserting a row.
                db.execute('SELECT faz39_final_gate(?)',(int(fx.clock.now),)).fetchone()
                db.rollback()
        result=await capture_armed(ArmedRunner(ledger,gate))
        require(result['status']=='RECORDED' and result['new_prospective_cuts']==0,
                'SYNTHETIC_PROBE_CAPTURE_FAILED')
        bundle=snapshot(ledger.path,root/'synthetic-recovery.tar.gz',source['sha'])['bundle']
        code="import sys,json;sys.path.insert(0,sys.argv[1]);from faz39_recovery import restore;print(json.dumps(restore(sys.argv[2],sys.argv[3],sys.argv[4])))"
        child=subprocess.run([sys.executable,'-I','-c',code,str(Path(__file__).resolve().parent),
            bundle['path'],str(root/'restored-in-new-process'),bundle['sha256']],
            check=True,capture_output=True,text=True,timeout=30)
        recovery=json.loads(child.stdout)
        require(recovery['audit']['prospective_cuts']==0 and recovery['audit']['synthetic_cuts']==1,
                'SYNTHETIC_PROBE_MODE_CHANGED')
        report=dict(scope='CURRENT_CLOUD_RUNTIME_ONLY_SYNTHETIC_CLOCK_AND_DATA',source=source,
            samples=samples,quantiles='nearest rank; descriptive, not an SLA or tail guarantee',
            timings=timings.summary(),capture=result,bundle=bundle,recovery=recovery,
            separate_cloud_runtime_verified=False,new_real_prospective_records=0,
            network_calls=0,external_upload_performed=False,new_python_process=True)
        (root/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        return report
    finally:
        # This helper case was not run by unittest's asynchronous runner.
        while fixture._cleanups:
            function,args,kwargs=fixture._cleanups.pop()
            function(*args,**kwargs)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination');parser.add_argument('--samples',type=int,default=128)
    args=parser.parse_args()
    report=asyncio.run(probe(args.destination,args.samples))
    print(json.dumps({k:v for k,v in report.items() if k not in ('capture','recovery')},sort_keys=True))


if __name__=='__main__':main()

"""Read-only shadow readiness report and explicit offline training command."""
import argparse
import json
from pathlib import Path
import subprocess
import hashlib
from prospective_error_audit import audit,read_only_ledger
from shadow_ridge import train,walk_forward


def inspect(period_file,ledgers):
    data=json.loads(Path(period_file).read_text())
    records=data['period_feature_layer']['records'] if isinstance(data,dict) else data
    baseline=[];reference_count=0;examples=[]
    for path in ledgers:
        verified=audit([path]);baseline+=verified['cohorts']
        ledger=read_only_ledger(path)
        with ledger._connect() as db:
            bundles=db.execute('SELECT fixture_id,payload FROM faz24_stages').fetchall()
            period_table=db.execute("SELECT 1 FROM sqlite_master WHERE name='period_result_evidence'").fetchone()
            for fixture,raw in bundles:
                bundle=json.loads(raw);attempt=bundle.get('shadow_pair')
                if not attempt:continue
                from prediction_inputs import digest
                if digest(attempt['payload'])!=attempt['sha256']:raise ValueError('shadow archive corruption')
                features=attempt['payload'].get('features')
                if not features or features['payload']['status']!='READY' or not period_table:continue
                period=db.execute('SELECT payload,sha256 FROM period_result_evidence WHERE fixture_id=?',(fixture,)).fetchone()
                if not period:continue
                payload=json.loads(period[0])
                if digest(payload)!=period[1]:raise ValueError('period archive corruption')
                final=ledger.load_outcome_evidence('NBA',fixture)
                if final is None or final['sha256']!=payload['final_sha256']:raise ValueError('period final binding missing')
                label=dict(summary=payload['summary'],observed_utc=max(payload['recorded_utc'],payload['source_observed_utc']))
                example=dict(features=features,label=label,label_sha256=digest(label))
                from shadow_ridge import validate_example
                validate_example(example);examples.append(example)
        reference_count+=len(bundles)
    from period_feature_layer import export_observations
    available=export_observations(records)
    version=subprocess.check_output(['git','rev-parse','HEAD'],cwd=Path(__file__).resolve().parent,text=True).strip()
    # Archives hold reference inputs, not historical FAZ31-created feature envelopes.
    gate=train(examples,version) if len(examples)<100 else dict(status='READY_FOR_EXPLICIT_OFFLINE_TRAINING',examples=len(examples))
    return dict(status='NOT_TRAINED',training_gate=gate,reference_prematch_records=reference_count,
        archived_period_games=len(available),valid_original_shadow_feature_label_examples=len(examples),
        missing=['100 time-stamped FAZ31 feature-label examples','60/20/20 purged chronological partitions',
                 'pre-tipoff opponent/home-away feature coverage','verified optional injuries/rosters/market'],
        baseline_cohorts=baseline,shadow_metrics=None,paired_real_games=0,
        historical_walk_forward=walk_forward([],version) if len(examples)<100 else dict(status='EXPLICIT_OFFLINE_EVALUATION_REQUIRED'),
        exportable_examples=examples,
        coefficients_changed=False,production_promoted=False,
        reason='Do not retroactively create shadow features at the old reference prediction times')


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    q=sub.add_parser('inspect');q.add_argument('period_file');q.add_argument('ledgers',nargs='+')
    q=sub.add_parser('train');q.add_argument('examples_file');q.add_argument('output_artifact')
    args=p.parse_args(argv)
    if args.command=='inspect':result=inspect(args.period_file,args.ledgers)
    else:
        repo=Path(__file__).resolve().parent
        if subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=repo,text=True):raise ValueError('clean source checkout required')
        version=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
        result=train(json.loads(Path(args.examples_file).read_text()),version)
        if result['status']=='TRAINED_EXPERIMENTAL':
            with open(args.output_artifact,'x') as f:json.dump(result['artifact'],f,sort_keys=True,allow_nan=False)
    print(json.dumps(result,sort_keys=True,allow_nan=False));return 0


if __name__=='__main__':raise SystemExit(main())

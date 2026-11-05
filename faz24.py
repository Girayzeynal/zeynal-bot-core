"""Opt-in prospective NBA stage collection. Never backfill or deploy a scheduler."""
import argparse
import asyncio
from copy import deepcopy
from dataclasses import asdict
import json
import re
import time

from prediction_inputs import canonical_json, digest
from prediction_ledger import PredictionLedger
from nba_prematch_orchestrator import persist_resolved_nba_prematch


def capture_stage(core, stage):
    payload=asdict(core)
    payload['meta'].pop('input_snapshot', None)
    return dict(stage=stage, captured_at_utc=int(time.time()), output=payload)


def build_bundle(cores, model_version, multilayer_config=None, shadow_config=None):
    if not isinstance(model_version,str) or not re.fullmatch(r'[0-9a-f]{40}',model_version):
        raise ValueError('exact source commit SHA required')
    if len(cores) != 3:
        raise ValueError('three stage outputs required')
    snapshot=cores[0].meta['input_snapshot']
    rows=[r for team in snapshot['payload']['teams'].values() for r in team['records']]
    observations=[r['pace_evidence']['snapshot']['observed_at_utc'] for r in rows if r.get('pace_evidence')]
    bundle = dict(schema_version=1, model_version=model_version,
                input_sha256=snapshot['sha256'], generated_at=cores[0].meta['generated_at'],
                context=snapshot['payload']['context'], source='ESPN',
                freshness=dict(latest_input_start_utc=max(r['ts_utc'] for r in rows),
                    latest_source_observation_utc=max(observations) if observations else None,
                    missing_observation_times=len(rows)-len(observations)),
                input_ids=[dict(source=r['source'],game_id=r['game_id']) for r in rows],
                missing_data=['PREMATCH_INJURIES','PREMATCH_ROSTERS','CALIBRATED_WIN_PROBABILITY'],
                stages=[capture_stage(c,stage) for c,stage in zip(cores,('FAZ13','FAZ22','FAZ23'))],
                scoring_scope='FINAL_WITH_OT', score_semantics='FAZ13_PROJECTION_WITH_DOWNSTREAM_DECISIONS',
                calibration_status='NOT_ESTABLISHED')
    if multilayer_config is not None:
        from faz28 import build_multilayer
        bundle['multilayer']=build_multilayer(snapshot,model_version=model_version,config=multilayer_config)
        bundle['multilayer_captured_at_utc']=int(time.time())
        for stage in bundle['stages']:stage['multilayer_sha256']=digest(bundle['multilayer'])
    if shadow_config is not None:
        if 'multilayer' not in bundle:raise ValueError('shadow comparison requires FAZ28 reference')
        from shadow_pairs import build_attempt
        bundle['shadow_pair']=build_attempt(bundle,snapshot,shadow_config)
    return bundle


def insert_stages(db, bundle, *, fixture_id, tipoff, prediction_utc, input_snapshot):
    now=int(time.time())
    if not 0 < prediction_utc <= now < tipoff:
        raise ValueError('FAZ24 requires actual pre-tipoff recording')
    if (input_snapshot is None or bundle.get('input_sha256') != input_snapshot['sha256']
            or bundle.get('generated_at') != prediction_utc
            or bundle.get('context') != input_snapshot['payload']['context']
            or bundle.get('source') != 'ESPN' or bundle.get('scoring_scope') != 'FINAL_WITH_OT'
            or bundle.get('schema_version') != 1
            or not re.fullmatch(r'[0-9a-f]{40}', bundle.get('model_version',''))):
        raise ValueError('FAZ24 original input/version binding mismatch')
    stages=bundle['stages']
    if [s['stage'] for s in stages] != ['FAZ13','FAZ22','FAZ23']:
        raise ValueError('exactly three ordered stages required')
    previous=prediction_utc
    for stage in stages:
        ts=stage['captured_at_utc']; out=stage['output'];meta=out['meta']
        if type(ts) is not int or not previous <= ts <= now < tipoff:
            raise ValueError('invalid stage chronology')
        previous=ts
        if (out['ctx'] != dict(league='NBA',**bundle['context'])
                or meta['generated_at'] != prediction_utc
                or any(meta[k] != input_snapshot['payload'][k] for k in ('expected_home','expected_away'))):
            raise ValueError('stage projection/context changed')
    if 'multilayer' in bundle:
        from faz28 import validate_multilayer
        ts=bundle.get('multilayer_captured_at_utc')
        if type(ts) is not int or not prediction_utc <= ts <= now:
            raise ValueError('multilayer capture chronology mismatch')
        validate_multilayer(bundle['multilayer'],input_snapshot,bundle['model_version'])
        if any(s.get('multilayer_sha256')!=digest(bundle['multilayer']) for s in stages):
            raise ValueError('stage multilayer binding mismatch')
    if 'shadow_pair' in bundle:
        from shadow_pairs import validate_attempt
        validate_attempt(bundle['shadow_pair'],bundle,input_snapshot,fixture_id,tipoff,int(time.time()))
    now=int(time.time())
    if now >= tipoff:raise ValueError('fixture started during stage replay')
    payload=canonical_json(bundle); sha=digest(bundle)
    db.execute('''CREATE TABLE IF NOT EXISTS faz24_stages (
        fixture_id TEXT PRIMARY KEY, home TEXT NOT NULL, away TEXT NOT NULL,
        start_utc INTEGER NOT NULL, recorded_utc INTEGER NOT NULL,
        payload TEXT NOT NULL, sha256 TEXT NOT NULL, UNIQUE(home,away,start_utc))''')
    for operation in ('UPDATE','DELETE'):
        db.execute(f"CREATE TRIGGER IF NOT EXISTS faz24_no_{operation.lower()} BEFORE {operation} ON faz24_stages BEGIN SELECT RAISE(ABORT,'immutable FAZ24 stage record'); END")
    old=db.execute('SELECT payload,sha256 FROM faz24_stages WHERE fixture_id=?',(fixture_id,)).fetchone()
    if old:
        if old != (payload,sha):
            raise ValueError('immutable FAZ24 record differs')
        return
    if db.execute("SELECT 1 FROM predictions WHERE league='NBA' AND fixture_id=?",(fixture_id,)).fetchone():
        raise ValueError('cannot attach stages after original prediction')
    ctx=bundle['context']
    db.execute('INSERT INTO faz24_stages VALUES (?,?,?,?,?,?,?)',
               (fixture_id,ctx['home'],ctx['away'],tipoff,now,payload,sha))


async def collect(*, engine, request, adapter, ledger, model_version, finalizer, expected_fixture=None, multilayer_config=None, shadow_config=None):
    # Fresh generation on each explicit invocation. Duplicates fail closed rather
    # than replacing the original immutable forecast with a newer run.
    from faz22_engine import Faz22Engine
    from providers.espn_turkey_fixture_lookup import resolve_named_nba_fixture_for_turkey_date
    fixture=await resolve_named_nba_fixture_for_turkey_date(adapter,request.date_str,home=request.home,away=request.away)
    if expected_fixture is not None and fixture != expected_fixture:
        raise ValueError('polled fixture changed before generation')
    if int(time.time()) >= fixture['start_ts_utc']:
        raise ValueError('fixture already started before generation')
    core=await engine.run_prematch(request)
    cores=[deepcopy(core)]; stages=[capture_stage(core,"FAZ13")]
    core=Faz22Engine().score_and_finalize(core);cores.append(deepcopy(core));stages.append(capture_stage(core,"FAZ22"))
    core=finalizer.apply_decision(core);cores.append(deepcopy(core));stages.append(capture_stage(core,"FAZ23"))
    if shadow_config is not None:shadow_config=dict(shadow_config,target=fixture)
    bundle=build_bundle(cores,model_version,multilayer_config,shadow_config)
    bundle["stages"]=stages
    if 'multilayer' in bundle:
        for stage in stages:stage['multilayer_sha256']=digest(bundle['multilayer'])
    result=await persist_resolved_nba_prematch(adapter=adapter,ledger=ledger,core=cores[0],
                                               stage_bundle=bundle, expected_fixture=expected_fixture)
    return dict(result, stage_sha256=digest(bundle))


def report(database):
    """Separate prospective accuracy from the offline walk-forward experiment."""
    from bound_backtest_report import report_bound
    import sqlite3
    multilayer_predictions={}
    with sqlite3.connect('file:'+str(database)+'?mode=ro',uri=True) as db:
        rows=db.execute('SELECT fixture_id,payload,sha256,start_utc,recorded_utc FROM faz24_stages').fetchall()
        for fixture,payload,sha,start,recorded in rows:
            if digest(json.loads(payload)) != sha:
                raise ValueError('FAZ24 integrity mismatch')
            bundle=json.loads(payload)
            ledger=object.__new__(PredictionLedger)
            ledger.db_path=str(database)
            inputs=ledger.load_prediction_inputs('NBA',fixture)
            if inputs is None or inputs['sha256'] != bundle['input_sha256']:
                raise ValueError('FAZ24 input binding missing or changed')
            if 'multilayer' in bundle:
                from faz28 import validate_multilayer
                ts=bundle.get('multilayer_captured_at_utc')
                if type(ts) is not int or not bundle['generated_at'] <= ts <= recorded < start:
                    raise ValueError('multilayer capture chronology mismatch')
                validate_multilayer(bundle['multilayer'],inputs,bundle['model_version'])
                multilayer_predictions[fixture]=bundle['multilayer']
                if any(s.get('multilayer_sha256')!=digest(bundle['multilayer']) for s in bundle['stages']):
                    raise ValueError('stage multilayer binding mismatch')
            provenance=db.execute("SELECT start_ts_utc FROM fixture_provenance WHERE league='NBA' AND fixture_id=? AND provider='ESPN'",(fixture,)).fetchone()
            if provenance != (start,) or not bundle['generated_at'] <= recorded < start:
                raise ValueError('FAZ24 fixture/recording chronology mismatch')
            if [s['stage'] for s in bundle['stages']] != ['FAZ13','FAZ22','FAZ23']:
                raise ValueError('missing FAZ24 stage')
            previous=bundle['generated_at']
            for stage in bundle['stages']:
                if not previous <= stage['captured_at_utc'] <= recorded:
                    raise ValueError('FAZ24 stage chronology mismatch')
                previous=stage['captured_at_utc']
                if any(stage['output']['meta'][k] != inputs['payload'][k] for k in ('expected_home','expected_away')):
                    raise ValueError('FAZ24 stage score differs from original')
    # Filter a temporary ledger snapshot to FAZ24 fixture IDs, never source DB.
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as folder:
        path=str(Path(folder)/'report.sqlite')
        with sqlite3.connect('file:'+str(database)+'?mode=ro',uri=True) as source:
            with sqlite3.connect(path) as target: source.backup(target)
        with sqlite3.connect(path) as db:
            ids={row[0] for row in rows}
            for (fixture,) in db.execute("SELECT fixture_id FROM predictions WHERE league='NBA'").fetchall():
                if fixture not in ids: db.execute("DELETE FROM predictions WHERE league='NBA' AND fixture_id=?",(fixture,))
        bound=report_bound(path)
    walk=bound.pop('walk_forward')
    return dict(prospective=bound, historical_walk_forward=walk,
                multilayer_predictions=multilayer_predictions,
                multilayer_evaluation=dict(status='REGULATION_PROXY_NOT_VALIDATED',sample_size=0,metrics=None,
                    reason='No separately verified regulation/period outcomes; do not score against OT-inclusive finals'),
                stages={stage:dict(score_output='shared_FAZ13_projection',
                         metrics=bound['metrics'],brier_score=None,log_loss=None,
                         probability_calibration=None) for stage in ('FAZ13','FAZ22','FAZ23')},
                limitation='Stage confidence is heuristic; no archived calibrated win probability')


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    q=sub.add_parser('report');q.add_argument('database')
    q=sub.add_parser('collect');q.add_argument('database');q.add_argument('baselines')
    q.add_argument('date');q.add_argument('home');q.add_argument('away');q.add_argument('--model-version',required=True);q.add_argument('--multilayer',action='store_true');q.add_argument('--shadow-periods');q.add_argument('--shadow-model')
    args=p.parse_args(argv)
    try:
        if args.command=='report': result=report(args.database)
        else:
            import subprocess
            from pathlib import Path
            repo=Path(__file__).resolve().parent
            actual=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
            dirty=subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=repo,text=True)
            if actual != args.model_version or dirty:
                raise ValueError('model version must match clean checked-out commit')
            from baseline.team_baseline_store import TeamBaselineStore
            from faz13_engine import Faz13Engine, PrematchRequest
            from faz23_engine import Faz23Engine
            from providers.espn_adapter import ESPNAdapter
            shadow_config=None
            if args.shadow_model and not args.shadow_periods:raise ValueError('shadow period data required')
            if args.shadow_periods:
                if not args.multilayer:raise ValueError('shadow requires explicit multilayer reference')
                data=json.loads(Path(args.shadow_periods).read_text())
                records=data['period_feature_layer']['records'] if isinstance(data,dict) else data
                shadow_config=dict(period_records=records,artifact=json.loads(Path(args.shadow_model).read_text()) if args.shadow_model else None)
            async def run():
                adapter=ESPNAdapter()
                engine=Faz13Engine('', '',baseline_store=TeamBaselineStore(args.baselines))
                engine.espn=adapter
                try:
                    import tempfile
                    from pathlib import Path
                    with tempfile.TemporaryDirectory() as folder:
                        finalizer=Faz23Engine(str(Path(folder)/'decisions.sqlite'))
                        return await collect(engine=engine,request=PrematchRequest(0,'NBA',args.date,args.home,args.away),
                            adapter=adapter,ledger=PredictionLedger(args.database),model_version=args.model_version,finalizer=finalizer,
                            multilayer_config={} if args.multilayer else None,shadow_config=shadow_config)
                finally: await adapter.aclose()
            result=asyncio.run(run())
        print(json.dumps(result,sort_keys=True,allow_nan=False));return 0
    except (ValueError,TypeError,KeyError,OSError,RuntimeError,__import__('sqlite3').Error) as exc:
        print(json.dumps(dict(status='rejected',error_type=type(exc).__name__)));return 1


if __name__=='__main__': raise SystemExit(main())

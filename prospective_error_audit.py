"""Version-separated error audit of immutable prospective records and verified finals."""
from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal
import json
import math
from pathlib import Path
import sqlite3
import time

from prediction_inputs import digest,canonical_json
from prediction_ledger import PredictionLedger
from providers.espn_result_evidence import parse_final_summary
from historical_backtest import HistoricalPrediction,evaluate_predictions
from walk_forward_calibration import evaluate_walk_forward


def _period_final(payload, observed):
    event=parse_final_summary(payload,observed)
    if event is None:raise ValueError('verified FINAL required')
    comp=payload['header']['competitions'][0];sides={}
    for c in comp['competitors']:
        values=[]
        for line in c['linescores']:
            raw=line['displayValue']
            if not isinstance(raw,str) or not raw.isascii() or not raw.isdigit():raise ValueError('invalid period score')
            values.append(int(raw))
        if not 4<=len(values)<=12 or sum(values)!=event['actual_'+c['homeAway']]:raise ValueError('period totals mismatch')
        sides[c['homeAway']]=values
    if len(sides['home'])!=len(sides['away']):raise ValueError('period count mismatch')
    for n in range(4,len(sides['home'])):
        if sum(sides['home'][:n])!=sum(sides['away'][:n]):raise ValueError('overtime without preceding tie')
    stated=comp.get('status',payload['header'].get('status',{})).get('period')
    if stated is not None and (type(stated) is not int or stated!=len(sides['home'])):raise ValueError('status period mismatch')
    return dict(event=event,periods=sides,regulation_home=sum(sides['home'][:4]),
                regulation_away=sum(sides['away'][:4]),overtime=len(sides['home'])>4)


def period_final(payload, observed):
    try:return _period_final(payload,observed)
    except (KeyError,TypeError,IndexError,AttributeError,OverflowError) as exc:
        raise ValueError('missing or malformed period evidence') from exc


def record_period_result(ledger,fixture,payload,source_observed_utc):
    final=ledger.load_outcome_evidence('NBA',fixture)
    if final is None:raise ValueError('bound final evidence required first')
    now=int(time.time())
    if type(source_observed_utc) is not int or not 0<source_observed_utc<=now:raise ValueError('invalid source time')
    parsed=period_final(payload,source_observed_utc)
    if parsed['event']!=final['snapshot']['event']:raise ValueError('period/final identity conflict')
    header=payload['header'];comp=header['competitions'][0]
    trimmed=dict(id=header['id'],competitions=[dict(id=comp['id'],date=comp['date'],
       competitors=[dict(homeAway=c['homeAway'],score=c['score'],team={'id':c['team']['id']},linescores=c['linescores']) for c in comp['competitors']])])
    if 'status' in header:trimmed['status']=header['status']
    if 'status' in comp:trimmed['competitions'][0]['status']=comp['status']
    p=dict(source_url=final['snapshot']['source_url'],final_sha256=final['sha256'],
           source_observed_utc=source_observed_utc,recorded_utc=now,summary={'header':trimmed})
    with ledger._connect() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS period_result_evidence (fixture_id TEXT PRIMARY KEY,payload TEXT NOT NULL,sha256 TEXT NOT NULL)')
        for op in ('UPDATE','DELETE'):
            db.execute(f"CREATE TRIGGER IF NOT EXISTS period_result_no_{op} BEFORE {op} ON period_result_evidence BEGIN SELECT RAISE(ABORT,'immutable period result'); END")
        current=db.execute("SELECT evidence_sha256 FROM outcome_evidence WHERE league='NBA' AND fixture_id=?",(fixture,)).fetchone()
        if current!=(final['sha256'],):raise ValueError('final evidence changed')
        old=db.execute('SELECT payload,sha256 FROM period_result_evidence WHERE fixture_id=?',(fixture,)).fetchone()
        if old:
            previous=json.loads(old[0])
            if digest(previous)!=old[1]:raise ValueError('period evidence digest mismatch')
            prior,new=deepcopy(previous),deepcopy(p)
            if new.pop('source_observed_utc')<prior.pop('source_observed_utc'):raise ValueError('backdated period evidence')
            prior.pop('recorded_utc');new.pop('recorded_utc')
            if prior!=new:raise ValueError('immutable period evidence conflict')
            return False
        db.execute('INSERT INTO period_result_evidence VALUES (?,?,?)',(fixture,canonical_json(p),digest(p)))
        return True


def errors(home,away,actual_home,actual_away):
    if any(type(v) not in (int,float) or not math.isfinite(v) or v<0 for v in (home,away)):
        raise ValueError('invalid projection')
    if any(type(v) is not int or v<0 for v in (actual_home,actual_away)):raise ValueError('invalid actual score')
    h,a=Decimal(str(home)),Decimal(str(away));eh=h-actual_home;ea=a-actual_away
    margin=h-a;actual_margin=actual_home-actual_away
    return dict(expected_home=home,expected_away=away,actual_home=actual_home,actual_away=actual_away,
      home_error=float(eh),away_error=float(ea),total_absolute_error=float(abs(eh+ea)),
      predicted_margin=float(margin),actual_margin=actual_margin,margin_error=float(margin-actual_margin),
      margin_absolute_error=float(abs(margin-actual_margin)),
      winner_direction_correct=(None if margin==0 else bool((margin>0)==(actual_margin>0))) if actual_margin!=0 else None)


def read_only_ledger(path):
    ledger=object.__new__(PredictionLedger);ledger.db_path=str(path)
    ledger._connect=lambda:sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
    return ledger


def audit(paths):
    rows=[];groups={};seen=set();canonical_games=set();checks=[]
    for path in paths:
        ledger=read_only_ledger(path)
        with ledger._connect() as db:
            stages=db.execute('SELECT fixture_id,start_utc,recorded_utc,payload,sha256 FROM faz24_stages').fetchall()
            integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
            if integrity!='ok':raise ValueError('SQLite integrity failure')
            checks.append(dict(ledger=str(path),integrity=integrity))
        for fixture,start,recorded,raw,sha in stages:
            if fixture in seen:raise ValueError('duplicate fixture across research ledgers')
            seen.add(fixture);bundle=json.loads(raw)
            if digest(bundle)!=sha:raise ValueError('stage digest mismatch')
            inputs=ledger.load_prediction_inputs('NBA',fixture)
            if inputs is None or inputs['sha256']!=bundle['input_sha256']:raise ValueError('original input binding mismatch')
            if not bundle['generated_at']<=recorded<start:raise ValueError('not prospective')
            with ledger._connect() as db:
                prediction=db.execute("SELECT prediction_ts_utc,expected_home,expected_away,scope FROM predictions WHERE league='NBA' AND fixture_id=?",(fixture,)).fetchone()
            if prediction!=(bundle['generated_at'],inputs['payload']['expected_home'],inputs['payload']['expected_away'],'FINAL_WITH_OT'):raise ValueError('canonical prediction mismatch')
            if [s['stage'] for s in bundle['stages']]!=['FAZ13','FAZ22','FAZ23']:raise ValueError('missing stages')
            previous=bundle['generated_at']
            for stage in bundle['stages']:
                if stage['output']['ctx']!=dict(league='NBA',**bundle['context']) or not previous<=stage['captured_at_utc']<=recorded:raise ValueError('stage context/chronology mismatch')
                previous=stage['captured_at_utc']
                if any(stage['output']['meta'][k]!=inputs['payload'][k] for k in ('expected_home','expected_away')):raise ValueError('stage score changed')
            evidence=ledger.load_outcome_evidence('NBA',fixture)
            if evidence is None:
                rows.append(dict(fixture_id=fixture,status='awaiting_verified_final'));continue
            event=evidence['snapshot']['event'];observed=evidence['snapshot']['observed_at_utc']
            if event['start_ts_utc']!=start or not start<observed:raise ValueError('result identity/time mismatch')
            canonical=(start,tuple(sorted((event['home_team_id'],event['away_team_id']))))
            if canonical in canonical_games:raise ValueError('duplicate canonical game across ledgers')
            canonical_games.add(canonical)
            base=dict(fixture_id=fixture,status='evaluated',context=bundle['context'],model_version=bundle['model_version'],
                      generated_at=bundle['generated_at'],start_utc=start,recorded_utc=recorded,
                      result_observed_utc=observed,source_url=evidence['snapshot']['source_url'],
                      final_evidence_sha256=evidence['sha256'],missing_data=bundle['missing_data'])
            def add(model,scope,home,away,actual_home,actual_away,when):
                item=dict(base,model=model,scope=scope,**errors(home,away,actual_home,actual_away))
                item['result_observed_utc']=when
                key=(model,bundle['model_version'],scope)
                groups.setdefault(key,[]).append(HistoricalPrediction(fixture,'NBA',bundle['generated_at'],when,
                  home,away,actual_home,actual_away,prediction_scope=scope,result_scope=scope,fixture_start_ts_utc=start))
                rows.append(item);return item
            anchor=add('FAZ13','FINAL_WITH_OT',prediction[1],prediction[2],event['actual_home'],event['actual_away'],observed)
            period=None
            with ledger._connect() as db:
                exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='period_result_evidence'").fetchone()
                pr=db.execute('SELECT payload,sha256 FROM period_result_evidence WHERE fixture_id=?',(fixture,)).fetchone() if exists else None
            if pr:
                p=json.loads(pr[0])
                if digest(p)!=pr[1] or p['final_sha256']!=evidence['sha256'] or p['source_url']!=evidence['snapshot']['source_url']:raise ValueError('period/result binding mismatch')
                if not start<p['source_observed_utc']<=p['recorded_utc']<=int(time.time()):raise ValueError('period observation time mismatch')
                period=period_final(p['summary'],p['source_observed_utc'])
                if period['event']!=event:raise ValueError('period/final conflict')
            if 'multilayer' in bundle:
                layer=bundle['multilayer'];simulation=layer.get('simulation')
                if layer.get('model_id')!='FAZ28_NORMAL_V1' or layer.get('model_scope')!='REGULATION_ONLY' or not bundle['generated_at']<=bundle['multilayer_captured_at_utc']<=recorded:raise ValueError('unsupported model scope/chronology')
                if layer['input_sha256']!=inputs['sha256'] or layer['model_version']!=bundle['model_version'] or any(s.get('multilayer_sha256')!=digest(layer) for s in bundle['stages']):raise ValueError('multilayer digest binding mismatch')
                if simulation and period:
                    item=add(layer['model_id']+'/MC','REGULATION_ONLY',simulation['expected_home_score'],simulation['expected_away_score'],period['regulation_home'],period['regulation_away'],p['recorded_utc'])
                    actual=period['regulation_home']+period['regulation_away'];lo=simulation['total_quantiles']['p05'];hi=simulation['total_quantiles']['p95']
                    item['distribution']=dict(actual_regulation_total=actual,p05=lo,p95=hi,inside_p05_p95=lo<=actual<=hi,
                       regulation_probabilities={k:simulation[k] for k in ('home_regulation_win_probability','away_regulation_win_probability','regulation_tie_probability')},
                       scope_status=layer['scope_status'],overtime=period['overtime'])
                    item['quarter_comparison']=[dict(quarter=i+1,expected=layer['quarters'][str(i+1)],actual_home=period['periods']['home'][i],actual_away=period['periods']['away'][i]) for i in range(4)]
                else:rows.append(dict(base,model=layer['model_id']+'/MC',status='missing_regulation_evidence_or_simulation'))
    metrics=[]
    for (model,version,scope),records in groups.items():
        margin_errors=[(r.expected_home-r.expected_away)-(r.actual_home-r.actual_away) for r in records]
        values=asdict(evaluate_predictions(records))
        values.update(margin_mae=sum(abs(e) for e in margin_errors)/len(records),
                      margin_rmse=math.sqrt(sum(e*e for e in margin_errors)/len(records)))
        metrics.append(dict(model=model,model_version=version,scope=scope,metrics=values,
            historical_walk_forward=evaluate_walk_forward(records),calibration_status='NOT_ESTABLISHED'))
    return dict(rows=rows,cohorts=metrics,ledgers=checks,distinct_fixtures=len(seen),
                error_sign='prediction_minus_actual',statistical_status='SMALL_SAMPLE_DESCRIPTIVE_ONLY',
                policy='Observed results may train only later predictions; never alter original forecasts')


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('ledgers',nargs='+')
    args=parser.parse_args()
    print(json.dumps(audit(args.ledgers),sort_keys=True,allow_nan=False))

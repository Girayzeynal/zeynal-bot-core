"""Read-only native result review of first conditional period research receipts."""
import argparse
from collections import Counter,defaultdict
import json
import math
import re
import time
import numpy as np
from core.team_identity import digest
from hybrid_engine.data import local_path
from hybrid_engine.rotation_periods import read,capture,VERSION
from hybrid_engine.time_policy import PREMATCH_MINIMUM_LEAD_SECONDS

MARKETS={'1Q':[0],'2Q':[1],'3Q':[2],'4Q':[3],'1H':[0,1],'2H':[2,3]}
MODELS=('original','team_allocation','player_allocation')

def metrics(rows):
    out={}
    for model in MODELS:
        markets={}
        for label,idx in MARKETS.items():
            errors=[];hits=[];widths=[]
            for r in rows:
                actual=np.asarray(r['actual'],dtype=float)[idx].sum(axis=0)
                forecast=np.asarray(r[model]['quarters'],dtype=float)[idx].sum(axis=0)
                errors.append(forecast-actual)
                if model!='original':
                    lo,_,hi=r[model]['conditional_80_intervals'][label]['total']
                    hits.append(lo<=actual.sum()<=hi);widths.append(hi-lo)
            if not errors:continue
            e=np.asarray(errors);t=e.sum(axis=1)
            markets[label]=dict(n=len(e),total_mae=float(np.mean(abs(t))),
                total_rmse=float(np.sqrt(np.mean(t*t))),total_bias=float(t.mean()),
                home_mae=float(np.mean(abs(e[:,0]))),away_mae=float(np.mean(abs(e[:,1]))),
                margin_mae=float(np.mean(abs(e[:,0]-e[:,1]))))
            if hits:
                markets[label].update(conditional_interval_hits=sum(hits),
                    descriptive_observed_coverage=sum(hits)/len(hits),
                    mean_interval_width=float(np.mean(widths)))
        out[model]=markets
    return out

def evaluate(root,ledger,*,now=None):
    from ledger_reports import LedgerReports
    from hybrid_engine.player_inputs import load_snapshot
    root=local_path(root);ledger=local_path(ledger)
    now=int(time.time()) if now is None else now
    if type(now) is not int or now>int(time.time()):raise ValueError('PERIOD_REVIEW_FUTURE_CLOCK')
    native=LedgerReports(ledger).read('NBA')
    if native['status']!='VERIFIED_LIVE_REPORT':raise ValueError('PERIOD_REVIEW_LEDGER_UNVERIFIED')
    originals={(r['fixture_id'],r['snapshot_sha256']):r for r in native['forecasts']}
    records=defaultdict(list);exclusions=Counter()
    for path in sorted(root.glob('period-score-*.json')):
        m=re.fullmatch(r'period-score-([0-9a-f]{64})\.json',path.name)
        if not m:continue
        try:
            pin=m[1];p=read(root,'period-score-',pin)
            row=originals[(p['fixture_id'],p['original_snapshot_sha256'])]
            tip=row['fixture_start_utc'];generated=p['generated_at_utc']
            if (p['format']!=VERSION or p['status']!='FORWARD_CONDITIONAL_PERIOD_RESEARCH'
                or p['production_enabled'] or p['forecast_changed']
                or p['fixture_start_utc']!=tip
                or not row['prediction_generated_at_utc']<=generated<=now
                or not generated<=path.stat().st_mtime<tip-PREMATCH_MINIMUM_LEAD_SECONDS):
                raise ValueError('PERIOD_REVIEW_PUBLICATION_SCOPE_OR_CLOCK')
            factor=read(root,'factor-score-',p['factor_sha256'])
            factor_path=root/('factor-score-'+p['factor_sha256']+'.json')
            if not factor['generated_at_utc']<=factor_path.stat().st_mtime<generated+1:
                raise ValueError('PERIOD_REVIEW_FACTOR_CLOCK')
            a=read(root,'period-model-',p['control_sha256'])
            b=read(root,'period-model-',p['model_sha256'])
            snapshot=load_snapshot(ledger,p['fixture_id'])
            # capture is pure and accepts the ORIGINAL decision clock.
            # Never publish or replace an old record during evaluation.
            replay=capture(root,factor,p['factor_sha256'],snapshot,
                dict(payload=a,sha256=p['control_sha256']),
                dict(payload=b,sha256=p['model_sha256']),generated)
            for k in ('fixture_id','original_snapshot_sha256','rotation_sha256','factor_sha256',
                      'model_sha256','control_sha256','training_games','player_terms'):
                if replay[k]!=p[k]:raise ValueError('PERIOD_REVIEW_IDENTITY_REPLAY')
            for model in MODELS[1:]:
                for field in ('quarters','halves','score','total','represented_minutes'):
                    x=np.asarray(replay[model][field],dtype=float);y=np.asarray(p[model][field],dtype=float)
                    if x.shape!=y.shape or not np.allclose(x,y,rtol=0,atol=1e-6):
                        raise ValueError('PERIOD_REVIEW_SCORE_REPLAY')
                for market in MARKETS:
                    for side in ('home','away','total'):
                        if not np.allclose(replay[model]['conditional_80_intervals'][market][side],
                                           p[model]['conditional_80_intervals'][market][side],rtol=0,atol=1e-6):
                            raise ValueError('PERIOD_REVIEW_INTERVAL_REPLAY')
            records[(row['season'],p['fixture_id'])].append((generated,path.stat().st_mtime,pin,p,row,snapshot))
        except (ValueError,KeyError,TypeError,OSError,IndexError,np.linalg.LinAlgError) as exc:
            reason=str(exc);exclusions[reason if reason.isupper() and len(reason)<100 else type(exc).__name__]+=1
    seasons=defaultdict(lambda:dict(rows=[],pending=0,duplicates=0));detail=[]
    for (season,fid),items in sorted(records.items()):
        g=seasons[season];g['duplicates']+=len(items)-1
        _,_,pin,p,row,snapshot=min(items,key=lambda x:x[:3])
        label=row.get('label_available_utc')
        if row['actual'] is None or type(label) is not int or label>now:
            g['pending']+=1;continue
        try:
            if label<=row['fixture_start_utc']:raise ValueError('PERIOD_REVIEW_FINAL_CLOCK')
            actual=np.array([row['actual_periods'][s][:4] for s in ('home','away')]).T
            if actual.shape!=(4,2) or (actual<0).any() or not np.array_equal(actual.sum(axis=0),row['actual']):
                raise ValueError('PERIOD_REVIEW_REGULATION_LABEL')
            original=np.asarray(snapshot['prediction']['quarters'],dtype=float)
            if original.shape!=(4,2) or not np.allclose(original.sum(axis=0),row['prediction'],rtol=0,atol=1e-6):
                raise ValueError('PERIOD_REVIEW_ORIGINAL_SCORE')
            r=dict(actual=actual.tolist(),original=dict(quarters=original.tolist()),
                   team_allocation=p['team_allocation'],player_allocation=p['player_allocation'])
            g['rows'].append(r);detail.append(dict(fixture_id=fid,home=row['home'],away=row['away'],
                receipt=pin,actual=actual.tolist(),original=original.tolist(),
                team_allocation=p['team_allocation']['quarters'],player_allocation=p['player_allocation']['quarters']))
        except (ValueError,KeyError,TypeError,IndexError) as exc:
            reason=str(exc);exclusions[reason if reason.isupper() and len(reason)<100 else type(exc).__name__]+=1
    return dict(format='NBA_ROTATION_PERIOD_FORWARD_LOCAL_REVIEW_V1',groups=[
        dict(season=k,matched=len(v['rows']),pending=v['pending'],duplicates=v['duplicates'],metrics=metrics(v['rows']))
        for k,v in sorted(seasons.items())],exclusions=dict(exclusions),results=detail,
        interval_scope='FIXED_PREDICTED_TOTALS_DESCRIPTIVE_NOT_CALIBRATION',
        publication_evidence='LOCAL_FILE_CLOCK_NOT_EXTERNAL_ATTESTATION',
        production_enabled=False,calibrated=False,original_archive_read_only=True)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--data-directory',required=True)
    a=p.parse_args();root=local_path(a.data_directory)
    print(json.dumps(evaluate(root/'player-shadow',root/'live-nba/nba-hybrid.sqlite'),ensure_ascii=False,indent=2,allow_nan=False))
if __name__=='__main__':main()

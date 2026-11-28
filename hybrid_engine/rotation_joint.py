"""Joint regulation score research, using earlier settled forecast error vectors.

The residual law is transferred from archived original forecasts, NOT estimated
from the new model's out-of-sample errors. No odds or production changes.
"""
import argparse
from collections import defaultdict
import json
import math
import re
import time
import numpy as np
from core.team_identity import digest
from hybrid_engine.data import Abstain,local_path
from hybrid_engine.boxes import publish_json
from hybrid_engine.rotation_periods import read,capture,VERSION as PERIOD_VERSION
from hybrid_engine.time_policy import PREMATCH_MINIMUM_LEAD_SECONDS

VERSION='NBA_JOINT_ARCHIVED_ERROR_RESEARCH_V1'
SCENARIOS=8192
SEED=20261127
MARKETS={'1Q':[0],'2Q':[1],'3Q':[2],'4Q':[3],'1H':[0,1],'2H':[2,3],'FULL':[0,1,2,3]}

def residual_pool(rows,target,cutoff):
    """First archived forecast per fixture, then require a known regulation label."""
    groups=defaultdict(list)
    for r in rows:
        if (r['fixture_id']==target['fixture_id'] or r['league']!='NBA'
            or r['season']!=target['season'] or r['model_version']!=target['model_version']):continue
        t=r['fixture_start_utc'];g=r.get('prediction_generated_at_utc');a=r.get('first_archived_at_utc')
        if type(g) is not int or type(a) is not int or not 0<g<=a<t-PREMATCH_MINIMUM_LEAD_SECONDS:continue
        if a<=cutoff and t<cutoff:groups[r['fixture_id']].append(r)
    out=[]
    for fid,items in sorted(groups.items()):
        r=min(items,key=lambda r:(r['first_archived_at_utc'],r['prediction_generated_at_utc'],r['snapshot_sha256']))
        label=r.get('label_available_utc')
        if r.get('actual') is None or type(label) is not int or not r['fixture_start_utc']<label<=cutoff:continue
        q=np.asarray(r.get('predicted_quarters'),dtype=float)
        actual=np.asarray([r['actual_periods'][s][:4] for s in ('home','away')],dtype=float).T
        if (q.shape!=(4,2) or actual.shape!=(4,2) or not np.isfinite(q).all()
            or not np.isfinite(actual).all() or (q<0).any() or (actual<0).any()
            or not np.allclose(q.sum(axis=0),r['prediction'],rtol=0,atol=1e-6)
            or not np.array_equal(actual.sum(axis=0),r['actual'])):continue
        out.append(dict(fixture_id=fid,snapshot_sha256=r['snapshot_sha256'],model_digest=r['model_digest'],
            label_available_utc=label,errors=(actual-q).tolist()))
    if len(out)<2:raise Abstain('JOINT_RESIDUAL_HISTORY_INSUFFICIENT')
    return out

def simulate(quarters,pool):
    q=np.asarray(quarters,dtype=float);e=np.asarray([r['errors'] for r in pool],dtype=float)
    if (q.shape!=(4,2) or not np.isfinite(q).all() or (q<0).any() or (q.sum(axis=0)<=0).any()
        or e.ndim!=3 or e.shape[1:]!=(4,2) or len(e)<2 or not np.isfinite(e).all()):
        raise ValueError('JOINT_SCORE_OR_RESIDUAL_SCHEMA')
    # Center transferred residuals rather than assume the old model's bias
    # is the new model's bias. Joint vectors retain empirical dependence.
    rng=np.random.default_rng(SEED);mean=e.mean(axis=0)
    draw=e[rng.integers(len(e),size=SCENARIOS)]-mean
    raw=q[None,:,:]+draw
    clipped=int((raw<0).any(axis=(1,2)).sum())
    paths=np.rint(np.maximum(raw,0)).astype(np.int32)
    report={}
    for label,idx in MARKETS.items():
        scores=paths[:,idx,:].sum(axis=1)
        cols={'home':scores[:,0],'away':scores[:,1],'total':scores.sum(axis=1),'margin':scores[:,0]-scores[:,1]}
        report[label]={k:dict(mean=float(v.mean()),p05=float(np.quantile(v,.05)),p10=float(np.quantile(v,.1)),
            p50=float(np.quantile(v,.5)),p90=float(np.quantile(v,.9)),p95=float(np.quantile(v,.95)))
            for k,v in cols.items()}
    totals=paths.sum(axis=1);margin=totals[:,0]-totals[:,1]
    if np.unique(totals.sum(axis=1)).size<2:raise Abstain('JOINT_TOTAL_VARIATION_UNSUPPORTED')
    return dict(markets=report,scenarios=len(paths),seed=SEED,unique_game_totals=int(np.unique(totals.sum(axis=1)).size),
        regulation_outcomes=dict(home=float(np.mean(margin>0)),tie=float(np.mean(margin==0)),away=float(np.mean(margin<0))),
        negative_path_clips=clipped,source_mean_residual=mean.tolist(),point_quarters=q.tolist(),
        point_team_scores=q.sum(axis=0).tolist(),point_total=float(q.sum()),
        scenario_sha256=digest(paths.tolist()),calibrated=False,
        uncertainty_scope='TRANSFERRED_CENTERED_ORIGINAL_FORECAST_ERRORS_NOT_CANDIDATE_CALIBRATION')

def main():
    from ledger_reports import LedgerReports
    from hybrid_engine.player_inputs import load_snapshot,file_sha256
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--data-directory',required=True)
    p.add_argument('--maximum',type=int,default=4);args=p.parse_args()
    if not 1<=args.maximum<=8:p.error('maximum must be 1..8')
    root=local_path(args.data_directory);folder=root/'player-shadow';ledger=root/'live-nba/nba-hybrid.sqlite'
    before=file_sha256(ledger);now=int(time.time());native=LedgerReports(ledger).read('NBA')
    if native['status']!='VERIFIED_LIVE_REPORT':raise ValueError('JOINT_LEDGER_UNVERIFIED')
    originals={(r['fixture_id'],r['snapshot_sha256']):r for r in native['forecasts']}
    chosen={}
    for path in sorted(folder.glob('period-score-*.json')):
        m=re.fullmatch(r'period-score-([0-9a-f]{64})\.json',path.name)
        if not m:continue
        r=read(folder,'period-score-',m[1]);key=(r['fixture_id'],r['original_snapshot_sha256'])
        row=originals.get(key)
        if (not row or row['actual'] is not None or r['format']!=PERIOD_VERSION
            or r['fixture_start_utc']!=row['fixture_start_utc'] or r['production_enabled'] or r['forecast_changed']
            or not r['generated_at_utc']<=path.stat().st_mtime<r['fixture_start_utc']-PREMATCH_MINIMUM_LEAD_SECONDS
            or now>=r['fixture_start_utc']-PREMATCH_MINIMUM_LEAD_SECONDS):continue
        order=(r['generated_at_utc'],path.stat().st_mtime,m[1])
        if key not in chosen or order<chosen[key][0]:chosen[key]=(order,r,m[1],row)
    results=[]
    for _,r,pin,row in sorted(chosen.values(),key=lambda x:(x[1]['fixture_start_utc'],x[1]['fixture_id']))[:args.maximum]:
        try:
            snapshot=load_snapshot(ledger,row['fixture_id'])
            factor=read(folder,'factor-score-',r['factor_sha256'])
            a=read(folder,'period-model-',r['control_sha256']);b=read(folder,'period-model-',r['model_sha256'])
            replay=capture(folder,factor,r['factor_sha256'],snapshot,
                dict(payload=a,sha256=r['control_sha256']),dict(payload=b,sha256=r['model_sha256']),r['generated_at_utc'])
            if not np.allclose(replay['player_allocation']['quarters'],r['player_allocation']['quarters'],rtol=0,atol=1e-6):
                raise ValueError('JOINT_PERIOD_REPLAY')
            decision=int(time.time());pool=residual_pool(native['forecasts'],row,decision)
            result=simulate(r['player_allocation']['quarters'],pool)
            if int(time.time())>=row['fixture_start_utc']-PREMATCH_MINIMUM_LEAD_SECONDS:
                raise Abstain('JOINT_PUBLICATION_WINDOW_CLOSED')
            receipt=dict(format=VERSION,status='FORWARD_JOINT_RESEARCH',fixture_id=row['fixture_id'],
                fixture_start_utc=row['fixture_start_utc'],generated_at_utc=decision,
                original_snapshot_sha256=row['snapshot_sha256'],period_sha256=pin,
                original_model_version=row['model_version'],residual_games=len(pool),residual_pool_sha256=digest(pool),
                residual_model_digests=len({v['model_digest'] for v in pool}),simulation=result,
                production_enabled=False,forecast_changed=False,calibrated=False)
            publish_json(folder/('joint-pool-'+digest(pool)+'.json'),dict(payload=pool,sha256=digest(pool)))
            if int(time.time())>=row['fixture_start_utc']-PREMATCH_MINIMUM_LEAD_SECONDS:
                raise Abstain('JOINT_PUBLICATION_WINDOW_CLOSED')
            h=digest(receipt);publish_json(folder/('joint-score-'+h+'.json'),dict(payload=receipt,sha256=h))
            out=dict(receipt,sha256=h)
        except (ValueError,KeyError,TypeError,OSError,np.linalg.LinAlgError) as exc:
            out=dict(status='BLOCKED',reason=str(exc) if str(exc).isupper() and len(str(exc))<100 else type(exc).__name__)
        results.append(dict(home=row['home'],away=row['away'],**out))
    print(json.dumps(dict(format=VERSION,results=results,source_calls=0,database_bytes_unchanged=before==file_sha256(ledger),production_changed=False),ensure_ascii=False,indent=2,allow_nan=False))
if __name__=='__main__':main()

"""Conditional quarter research using historical player rotation and factor scores.

Full-game minutes are exposure proxies, not observed quarter lineups.
Both allocation candidates share the same fixed factor game scores. Simulations
condition on rounded team scores; they do not quantify full-game uncertainty.
"""
import argparse
from collections import Counter,defaultdict
import json
import math
import re
import time
import numpy as np
from core.team_identity import digest
from hybrid_engine.boxes import publish_json
from hybrid_engine.data import STRICT,Abstain,available_at,local_path,regulation
from hybrid_engine.player_box_pilot import verified_box_rows
from hybrid_engine.rotation_efficiency import design,predict as factor_predict
from hybrid_engine.historical_five_score import rotation_from_summary
from hybrid_engine.time_policy import PREMATCH_MINIMUM_LEAD_SECONDS

VERSION='NBA_ROTATION_CONDITIONAL_PERIOD_RESEARCH_V1'
POLICY=dict(team_prior=.12,player_prior=.06,home_prior=.06,noise_floor=.01,
            maximum_players=450,scenarios=4096,seed=20261127)

def training_rows(cohort,cutoff):
    games,excluded=verified_box_rows(cohort,cutoff)
    indexed=defaultdict(list)
    for versions in cohort:
        for r in versions:
            if r.get('box') is not None and available_at(r,STRICT)<=cutoff:
                indexed[(r['fixture_id'],r['box']['source_digest'])].append(r)
    result=[]
    for g in games:
        matches=indexed[(g['fixture_id'],g['source_sha256'])]
        r=max(matches,key=lambda r:available_at(r,STRICT))
        q=[r['periods'][s][:4] for s in ('home','away')]
        if (any(len(v)!=4 or any(type(x) is not int or x<0 for x in v) for v in q)
            or [sum(v) for v in q]!=g['score'] or min(g['score'])<=0):
            excluded['INVALID_REGULATION_PERIODS']=excluded.get('INVALID_REGULATION_PERIODS',0)+1
            continue
        result.append(dict(g,quarters=q))
    return result,excluded

def fit(games,cutoff,*,players_enabled):
    if not 30<=len(games)<=1000:raise Abstain('PERIOD_TRAINING_BOX_BUDGET')
    if (type(cutoff) is not int or not 0<cutoff<=int(time.time())
        or len({g['fixture_id'] for g in games})!=len(games)
        or len({g['season'] for g in games})!=1
        or any(g['league']!='NBA' or not g['fixture_start_utc']<g['available_at_utc']<=cutoff for g in games)):
        raise ValueError('PERIOD_TRAINING_IDENTITY_OR_CLOCK')
    teams=sorted({g[s+'_team_id'] for g in games for s in ('home','away')})
    counts=Counter(p for g in games for r in g['minutes'].values() for p,v in r.items() if v>0)
    players=sorted(sorted(counts,key=lambda p:(-counts[p],p))[:POLICY['maximum_players']]) if players_enabled else []
    x=[];y=[]
    for g in games:
        q=np.asarray(g['quarters'],dtype=float)
        if q.shape!=(2,4) or not np.isfinite(q).all() or (q<0).any() or not np.array_equal(q.sum(axis=1),g['score']):
            raise ValueError('PERIOD_TRAINING_SCORE_CONFLICT')
        for j,(s,o) in enumerate((('home','away'),('away','home'))):
            x.append(design(teams,players,g[s+'_team_id'],g[o+'_team_id'],g['minutes'][s],g['minutes'][o],j==0))
            log=np.log(q[j]+.5);y.append(log-log.mean())
    x=np.asarray(x);y=np.asarray(y)
    center=y.mean(axis=0);residual=y-center
    scale=np.r_[POLICY['home_prior'],np.full(2*len(teams),POLICY['team_prior']),np.full(2*len(players),POLICY['player_prior'])]
    z=x*scale
    noise=max(POLICY['noise_floor'],float(np.mean(np.var(residual,axis=0,ddof=1))))
    coef=scale[:,None]*(z.T@np.linalg.solve(z@z.T+noise*np.eye(len(y)),residual))
    if not np.isfinite(coef).all():raise ValueError('PERIOD_NONFINITE_FIT')
    # Paired historical residuals preserve cross-team and across-quarter dependence.
    errors=(y-center-x@coef).reshape(-1,2,4)
    errors-=errors.mean(axis=0)
    payload=dict(format=VERSION,season=games[0]['season'],cutoff_utc=cutoff,
        teams=teams,players=players,training_games=len(games),
        training_fixture_ids=[g['fixture_id'] for g in games],training_sha256=digest(games),
        center=center.tolist(),coefficients=coef.tolist(),paired_residuals=errors.tolist(),
        policy=POLICY,calibrated=False,production_enabled=False)
    return dict(payload=payload,sha256=digest(payload))

def softmax(v):
    a=np.exp(v-np.max(v,axis=-1,keepdims=True))
    return a/a.sum(axis=-1,keepdims=True)

def allocate(shares,scores):
    raw=np.asarray(shares)*np.asarray(scores)[None,:,None]
    whole=np.floor(raw).astype(np.int32)
    remaining=np.asarray(scores)[None,:]-whole.sum(axis=-1)
    order=np.argsort(-(raw-whole),axis=-1,kind='stable')
    for i in range(4):
        np.put_along_axis(whole,order[:,:,i:i+1],
            np.take_along_axis(whole,order[:,:,i:i+1],axis=-1)+(remaining>i)[:,:,None],axis=-1)
    if not np.all(whole.sum(axis=-1)==np.asarray(scores)[None,:]):raise ValueError('PERIOD_TOTAL_CONSERVATION')
    return whole

def predict(model,home,away,rotations,scores):
    p=model['payload']
    if digest(p)!=model['sha256'] or p['format']!=VERSION or p['policy']!=POLICY:raise ValueError('PERIOD_MODEL_PIN')
    if len(scores)!=2 or any(not math.isfinite(s) or not 0<s<300 for s in scores):
        raise ValueError('PERIOD_INVALID_TEAM_TOTAL')
    a=design(p['teams'],p['players'],home,away,*rotations,True)
    b=design(p['teams'],p['players'],away,home,rotations[1],rotations[0],False)
    logits=np.asarray(p['center'])+np.asarray([a,b])@np.asarray(p['coefficients'])
    means=softmax(logits)*np.asarray(scores)[:,None]
    if not np.allclose(means.sum(axis=1),scores,rtol=0,atol=1e-8):raise ValueError('PERIOD_POINT_CONSERVATION')
    residual=np.asarray(p['paired_residuals'])
    rng=np.random.default_rng(POLICY['seed'])
    draws=residual[rng.integers(0,len(residual),size=POLICY['scenarios'])]
    paths=allocate(softmax(logits[None,:,:]+draws),np.rint(scores).astype(int))
    intervals={}
    for label,idx in [('1Q',[0]),('2Q',[1]),('3Q',[2]),('4Q',[3]),('1H',[0,1]),('2H',[2,3])]:
        vals=paths[:,:,idx].sum(axis=-1)
        intervals[label]={k:np.quantile(v,[.1,.5,.9]).tolist() for k,v in
            [('home',vals[:,0]),('away',vals[:,1]),('total',vals.sum(axis=1))]}
    return dict(quarters=means.T.tolist(),halves=[means[:,:2].sum(axis=1).tolist(),means[:,2:].sum(axis=1).tolist()],
        score=list(scores),total=sum(scores),conditional_80_intervals=intervals,
        scenarios=len(paths),conditional_fixed_rounded_team_scores=np.rint(scores).astype(int).tolist(),
        scenario_team_totals_conserved=True,intervals_calibrated=False,
        represented_minutes=[sum(v for pid,v in r.items() if pid in p['players']) for r in rotations])

def read(folder,prefix,pin):
    if not re.fullmatch('[0-9a-f]{64}',pin):raise ValueError('PERIOD_ASSET_PIN_FORMAT')
    path=folder/(prefix+pin+'.json')
    if path.is_symlink() or not path.is_file() or path.stat().st_size>8*1024*1024:raise ValueError('PERIOD_ASSET_UNAVAILABLE')
    w=json.loads(path.read_text())
    if digest(w['payload'])!=pin or w['sha256']!=pin:raise ValueError('PERIOD_ASSET_PIN')
    return w['payload']

def capture(folder,factor,pin,snapshot,control,candidate,now):
    fid=snapshot['fixture_id'];tip=snapshot['fixture_start_utc']
    if (digest(factor)!=pin or factor['format']!='NBA_ROTATION_PACE_EFFICIENCY_RESEARCH_V1'
        or factor['fixture_id']!=fid or factor['fixture_start_utc']!=tip
        or factor['original_snapshot_sha256']!=digest(snapshot)
        or not factor['generated_at_utc']<=now<tip-PREMATCH_MINIMUM_LEAD_SECONDS):
        raise Abstain('PERIOD_FACTOR_IDENTITY_OR_CLOCK')
    a,b=control['payload'],candidate['payload']
    if (a['season']!=snapshot['season'] or b['season']!=snapshot['season']
        or a['training_sha256']!=b['training_sha256'] or a['training_fixture_ids']!=b['training_fixture_ids']
        or not a['cutoff_utc']==b['cutoff_utc']<=now or fid in b['training_fixture_ids']):
        raise ValueError('PERIOD_TRAINING_BINDING')
    rotation=read(folder,'historical-five-',factor['rotation_sha256'])
    if (rotation['fixture_id']!=fid or rotation['original_snapshot_sha256']!=digest(snapshot)
        or not rotation['generated_at_utc']<=factor['generated_at_utc']):
        raise ValueError('PERIOD_ROTATION_BINDING')
    teams=[snapshot[s]['provider_id'] for s in ('home','away')]
    if teams!=[rotation['teams'][s]['team_id'] for s in ('home','away')]:raise ValueError('PERIOD_TEAM_BINDING')
    rotations=[rotation_from_summary(rotation['teams'][s]) for s in ('home','away')]
    if set(rotations[0])&set(rotations[1]):raise Abstain('PERIOD_DUPLICATE_PLAYER_TEAM')
    fm=read(folder,'factor-model-',factor['model_sha256'])
    if fid in fm['training_fixture_ids'] or fm['season']!=snapshot['season'] or fm['cutoff_utc']>factor['generated_at_utc']:
        raise ValueError('PERIOD_FACTOR_MODEL_BINDING')
    replay=factor_predict(dict(payload=fm,sha256=factor['model_sha256']),*teams,rotations)
    scores=[replay[s] for s in ('home','away')]
    if any(abs(replay[s]-factor['player_candidate'][s])>1e-6 for s in ('home','away','total')):
        raise ValueError('PERIOD_FACTOR_SCORE_REPLAY')
    return dict(format=VERSION,status='FORWARD_CONDITIONAL_PERIOD_RESEARCH',
        fixture_id=fid,fixture_start_utc=tip,generated_at_utc=now,original_snapshot_sha256=digest(snapshot),
        factor_sha256=pin,rotation_sha256=factor['rotation_sha256'],
        model_sha256=candidate['sha256'],control_sha256=control['sha256'],
        training_games=b['training_games'],player_terms=len(b['players']),
        team_allocation=predict(control,*teams,rotations,scores),
        player_allocation=predict(candidate,*teams,rotations,scores),
        uncertainty_scope='CONDITIONAL_ON_FIXED_TEAM_TOTALS_IN_SAMPLE_RESIDUAL_RESAMPLING',
        exposure_kind='FULL_GAME_MINUTES_PROXY_NOT_QUARTER_LINEUPS',
        calibrated=False,production_enabled=False,forecast_changed=False)

def main():
    from hybrid_engine.adaptive_data import FeatureStore
    from hybrid_engine.player_inputs import load_snapshot,file_sha256
    from ledger_reports import LedgerReports
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--data-directory',required=True)
    p.add_argument('--maximum',type=int,default=4);args=p.parse_args()
    if not 1<=args.maximum<=8:p.error('maximum must be 1..8')
    root=local_path(args.data_directory);folder=root/'player-shadow';ledger=root/'live-nba/nba-hybrid.sqlite'
    before=file_sha256(ledger);now=int(time.time())
    native=LedgerReports(ledger).read('NBA')
    if native['status']!='VERIFIED_LIVE_REPORT':raise ValueError('PERIOD_LEDGER_UNVERIFIED')
    rows={(r['fixture_id'],r['snapshot_sha256']):r for r in native['forecasts']}
    chosen={}
    for path in folder.glob('factor-score-*.json'):
        pin=path.stem.removeprefix('factor-score-');f=read(folder,'factor-score-',pin)
        key=(f['fixture_id'],f['original_snapshot_sha256']);row=rows.get(key)
        if not row or row['actual'] is not None:continue
        if not f['generated_at_utc']<=path.stat().st_mtime< f['fixture_start_utc']-PREMATCH_MINIMUM_LEAD_SECONDS or now>=f['fixture_start_utc']-PREMATCH_MINIMUM_LEAD_SECONDS:continue
        order=(f['generated_at_utc'],path.stat().st_mtime,pin)
        if key not in chosen or order<chosen[key][0]:chosen[key]=(order,f,pin,row)
    fits={};results=[]
    for _,f,pin,row in sorted(chosen.values(),key=lambda x:(x[1]['fixture_start_utc'],x[1]['fixture_id']))[:args.maximum]:
        try:
            snapshot=load_snapshot(ledger,row['fixture_id']);season=snapshot['season']
            if season not in fits:
                store=FeatureStore(root/'adaptive-v2/inputs',[root/'live-nba/assets'],
                    lambda *a,**k: (_ for _ in ()).throw(RuntimeError('NETWORK_FORBIDDEN')))
                cutoff=int(time.time());games,_=training_rows(store.cohort('NBA',int(season.split('/')[0]),cutoff),cutoff)
                fits[season]=(fit(games,cutoff,players_enabled=False),fit(games,cutoff,players_enabled=True))
            a,b=fits[season];result=capture(folder,f,pin,snapshot,a,b,int(time.time()))
            for model in (a,b):publish_json(folder/('period-model-'+model['sha256']+'.json'),model)
            if int(time.time())>=snapshot['fixture_start_utc']-PREMATCH_MINIMUM_LEAD_SECONDS:raise Abstain('PERIOD_PUBLICATION_WINDOW_CLOSED')
            h=digest(result);publish_json(folder/('period-score-'+h+'.json'),dict(payload=result,sha256=h))
        except (ValueError,KeyError,TypeError,OSError,np.linalg.LinAlgError) as exc:
            result=dict(status='BLOCKED',reason=str(exc) if str(exc).isupper() and len(str(exc))<100 else type(exc).__name__)
        results.append(dict(home=row['home'],away=row['away'],**result))
    print(json.dumps(dict(format=VERSION,results=results,source_calls=0,database_bytes_unchanged=before==file_sha256(ledger),production_changed=False),ensure_ascii=False,indent=2,allow_nan=False))

if __name__=='__main__':main()

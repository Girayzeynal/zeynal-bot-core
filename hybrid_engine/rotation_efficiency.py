"""NBA historical rotation, pace and efficiency research, separate from live scores.

Uses pinned historical normal-duration boxes, actual acquisition clocks, and
ridge associations. Individual causal/on-court defense is not measured.
"""
import argparse
from collections import Counter,defaultdict
import json
import math
import re
import time
import numpy as np
from core.team_identity import digest
from hybrid_engine.boxes import checked_stats,publish_json
from hybrid_engine.data import Abstain,local_path
from hybrid_engine.player_box_pilot import verified_box_rows
from hybrid_engine.historical_five_score import rotation_from_summary
from hybrid_engine.time_policy import PREMATCH_MINIMUM_LEAD_SECONDS

VERSION='NBA_ROTATION_PACE_EFFICIENCY_RESEARCH_V1'
POLICY=dict(maximum_players=450,minimum_training_boxes=30,
    pace_prior_team=4.,pace_prior_player=1.5,rating_prior_team=6.,rating_prior_player=3.)

def training_rows(cohort,cutoff):
    verified,excluded=verified_box_rows(cohort,cutoff)
    indexed={ (r['fixture_id'],r['box']['source_digest']):r['box']
        for versions in cohort for r in versions if r.get('box') is not None}
    out=[]
    for g in verified:
        b=indexed[(g['fixture_id'],g['source_sha256'])]
        stats=[checked_stats(b['teams'][s]) for s in ('home','away')]
        pace=sum(s['possessions_estimate'] for s in stats)/2
        if not 50<=pace<=150:
            excluded['PACE_OUTSIDE_RESEARCH_RANGE']=excluded.get('PACE_OUTSIDE_RESEARCH_RANGE',0)+1
            continue
        out.append(dict(g,pace=pace,ratings=[100*p/pace for p in g['score']]))
    return out,excluded

def design(teams,players,own,other,own_minutes,other_minutes,home):
    ix={t:i for i,t in enumerate(teams)};pix={p:i for i,p in enumerate(players)}
    n=len(teams);m=len(players);x=np.zeros(1+2*n+2*m)
    if own not in ix or other not in ix or own==other:raise Abstain('FACTOR_TEAM_NOT_IN_TRAINING')
    x[0]=int(home);x[1+ix[own]]=1;x[1+n+ix[other]]=1
    for offset,rotation in ((1+2*n,own_minutes),(1+2*n+m,other_minutes)):
        if (not 6<=len(rotation)<=30 or any(not math.isfinite(v) or not 0<=v<=48 for v in rotation.values())
                or abs(sum(rotation.values())-240)>3):
            raise ValueError('FACTOR_ROTATION_MINUTES')
        for p,v in rotation.items():
            if p in pix:x[offset+pix[p]]=v/48
    return x

def ridge(x,y,scale):
    # Dual solve keeps memory bounded even with two player exposure blocks.
    center=float(np.mean(y));variance=max(1.,float(np.var(y,ddof=1)))
    z=x*scale
    alpha=np.linalg.solve(z@z.T+variance*np.eye(len(y)),y-center)
    beta=scale*(z.T@alpha)
    if not np.isfinite(beta).all():raise ValueError('FACTOR_NONFINITE_FIT')
    return dict(center=center,coefficients=beta.tolist())

def fit(games,cutoff,*,players_enabled):
    if len(games)<POLICY['minimum_training_boxes'] or len(games)>1000:
        raise Abstain('FACTOR_TRAINING_BOXES_INSUFFICIENT_OR_OVER_BUDGET')
    if (type(cutoff) is not int or not 0<cutoff<=int(time.time()) or
        len({g['fixture_id'] for g in games})!=len(games) or
        len({(g['league'],g['season']) for g in games})!=1 or
        any(g['league']!='NBA' or not g['fixture_start_utc']<g['available_at_utc']<=cutoff
            for g in games)):
        raise ValueError('FACTOR_TRAINING_IDENTITY_OR_CLOCK')
    teams=sorted({g[s+'_team_id'] for g in games for s in ('home','away')})
    counts=Counter(p for g in games for r in g['minutes'].values() for p,v in r.items() if v>0)
    players=sorted(sorted(counts,key=lambda p:(-counts[p],p))[:POLICY['maximum_players']]) if players_enabled else []
    x=[];xp=[];y=[];yp=[]
    for g in games:
        pair=[]
        for j,(s,o) in enumerate((('home','away'),('away','home'))):
            v=design(teams,players,g[s+'_team_id'],g[o+'_team_id'],g['minutes'][s],g['minutes'][o],j==0)
            pair.append(v);x.append(v);y.append(g['ratings'][j])
        xp.append((pair[0]+pair[1])/2);yp.append(g['pace'])
    n=len(teams);m=len(players)
    ps=np.r_[1.,np.full(2*n,POLICY['pace_prior_team']),np.full(2*m,POLICY['pace_prior_player'])]
    rs=np.r_[3.,np.full(2*n,POLICY['rating_prior_team']),np.full(2*m,POLICY['rating_prior_player'])]
    payload=dict(format=VERSION,season=games[0]['season'],cutoff_utc=cutoff,
        teams=teams,players=players,training_games=len(games),
        training_fixture_ids=[g['fixture_id'] for g in games],
        training_sha256=digest(games),policy=POLICY,
        pace=ridge(np.array(xp),np.array(yp),ps),rating=ridge(np.array(x),np.array(y),rs),
        individual_causal_defense_identified=False,production_enabled=False)
    return dict(payload=payload,sha256=digest(payload))

def predict(wrapper,home,away,rotations):
    p=wrapper['payload']
    if digest(p)!=wrapper['sha256'] or p['format']!=VERSION:raise ValueError('FACTOR_MODEL_PIN')
    a=design(p['teams'],p['players'],home,away,*rotations,True)
    b=design(p['teams'],p['players'],away,home,rotations[1],rotations[0],False)
    def apply(k,x):
        return float(p[k]['center']+np.dot(x,p[k]['coefficients']))
    pace=apply('pace',(a+b)/2);ratings=[apply('rating',x) for x in (a,b)]
    if not 50<=pace<=150 or any(not 50<=v<=180 for v in ratings):
        raise Abstain('FACTOR_PREDICTION_OUTSIDE_RESEARCH_RANGE')
    scores=[pace*v/100 for v in ratings]
    return dict(estimated_shared_possessions=pace,home_points_per_100=ratings[0],
        away_points_per_100=ratings[1],home=scores[0],away=scores[1],total=sum(scores),
        represented_minutes=[sum(m for pid,m in r.items() if pid in p['players']) for r in rotations])

def compare(summary,snapshot,control,candidate,now):
    tip=snapshot['fixture_start_utc'];fid=snapshot['fixture_id']
    if (summary['format']!='NBA_HISTORICAL_MAIN_FIVE_V1'
        or summary['fixture_id']!=fid or summary['original_snapshot_sha256']!=digest(snapshot)
        or summary['fixture_start_utc']!=tip or summary['generated_at_utc']>now
        or not now<tip-PREMATCH_MINIMUM_LEAD_SECONDS):
        raise Abstain('FACTOR_FORECAST_BINDING_OR_CLOCK')
    a,b=control['payload'],candidate['payload']
    if (a['season']!=snapshot['season'] or b['season']!=snapshot['season']
        or a['training_sha256']!=b['training_sha256'] or a['cutoff_utc']!=b['cutoff_utc']
        or a['cutoff_utc']>now or fid in a['training_fixture_ids'] or fid in b['training_fixture_ids']):
        raise ValueError('FACTOR_TRAINING_BINDING')
    teams=[snapshot[s]['provider_id'] for s in ('home','away')]
    if teams!=[summary['teams'][s]['team_id'] for s in ('home','away')]:
        raise ValueError('FACTOR_TEAM_BINDING')
    rotation=[rotation_from_summary(summary['teams'][s]) for s in ('home','away')]
    if set(rotation[0])&set(rotation[1]):raise Abstain('FACTOR_PLAYER_ON_BOTH_TEAMS')
    base=predict(control,*teams,rotation);player=predict(candidate,*teams,rotation)
    return dict(format=VERSION,status='FORWARD_FACTOR_RESEARCH',fixture_id=fid,
        fixture_start_utc=tip,generated_at_utc=now,original_snapshot_sha256=digest(snapshot),
        rotation_sha256=digest(summary),model_sha256=candidate['sha256'],control_sha256=control['sha256'],
        original_prediction=snapshot['prediction'],team_control=base,player_candidate=player,
        training_games=b['training_games'],player_terms=len(b['players']),
        pace_delta=player['estimated_shared_possessions']-base['estimated_shared_possessions'],
        rating_delta=[player[k]-base[k] for k in ('home_points_per_100','away_points_per_100')],
        possession_kind='BOX_ESTIMATE_NOT_MEASURED_PBP',defense_kind='OPPONENT_MINUTE_ASSOCIATION_NOT_CAUSAL',
        lineup_verified=False,calibrated=False,production_enabled=False,forecast_changed=False)

def main():
    from hybrid_engine.adaptive_data import FeatureStore
    from hybrid_engine.player_inputs import load_snapshot,file_sha256
    from ledger_reports import LedgerReports
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--data-directory',required=True)
    p.add_argument('--maximum',type=int,default=4);args=p.parse_args()
    if not 1<=args.maximum<=8:p.error('maximum must be 1..8')
    root=local_path(args.data_directory);folder=root/'player-shadow';ledger=root/'live-nba/nba-hybrid.sqlite'
    before=file_sha256(ledger);now=int(time.time())
    live=LedgerReports(ledger).read('NBA')
    if live['status']!='VERIFIED_LIVE_REPORT':raise ValueError('FACTOR_LEDGER_UNVERIFIED')
    groups=defaultdict(list)
    for row in live['forecasts']:groups[row['fixture_id']].append(row)
    saved=defaultdict(list)
    for path in folder.glob('historical-five-*.json'):
        if not re.fullmatch(r'historical-five-[0-9a-f]{64}\.json',path.name):continue
        if path.is_symlink() or path.stat().st_size>8*1024*1024:raise ValueError('FACTOR_ROTATION_FILE')
        w=json.loads(path.read_text());s=w['payload'];pin=digest(s)
        if pin!=w['sha256'] or path.stem!='historical-five-'+pin:raise ValueError('FACTOR_ROTATION_PIN')
        if not s['generated_at_utc']<=path.stat().st_mtime< s['fixture_start_utc']-PREMATCH_MINIMUM_LEAD_SECONDS:continue
        if s['status']=='HISTORICAL_ROTATION_READY':saved[s['fixture_id']].append(s)
    rows=sorted((v[0] for fid,v in groups.items() if len(v)==1 and fid in saved
        and v[0]['actual'] is None and now<v[0]['fixture_start_utc']-PREMATCH_MINIMUM_LEAD_SECONDS),
        key=lambda r:r['fixture_start_utc'])[:args.maximum]
    fits={};results=[]
    for row in rows:
        try:
            snapshot=load_snapshot(ledger,row['fixture_id']);season=snapshot['season']
            if season not in fits:
                storage=root/'adaptive-v2/inputs'
                store=FeatureStore(storage,[root/'live-nba/assets'],
                    lambda *a,**k: (_ for _ in ()).throw(RuntimeError('NETWORK_FORBIDDEN')))
                cutoff=int(time.time());cohort=store.cohort('NBA',int(season.split('/')[0]),cutoff)
                games,excluded=training_rows(cohort,cutoff)
                games=[g for g in games if g['season']==season]
                fits[season]=(fit(games,cutoff,players_enabled=False),fit(games,cutoff,players_enabled=True))
            control,candidate=fits[season]
            summary=min(saved[row['fixture_id']],key=lambda s:(s['generated_at_utc'],digest(s)))
            result=compare(summary,snapshot,control,candidate,int(time.time()))
            for model in (control,candidate):
                publish_json(folder/('factor-model-'+model['sha256']+'.json'),model)
            if int(time.time())>=snapshot['fixture_start_utc']-PREMATCH_MINIMUM_LEAD_SECONDS:
                raise Abstain('FACTOR_PUBLICATION_WINDOW_CLOSED')
            pin=digest(result);publish_json(folder/('factor-score-'+pin+'.json'),dict(payload=result,sha256=pin))
            result.pop('original_prediction')
        except (ValueError,KeyError,TypeError,OSError,np.linalg.LinAlgError) as exc:
            result=dict(status='BLOCKED',reason=str(exc) if str(exc).isupper() and len(str(exc))<100 else type(exc).__name__)
        results.append(dict(home=row['home'],away=row['away'],**result))
    print(json.dumps(dict(format=VERSION,results=results,source_calls=0,
        database_bytes_unchanged=before==file_sha256(ledger),production_changed=False),
        ensure_ascii=False,indent=2,allow_nan=False))

if __name__=='__main__':main()

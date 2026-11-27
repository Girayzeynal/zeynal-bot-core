"""Independent NBA past-six main rotation, not an announced starting five.

Uses authenticated original feature cut and actual historical box scores.
No injury index, PDF, availability probabilities, or target outcome needed.
Research sidecar only, no mutation of the first forecast.
"""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
import time

from core.team_identity import digest
from hybrid_engine.boxes import collect_boxes,publish_json
from hybrid_engine.data import Abstain,local_path
from hybrid_engine.player_minutes import historical_minutes
from hybrid_engine.prediction_audit import audit_snapshot
from hybrid_engine.time_policy import PREMATCH_MINIMUM_LEAD_SECONDS


def summarize_team(boxes,team,season,*,now,target_id):
    recent=[]
    for b in boxes:
        if team not in (b['home_team_id'],b['away_team_id']):continue
        if (b['fixture_id']==target_id or b['league']!='NBA' or b['season']!=season
                or b['source_digest']!=digest(b['source'])
                or not b['fixture_start_utc']<max(b['source']['observed_at_utc'],
                    b['source']['ingested_at_utc'])<=now):
            raise ValueError('HISTORICAL_FIVE_SOURCE_OR_CLOCK')
        if b['scope']=='FINAL_WITH_OT' and b['regulation_eligible'] is True:recent.append(b)
    if len({b['fixture_id'] for b in recent})!=len(recent):
        raise ValueError('HISTORICAL_FIVE_DUPLICATE')
    recent=sorted(recent,key=lambda b:(b['fixture_start_utc'],b['fixture_id']))[-6:]
    if len(recent)!=6 or now-recent[-1]['fixture_start_utc']>14*86400:
        raise Abstain('HISTORICAL_FIVE_SIX_FRESH_BOXES_REQUIRED')
    data=defaultdict(lambda:dict(minutes=0.,points=0,played=0,points_missing=0,listed=0,starts=0))
    for box in recent:
        rows=[p for p in box['players'] if p['team_id']==team]
        ids=[p['player_id'] for p in rows]
        if len(ids)!=len(set(ids)) or not 6<=len(ids)<=30 or any(
            not isinstance(p,str) or not re.fullmatch('[0-9]{1,15}',p) for p in ids):
            raise ValueError('HISTORICAL_FIVE_PLAYER_IDENTITY')
        minutes=[historical_minutes(p) for p in rows]
        if abs(sum(minutes)-240)>3 or sum(m>0 for m in minutes)<6:
            raise Abstain('HISTORICAL_FIVE_TEAM_MINUTES_INCOMPLETE')
        for p,m in zip(rows,minutes):
            v=data[p['player_id']];v['listed']+=1;v['minutes']+=m
            v['played']+=int(m>0);v['starts']+=int(p.get('historical_starter') is True)
            points=p.get('points')
            if type(points) is int and points>=0:v['points']+=points
            elif p.get('did_not_play') is not True:v['points_missing']+=1
    ranked=[]
    for pid,v in data.items():
        if v['minutes']<=0:continue
        points=v['points']/6 if not v['points_missing'] else None
        ranked.append(dict(player_id=pid,average_minutes=v['minutes']/6,
            average_points=points,points_per_minute=v['points']/v['minutes'] if points is not None else None,
            games_played=v['played'],games_listed=v['listed'],historical_starts=v['starts']))
    ranked.sort(key=lambda v:(-v['average_minutes'],v['player_id']))
    if len(ranked)<6:raise Abstain('HISTORICAL_FIVE_REPLACEMENTS_UNAVAILABLE')
    return dict(team_id=team,history_fixture_ids=[b['fixture_id'] for b in recent],
        history_box_sha256=[digest(b) for b in recent],latest_history_utc=recent[-1]['fixture_start_utc'],
        main_five=ranked[:5],bench=ranked[5:],
        mean_team_minutes=sum(v['average_minutes'] for v in ranked),
        current_roster_verified=False,confirmed_starting_five=False,
        denominator='SIX_TEAM_GAMES_NOT_ONLY_PLAYER_APPEARANCES')


def collect_historical(snapshot,assets,directory,*,box_collector=collect_boxes):
    root=local_path(directory); now=int(time.time());before=digest(snapshot)
    if snapshot['league']!='NBA' or now>=snapshot['fixture_start_utc']-PREMATCH_MINIMUM_LEAD_SECONDS:
        raise Abstain('HISTORICAL_FIVE_PREMATCH_WINDOW_CLOSED')
    audit_snapshot(snapshot,assets)
    ref=snapshot['input_asset']; asset=local_path(Path(assets)/ref['file'])
    if asset.parent!=local_path(assets):raise ValueError('HISTORICAL_FIVE_ASSET_PATH')
    cut=json.loads(asset.read_text())
    if digest(cut)!=ref['sha256']:raise ValueError('HISTORICAL_FIVE_ASSET_PIN')
    teams={s:snapshot[s]['provider_id'] for s in ('home','away')}
    targets={}
    for team in teams.values():
        rows=[r for r in cut['history'] if team in (r['home_team_id'],r['away_team_id'])
              and r['fixture_id']!=snapshot['fixture_id'] and r['league']=='NBA'
              and r['season']==snapshot['season'] and r['fixture_start_utc']<now
              and r.get('periods') and len(r['periods']['home'])==len(r['periods']['away'])==4]
        recent=sorted(rows,key=lambda r:(r['fixture_start_utc'],r['fixture_id']))[-6:]
        if len(recent)!=6:raise Abstain('HISTORICAL_FIVE_SIX_ORIGINAL_CUT_GAMES_REQUIRED')
        for r in recent:targets[r['fixture_id']]=r
    root.mkdir(parents=True,exist_ok=True)
    boxes_dir=root/'past-boxes'
    _,result=box_collector([[r] for r in targets.values()],boxes_dir,workers=1,interval=.1)
    boxes=result['games']; finished=int(time.time())
    if result['failures'] or {b['fixture_id'] for b in boxes}!=set(targets):
        raise Abstain('HISTORICAL_FIVE_INCOMPLETE_PAST_BOXES')
    if finished>=snapshot['fixture_start_utc']-PREMATCH_MINIMUM_LEAD_SECONDS:
        raise Abstain('HISTORICAL_FIVE_PREMATCH_WINDOW_CLOSED')
    output=dict(format='NBA_HISTORICAL_MAIN_FIVE_V1',status='HISTORICAL_ROTATION_READY',
        fixture_id=snapshot['fixture_id'],fixture_start_utc=snapshot['fixture_start_utc'],
        original_snapshot_sha256=before,original_cut_sha256=ref['sha256'],
        generated_at_utc=finished,history_scope='LAST_SIX_REGULATION_GAMES_IN_ORIGINAL_FROZEN_CUT',
        teams={s:summarize_team(boxes,t,snapshot['season'],now=finished,target_id=snapshot['fixture_id'])
               for s,t in teams.items()},injury_source_calls=0,lineup_verified=False,
        player_score_effect_applied=False,production_enabled=False,forecast_changed=False)
    if digest(snapshot)!=before:raise ValueError('ORIGINAL_FORECAST_MUTATED')
    pin=digest(output)
    publish_json(root/('historical-five-'+pin+'.json'),dict(payload=output,sha256=pin))
    return dict(output,sha256=pin)


def main():
    from hybrid_engine.player_inputs import load_snapshot,file_sha256
    from ledger_reports import LedgerReports
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-directory',required=True)
    p.add_argument('--maximum',type=int,default=4)
    args=p.parse_args()
    if not 1<=args.maximum<=8:p.error('--maximum must be 1..8')
    root=local_path(args.data_directory);ledger=root/'live-nba/nba-hybrid.sqlite'
    before=file_sha256(ledger);now=int(time.time())
    report=LedgerReports(ledger).read('NBA')
    if report['status']!='VERIFIED_LIVE_REPORT':raise ValueError('HISTORICAL_FIVE_LEDGER_UNVERIFIED')
    grouped=defaultdict(list)
    for r in report['forecasts']:grouped[r['fixture_id']].append(r)
    rows=sorted((v[0] for v in grouped.values() if len(v)==1 and v[0]['actual'] is None
                 and now+900<=v[0]['fixture_start_utc']<=now+48*3600),
                key=lambda r:(r['fixture_start_utc'],r['fixture_id']))
    results=[]
    for row in rows[:args.maximum]:
        try:
            out=collect_historical(load_snapshot(ledger,row['fixture_id']),root/'live-nba/assets',root/'player-shadow')
        except (ValueError,KeyError,TypeError,OSError) as exc:
            reason=str(exc);out=dict(status='BLOCKED',reason=reason if reason.replace('_','').isalnum() and len(reason)<=100 else type(exc).__name__)
        results.append(dict(home=row['home'],away=row['away'],**out))
    print(json.dumps(dict(format='NBA_HISTORICAL_FIVE_BATCH_V1',eligible=len(rows),
        ready=sum(r['status']=='HISTORICAL_ROTATION_READY' for r in results),
        results=results,database_bytes_unchanged=file_sha256(ledger)==before,
        injury_source_calls=0,production_changed=False),ensure_ascii=False,indent=2,allow_nan=False))

if __name__=='__main__':main()

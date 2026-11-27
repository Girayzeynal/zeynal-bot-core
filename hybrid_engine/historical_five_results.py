"""Read-only evaluation of first local historical player score research receipts."""
import argparse
from collections import Counter,defaultdict
import json
import math
import re
import time
from core.team_identity import digest
from hybrid_engine.data import local_path
from hybrid_engine.time_policy import PREMATCH_MINIMUM_LEAD_SECONDS

KINDS={'HISTORICAL_FIVE_PLAYER_SCORE_RESEARCH_V1':'CONTRAST64',
       'HISTORICAL_FIVE_BROAD_PLAYER_SCORE_RESEARCH_V1':'BROAD_RIDGE'}
NAMES=('original_prediction','team_control','player_candidate')

def metrics(rows):
    result={}
    for name in NAMES:
        e=[(r[name]['home']-r['actual'][0],r[name]['away']-r['actual'][1]) for r in rows]
        if not e:continue
        n=len(e);totals=[a+b for a,b in e]
        result[name]=dict(n=n,total_mae=sum(map(abs,totals))/n,
            total_rmse=math.sqrt(sum(x*x for x in totals)/n),bias=sum(totals)/n,
            team_mae=sum(abs(a)+abs(b) for a,b in e)/(2*n),
            margin_mae=sum(abs(a-b) for a,b in e)/n)
    return result

def evaluate(root,ledger,*,now=None):
    from ledger_reports import LedgerReports
    now=int(time.time()) if now is None else now
    if type(now) is not int or now>int(time.time()):raise ValueError('NO_FUTURE_REVIEW_CLOCK')
    root=local_path(root);ledger=local_path(ledger)
    native=LedgerReports(ledger).read('NBA')
    if native['status']!='VERIFIED_LIVE_REPORT':raise ValueError('HISTORICAL_SCORE_LEDGER_NOT_VERIFIED')
    originals={(r['fixture_id'],r['snapshot_sha256']):r for r in native['forecasts']}
    records=defaultdict(list);exclusions=Counter()
    def read(path,pin):
        if path.is_symlink() or not path.is_file() or path.stat().st_size>8*1024*1024:
            raise ValueError('ARCHIVE_FILE_UNAVAILABLE')
        w=json.loads(path.read_text());p=w['payload']
        if digest(p)!=w['sha256'] or w['sha256']!=pin:raise ValueError('ARCHIVE_PIN')
        return p
    for path in root.glob('historical-score-*.json'):
        m=re.fullmatch(r'historical-score-(broad-)?([0-9a-f]{64})\.json',path.name)
        if not m:continue
        try:
            p=read(path,m[2]);kind=KINDS[p['format']]
            if bool(m[1])!=(kind=='BROAD_RIDGE'):raise ValueError('FORMAT_NAME')
            row=originals[(p['fixture_id'],p['original_snapshot_sha256'])]
            tip=row['fixture_start_utc'];generated=p['generated_at_utc']
            # Local filesystem receipt time is not an external timestamp attestation.
            modified=path.stat().st_mtime
            if not (p['fixture_start_utc']==tip and
                row['prediction_generated_at_utc']<=generated<=now and
                generated<=modified<tip-PREMATCH_MINIMUM_LEAD_SECONDS and
                generated<tip-PREMATCH_MINIMUM_LEAD_SECONDS):
                raise ValueError('LOCAL_PUBLICATION_CLOCK')
            if p['production_enabled'] or p['forecast_changed']:raise ValueError('RESEARCH_SCOPE')
            rotation=read(root/('historical-five-'+p['rotation_sha256']+'.json'),p['rotation_sha256'])
            model=read(root/('historical-score-model-'+p['model_sha256']+'.json'),p['model_sha256'])
            control=read(root/('historical-score-control-'+p['control_sha256']+'.json'),p['control_sha256'])
            if (rotation['fixture_id']!=p['fixture_id'] or rotation['original_snapshot_sha256']!=p['original_snapshot_sha256']
                or not model['cutoff_utc']==control['cutoff_utc']==p['training_cutoff_utc']<=rotation['generated_at_utc']<=generated
                or model['training_sha256']!=control['training_sha256'] or model['training_sha256']!=p['training_sha256']
                or p['fixture_id'] in model['training_fixture_ids'] or model['training_fixture_ids']!=control['training_fixture_ids']):
                raise ValueError('MODEL_ROTATION_BINDING')
            if any(abs(p['original_prediction'][s]-row['prediction'][i])>1e-6 for i,s in enumerate(('home','away'))):
                raise ValueError('ORIGINAL_PREDICTION_MISMATCH')
            from hybrid_engine.historical_five_score import rotation_from_summary
            from hybrid_engine.player_box_pilot import projected_pair
            teams=[rotation['teams'][s]['team_id'] for s in ('home','away')]
            rotations=[rotation_from_summary(rotation['teams'][s]) for s in ('home','away')]
            for name,fit in (('team_control',control),('player_candidate',model)):
                pair=projected_pair(fit,*teams,*rotations)
                if any(not math.isfinite(v) or abs(v-p[name][s])>1e-6 for v,s in zip(pair,('home','away'))):
                    raise ValueError('SCORE_REPLAY_MISMATCH')
            records[(kind,row['season'],p['fixture_id'])].append((generated,modified,m[2],p,row))
        except (ValueError,KeyError,TypeError,OSError,IndexError) as e:
            reason=str(e);exclusions[reason if reason.isupper() and len(reason)<100 else type(e).__name__]+=1
    groups=defaultdict(lambda:dict(settled=[],pending=0,duplicates=0));detail=[]
    for (kind,season,fid),items in sorted(records.items()):
        g=groups[(kind,season)];g['duplicates']+=len(items)-1
        _,_,pin,p,row=min(items,key=lambda r:r[:3])
        label=row.get('label_available_utc')
        if row['actual'] is None or type(label) is not int or label>now:
            g['pending']+=1;continue
        if label<=row['fixture_start_utc']:
            exclusions['FINAL_CLOCK']+=1;continue
        actual=row['actual'];q=dict(p,actual=actual)
        g['settled'].append(q)
        detail.append(dict(kind=kind,fixture_id=fid,home=row['home'],away=row['away'],actual=actual,
            original=p['original_prediction']['total'],control=p['team_control']['total'],candidate=p['player_candidate']['total'],receipt=pin))
    return dict(format='HISTORICAL_FIVE_FORWARD_LOCAL_AUDIT_V1',groups=[
        dict(kind=k[0],season=k[1],matched=len(v['settled']),pending=v['pending'],duplicate_receipts=v['duplicates'],
             metrics=metrics(v['settled'])) for k,v in sorted(groups.items())],
        exclusions=dict(exclusions),results=detail,publication_evidence='LOCAL_FILE_CLOCK_NOT_EXTERNAL_ATTESTATION',
        production_enabled=False,calibrated=False,original_archive_read_only=True)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--data-directory',required=True)
    a=p.parse_args();root=local_path(a.data_directory)
    print(json.dumps(evaluate(root/'player-shadow',root/'live-nba/nba-hybrid.sqlite'),ensure_ascii=False,indent=2,allow_nan=False))
if __name__=='__main__':main()

"""Explicit offline collection of prospective NBA player inputs; ledger is read-only."""
import argparse
import json
from pathlib import Path
import sqlite3
import time

from core.team_identity import digest
from hybrid_engine.boxes import collect_boxes,publish_json
from hybrid_engine.current_roster import CurrentRosterReview,context_for,PREFIX,roster_ids
from hybrid_engine.data import Abstain,local_path
from hybrid_engine.player_minutes import MinutesArchive,projection
from hybrid_engine.prediction_audit import audit_snapshot
from ledger_reports import LedgerReports
from live_analysis_ledger import LiveAnalysisLedger


def load_snapshot(ledger,fixture_id):
    path=local_path(ledger)
    report=LedgerReports(path).read('NBA',fixture_id)
    rows=report.get('forecasts',[])
    if len(rows)!=1: raise ValueError('EXACTLY_ONE_ARCHIVED_NBA_MODEL_REQUIRED')
    row=rows[0]
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=.2) as db:
        db.execute('PRAGMA query_only=ON')
        raw,pin=db.execute('SELECT payload,sha256 FROM live_analysis_snapshots WHERE league=? AND fixture_id=? AND model_digest=?',
            ('NBA',row['fixture_id'],row['model_digest'])).fetchone()
    return LiveAnalysisLedger._decode(raw,pin,expected=('NBA',row['fixture_id'],row['model_digest']))


def collect(snapshot,assets,directory,*,reviewer=None,box_collector=collect_boxes):
    root=local_path(directory); root.mkdir(parents=True,exist_ok=True)
    now=int(time.time()); before=digest(snapshot)
    result=dict(format='PLAYER_INPUT_COLLECTION_V1',fixture_id=snapshot['fixture_id'],
        provider_fixture_ids=snapshot['provider_fixture_ids'],evaluated_at_utc=now,status='BLOCKED',reason=None,
        original_snapshot_sha256=before,projection=None,forecast_changed=False,online_training=False,
        actual_telegram_delivery_verified=False,production_changed=False)
    try:
        prior=[p for p in MinutesArchive(root/'minutes').first() if p['projection']['payload']['fixture_id']==snapshot['fixture_id']]
        if prior:
            old=prior[0]
            if old['projection']['payload']['original_snapshot_sha256']!=before:
                raise ValueError('PLAYER_MINUTES_LINKED_TO_DIFFERENT_ORIGINAL_FORECAST')
            result.update(status='EXISTING_MINUTES_REPLAY',projection=old['projection']['sha256'],
                first_archived_at_utc=old['first_archived_at_utc'],new_record=False)
            return result
        if now>=snapshot['fixture_start_utc']: raise Abstain('MATCH_STARTED_NO_PLAYER_INPUT_BACKFILL')
        audit_snapshot(snapshot,assets)
        ref=snapshot['input_asset']; path=local_path(Path(assets)/ref['file'])
        if path.parent!=local_path(assets): raise ValueError('PLAYER_INPUT_ASSET_PATH')
        cut=json.loads(path.read_text())
        if digest(cut)!=ref['sha256']: raise ValueError('PLAYER_INPUT_ASSET_PIN')
        context=context_for(snapshot)
        service=reviewer or CurrentRosterReview(root/'current-roster')
        review=service.review(context)
        if review['status']!='CURRENT_SOURCE_OBSERVATIONS': raise Abstain('CURRENT_ROSTER_SOURCE_REVIEW_REQUIRED')
        rosters={}; deadline=time.monotonic()+30
        for side in ('home','away'):
            team=context[side]['provider_id']
            r=service._get(PREFIX+'teams/'+team+'/roster?season='+context['season'][-4:],deadline)
            document=json.loads(r['body'])
            ids=roster_ids(document,dict(id=team,name=context[side]['official_name']),context['season'])
            if len(ids)!=len(document['athletes']): raise Abstain('AMBIGUOUS_ROSTER_DIRECTORY')
            rosters[side]=dict(team_id=team,season=context['season'],players=sorted(ids.values()),
                observed_at_utc=r['observed_at_utc'],source_sha256=r['body_sha256'])
        targets={}
        for side in ('home','away'):
            team=context[side]['provider_id']
            history=[r for r in cut['history'] if team in (r['home_team_id'],r['away_team_id']) and
                r['fixture_id']!=context['fixture_id'] and r['fixture_start_utc']<now and
                r['periods'] and len(r['periods']['home'])==len(r['periods']['away'])==4]
            history=sorted(history,key=lambda r:(r['fixture_start_utc'],r['fixture_id']))[-6:]
            if len(history)<6: raise Abstain('SIX_PREVIOUS_REGULATION_GAMES_REQUIRED')
            for row in history: targets[row['fixture_id']]=row
        box_dir=root/'past-boxes'; box_dir.mkdir(exist_ok=True)
        _,collected=box_collector([[r] for r in targets.values()],box_dir,workers=1,interval=.1)
        boxes,failures=collected['games'],collected['failures']
        if failures or len(boxes)!=len(targets): raise Abstain('INCOMPLETE_NATIVE_PAST_PLAYER_BOXES')
        generated=int(time.time())
        packet=projection(context,review,rosters,boxes,generated_at_utc=generated)
        bundle=dict(format='PLAYER_MINUTES_INPUT_WITNESSES_V1',context=context,review=review,rosters=rosters,
            boxes=boxes,original_cut_sha256=ref['sha256'],projection_sha256=packet['sha256'])
        witness=root/('inputs-'+packet['sha256']+'.json')
        publish_json(witness,dict(payload=bundle,sha256=digest(bundle)))
        publication,created=MinutesArchive(root/'minutes').record(packet)
        result.update(status='PROSPECTIVE_MINUTES_ARCHIVED',reason=None,projection=packet['sha256'],
            first_archived_at_utc=publication['first_archived_at_utc'],new_record=created,
            source_input_sha256=digest(bundle))
    except (ValueError,KeyError,TypeError,OSError,sqlite3.Error) as exc:
        reason=str(exc)
        result['reason']=reason if reason.replace('_','').isalnum() and len(reason)<=100 else 'PLAYER_INPUT_SOURCE_OR_ARCHIVE_UNAVAILABLE'
    if digest(snapshot)!=before: raise ValueError('ORIGINAL_FORECAST_MUTATED')
    result['completed_at_utc']=int(time.time())
    publish_json(root/('collection-'+digest(result)+'.json'),dict(payload=result,sha256=digest(result)))
    return result


def validate_witness(publication,directory):
    p=publication['projection']; path=local_path(directory)/('inputs-'+p['sha256']+'.json')
    if path.stat().st_size>16*1024*1024: raise ValueError('PLAYER_WITNESS_SIZE_BUDGET')
    w=json.loads(path.read_text()); b=w['payload']
    if digest(b)!=w['sha256'] or b['format']!='PLAYER_MINUTES_INPUT_WITNESSES_V1' or b['projection_sha256']!=p['sha256']:
        raise ValueError('PLAYER_INPUT_WITNESS_PIN')
    replay=projection(b['context'],b['review'],b['rosters'],b['boxes'],generated_at_utc=p['payload']['generated_at_utc'])
    if replay!=p: raise ValueError('PLAYER_MINUTES_REPLAY_CONFLICT')
    return p['payload']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger',required=True); parser.add_argument('--assets-directory',required=True)
    parser.add_argument('--fixture-id',required=True); parser.add_argument('--output-directory',required=True)
    args=parser.parse_args(); ledger=local_path(args.ledger)
    before=__import__('hashlib').sha256(ledger.read_bytes()).hexdigest()
    snapshot=load_snapshot(ledger,args.fixture_id)
    report=collect(snapshot,local_path(args.assets_directory),args.output_directory)
    report['database_bytes_unchanged']=__import__('hashlib').sha256(ledger.read_bytes()).hexdigest()==before
    print(json.dumps(report,sort_keys=True))


if __name__=='__main__': main()

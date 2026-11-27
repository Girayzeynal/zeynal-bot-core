"""Explicit offline collection of prospective NBA player inputs; ledger is read-only."""
import argparse
from collections import Counter,defaultdict
import hashlib
import heapq
import json
import os
import re
from pathlib import Path
import sqlite3
import time

from core.team_identity import digest
from hybrid_engine.boxes import collect_boxes,publish_json
from hybrid_engine.current_roster import CurrentRosterReview,context_for,PREFIX,roster_ids,review_diagnostics
from hybrid_engine.data import Abstain,local_path
from hybrid_engine.player_minutes import MinutesArchive,projection,official_available
from hybrid_engine.conditional_rotation import conditional_rotation,BLOCKS
from hybrid_engine.time_policy import PREMATCH_MINIMUM_LEAD_SECONDS
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


def rotation_coverage_diagnostics(context,review,rosters,boxes,now):
    """Explain unknown players in the last six boxes; never infer minutes.

    A new roster member can be valid without appearing in this team's six
    historical boxes. This diagnostic exposes the identity gap without
    assuming the player will sit or fabricating a transferable minute prior.
    """
    result={}
    for side in ('home','away'):
        team=context[side]['provider_id']
        eligible=sorted((box for box in boxes if
            box.get('league')=='NBA' and box.get('season')==context['season'] and
            team in (box.get('home_team_id'),box.get('away_team_id')) and
            box.get('scope')=='FINAL_WITH_OT' and box.get('regulation_eligible') is True and
            box.get('fixture_start_utc',0)<now),
            key=lambda box:(box['fixture_start_utc'],box['fixture_id']))[-6:]
        previously_listed={p['player_id'] for box in eligible for p in box['players']
                           if p.get('team_id')==team}
        records={}
        for row in review.get('records',[]):
            if row.get('team_id')==team and row.get('player_id'):
                records.setdefault(row['player_id'],[]).append(row)
        two_source_out={pid for pid,items in records.items() if
            {r.get('status') for r in items} <= {'Out','Suspended'} and
            {'ESPN','NBA_OFFICIAL_PDF'} <= {r.get('source') for r in items}}
        unknown=sorted(set(rosters[side]['players'])-previously_listed-two_source_out)
        known_other_team={p['player_id'] for box in boxes for p in box['players'] if p.get('team_id')!=team}
        earlier_team={p['player_id'] for box in boxes if box not in eligible for p in box['players']
                      if p.get('team_id')==team}
        result[side]=dict(past_regulation_games=len(eligible),
            missing_history_player_ids=unknown,missing_history_count=len(unknown),
            observed_older_same_team_player_ids=sorted(set(unknown)&earlier_team),
            observed_other_team_player_ids=sorted(set(unknown)&known_other_team),
            no_native_row_in_examined_boxes_ids=sorted(set(unknown)-earlier_team-known_other_team),
            actual_minutes_assumed=False,unverified_players_given_zero_minutes=False)
    return result


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
        # Match the isolated Telegram source policy. Public CDN access is
        # bounded by CurrentRosterReview; no authorization or rate-limit bypass.
        service=reviewer or CurrentRosterReview(
            root/'current-roster',report_archive=root.parent/'official-reports',
            bounded_public_pdf_fallback=True)
        review=service.review(context)
        result['roster_diagnostics']=review_diagnostics(review)
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
        targets={}; older_targets={}
        for side in ('home','away'):
            team=context[side]['provider_id']
            history=[r for r in cut['history'] if team in (r['home_team_id'],r['away_team_id']) and
                r['fixture_id']!=context['fixture_id'] and r['fixture_start_utc']<now and
                r['periods'] and len(r['periods']['home'])==len(r['periods']['away'])==4]
            history=sorted(history,key=lambda r:(r['fixture_start_utc'],r['fixture_id']))[-12:]
            if len(history)<6: raise Abstain('SIX_PREVIOUS_REGULATION_GAMES_REQUIRED')
            older_targets[side]=[row for row in history[:-6] if now-row['fixture_start_utc']<=30*86400]
            for row in history[-6:]: targets[row['fixture_id']]=row
        box_dir=root/'past-boxes'; box_dir.mkdir(exist_ok=True)
        _,collected=box_collector([[r] for r in targets.values()],box_dir,workers=1,interval=.1)
        boxes,failures=collected['games'],collected['failures']
        if failures or len(boxes)!=len(targets): raise Abstain('INCOMPLETE_NATIVE_PAST_PLAYER_BOXES')
        generated=int(time.time())
        try:
            try:
                packet=projection(context,review,rosters,boxes,generated_at_utc=generated)
            except Abstain as already_blocked:
                if str(already_blocked)!='CURRENT_PLAYER_WITHOUT_PRIOR_ROTATION_HISTORY':
                    raise
                diagnosis=rotation_coverage_diagnostics(context,review,rosters,boxes,generated)
                available={
                    row['player_id'] for row in review['records']
                    if row.get('player_id') and official_available(review,row,generated)
                }
                needed={r['fixture_id']:r for side,older in older_targets.items()
                        if available.intersection(diagnosis[side]['missing_history_player_ids'])
                        for r in older if r['fixture_id'] not in targets}
                if not needed or generated>=context['fixture_start_utc']-PREMATCH_MINIMUM_LEAD_SECONDS:
                    raise
                _,extra=box_collector([[r] for r in needed.values()],box_dir,workers=1,interval=.1)
                boxes=[*boxes,*extra['games']]
                generated=int(time.time())
                packet=projection(context,review,rosters,boxes,generated_at_utc=generated)
        except Abstain as exc:
            if str(exc) in BLOCKS:
                # Do not throw away verified past boxes when availability is
                # unavailable. Keep counterfactual research outside MinutesArchive.
                try:
                    scenario=conditional_rotation(context,review,rosters,boxes,now=int(time.time()))
                    pin=digest(scenario)
                    publish_json(root/('conditional-rotation-'+pin+'.json'),dict(payload=scenario,sha256=pin))
                    result['conditional_rotation']=dict(status=scenario['status'],sha256=pin,
                        training_eligible=False,score_computed=False,
                        teams={s:dict(unseen_players=len(v['unseen_current_roster_players']),
                                      scenario_count=len(v['counterfactuals']))
                               for s,v in scenario['teams'].items()})
                except (ValueError,KeyError,TypeError,OSError) as scenario_error:
                    reason=str(scenario_error)
                    result['conditional_rotation']=dict(status='UNAVAILABLE',
                        reason=reason if reason.replace('_','').isalnum() and len(reason)<=100 else 'INVALID_RESEARCH_INPUT',
                        training_eligible=False,score_computed=False)
            if str(exc)=='CURRENT_PLAYER_WITHOUT_PRIOR_ROTATION_HISTORY':
                result['rotation_diagnostics']=rotation_coverage_diagnostics(
                    context,review,rosters,boxes,generated)
            if str(exc)=='ABSENCE_REQUIRES_BOTH_SOURCE_OBSERVATIONS':
                # A second pass only on the already-captured data. It NEVER
                # enters MinutesArchive, training, a Telegram score, or production.
                # Only a fresh, pinned official PDF may be used to explore the
                # downstream failure reason without making an availability claim.
                try:
                    scenario=projection(context,review,rosters,boxes,
                        generated_at_utc=generated,diagnostic_official_only=True)
                except Abstain as secondary:
                    label=str(secondary)
                    result['official_only_diagnostic']=dict(
                        status='BLOCKED_NOT_ARCHIVED',
                        downstream_reason=label,
                        production_enabled=False,forecast_changed=False,
                        model_training_eligible=False)
                    if label=='CURRENT_PLAYER_WITHOUT_PRIOR_ROTATION_HISTORY':
                        result['rotation_diagnostics']=rotation_coverage_diagnostics(
                            context,review,rosters,boxes,generated)
                except (ValueError,KeyError,TypeError):
                    result['official_only_diagnostic']=dict(
                        status='UNAVAILABLE_NOT_ARCHIVED',
                        production_enabled=False,forecast_changed=False,
                        model_training_eligible=False)
                else:
                    p=scenario['payload']
                    result['official_only_diagnostic']=dict(
                        status='PROVISIONAL_ROTATION_COMPUTED_NOT_ARCHIVED',
                        source_evidence='FRESH_NBA_OFFICIAL_PDF_ONLY_NOT_ESPN_CORROBORATED',
                        official_only_player_ids=p['provisional_official_only_player_ids'],
                        projection_kind=p['model_input_kind'],
                        scores_computed=False,production_enabled=False,
                        forecast_changed=False,model_training_eligible=False)
            raise
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



def file_sha256(path):
    """Bounded memory, even when the private ledger grows."""
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(512*1024),b''): h.update(block)
    return h.hexdigest()


def collect_batch(ledger,assets,directory,*,maximum=4,minimum_lead_seconds=900,
                  window_seconds=48*3600,maximum_seconds=180,failure_limit=2,
                  dry_run=False,collect_one=collect,loader=load_snapshot):
    """One bounded offline pass over existing future forecasts, never predictions.

    The elapsed budget is checked between fixtures, not a hard process deadline.
    In-flight native requests retain the existing adapter timeouts. Already
    archived inputs do not consume the limit or starve later fixtures.
    """
    for value,low,high in ((maximum,1,8),(minimum_lead_seconds,900,7200),
            (window_seconds,3600,48*3600),(maximum_seconds,10,600),(failure_limit,1,4)):
        if type(value) is not int or not low<=value<=high:
            raise ValueError('PLAYER_BATCH_BOUNDED_POLICY_REQUIRED')
    if type(dry_run) is not bool: raise ValueError('PLAYER_BATCH_DRY_RUN_BOOLEAN_REQUIRED')
    path=local_path(ledger); root=local_path(directory); now=int(time.time()); began=time.monotonic()
    result=dict(format='PLAYER_INPUT_BATCH_V1',evaluated_at_utc=now,status='BLOCKED',reason=None,
        dry_run=dry_run,maximum=maximum,minimum_lead_seconds=minimum_lead_seconds,
        window_seconds=window_seconds,admission_budget_seconds=maximum_seconds,
        budget_scope='CHECKED_BETWEEN_FIXTURES_NOT_HARD_PROCESS_DEADLINE',failure_limit=failure_limit,
        selected=[],results=[],skipped={},eligible_total=0,remaining_eligible=0,
        database_bytes_unchanged=None,forecast_changed=False,online_training=False,
        actual_telegram_delivery_verified=False,production_changed=False)
    before=None
    try:
        if not path.is_file(): raise ValueError('PLAYER_BATCH_LEDGER_UNAVAILABLE')
        before=file_sha256(path)
        report=LedgerReports(path).read('NBA')
        if report['status']!='VERIFIED_LIVE_REPORT': raise ValueError('PLAYER_BATCH_VERIFIED_LEDGER_REQUIRED')
        grouped=defaultdict(list)
        for row in report['forecasts']: grouped[row['fixture_id']].append(row)
        folder=root/'minutes'
        publications=MinutesArchive(folder).first() if folder.is_dir() else []
        existing={p['projection']['payload']['fixture_id']:p for p in publications}
        skipped=Counter(); eligible=[]
        for fid,versions in grouped.items():
            if len(versions)!=1:
                skipped['AMBIGUOUS_ARCHIVED_MODELS']+=1; continue
            row=versions[0]; start=row['fixture_start_utc']
            if row['actual'] is not None:
                skipped['ALREADY_HAS_FINAL_RESULT']+=1; continue
            if start<=now:
                skipped['MATCH_ALREADY_STARTED']+=1; continue
            if start-now<minimum_lead_seconds:
                skipped['INSUFFICIENT_PRETIPOFF_COLLECTION_WINDOW']+=1; continue
            if start-now>window_seconds:
                skipped['OUTSIDE_PROSPECTIVE_WINDOW']+=1; continue
            if fid in existing:
                p=validate_witness(existing[fid],root)
                if p['original_snapshot_sha256']!=row['snapshot_sha256']:
                    skipped['ORIGINAL_SNAPSHOT_LINK_CONFLICT']+=1; continue
                skipped['ALREADY_ARCHIVED_MINUTES']+=1; continue
            eligible.append(row)
        eligible.sort(key=lambda r:(r['fixture_start_utc'],r['fixture_id']))
        selected=eligible[:maximum]
        result.update(skipped=dict(skipped),eligible_total=len(eligible),remaining_eligible=len(eligible),
            selected=[{k:r[k] for k in ('fixture_id','provider_fixture_ids','fixture_start_utc','home','away')}
                      for r in selected])
        if dry_run:
            result['status']='DRY_RUN'; return result
        consecutive=0
        for row in selected:
            if time.monotonic()-began>=maximum_seconds:
                result.update(status='PARTIAL',reason='ADMISSION_TIME_BUDGET_EXHAUSTED'); break
            if row['fixture_start_utc']-int(time.time())<minimum_lead_seconds:
                result['results'].append(dict(fixture_id=row['fixture_id'],status='SKIPPED',
                    reason='COLLECTION_WINDOW_CLOSED_DURING_BATCH'))
                continue
            try:
                snapshot=loader(path,row['fixture_id'])
                if digest(snapshot)!=row['snapshot_sha256']:
                    raise ValueError('PLAYER_BATCH_SNAPSHOT_CHANGED_DURING_READ')
                one=collect_one(snapshot,assets,root)
                item={k:one.get(k) for k in ('fixture_id','status','reason','projection','new_record','roster_diagnostics','rotation_diagnostics','official_only_diagnostic','conditional_rotation')}
            except (ValueError,KeyError,TypeError,OSError,sqlite3.Error):
                item=dict(fixture_id=row['fixture_id'],status='BLOCKED',reason='PLAYER_BATCH_ARCHIVE_OR_SOURCE_UNAVAILABLE')
            result['results'].append(item)
            consecutive=consecutive+1 if item['status']=='BLOCKED' else 0
            if consecutive>=failure_limit:
                result.update(status='PARTIAL',reason='CONSECUTIVE_SOURCE_OR_INPUT_BLOCKS'); break
        if result['status']!='PARTIAL':
            result['status']='COMPLETED_WITH_BLOCKS' if any(r['status']=='BLOCKED' for r in result['results']) else 'COMPLETED'
        result['remaining_eligible']=len(eligible)-sum(r['status'] in ('PROSPECTIVE_MINUTES_ARCHIVED','EXISTING_MINUTES_REPLAY')
                                                    for r in result['results'])
    except (ValueError,KeyError,TypeError,OSError,sqlite3.Error):
        result.update(status='BLOCKED',reason='PLAYER_BATCH_ARCHIVE_UNAVAILABLE_OR_INVALID')
    finally:
        if before is not None:
            try: result['database_bytes_unchanged']=path.is_file() and file_sha256(path)==before
            except OSError: result['database_bytes_unchanged']=False
            if not result['database_bytes_unchanged']:
                result.update(status='BLOCKED',reason='CONCURRENT_LEDGER_CHANGE_DETECTED_NO_RESTORE_ATTEMPT')
    if not dry_run:
        root.mkdir(parents=True,exist_ok=True)
        publish_json(root/('batch-'+digest(result)+'.json'),dict(payload=result,sha256=digest(result)))
    return result


def recent_collection_diagnostics(directory,*,limit=3,maximum_files=512):
    """Return latest hash-pinned real attempts despite a large historical folder.

    The scan is metadata-only. At most maximum_files newest candidate documents
    are opened; the immutable archive is never trimmed, changed or retrained.
    A large count is not an error, nor a reason to hide the newest blockers.
    """
    if type(limit) is not int or not 1<=limit<=10 or type(maximum_files) is not int or not 8<=maximum_files<=4096:
        raise ValueError('COLLECTION_DIAGNOSTIC_BOUNDED_POLICY_REQUIRED')
    root=local_path(directory)
    if not root.is_dir():
        return dict(status='NO_COLLECTION_ATTEMPTS',items=[],read_only=True)
    candidates=[]; count=0
    # Previous implementation stopped when there were >512 files; filename
    # ordering by SHA is not creation ordering. Select by filesystem mtime,
    # but verify the full SHA pin before trusting any record.
    with os.scandir(root) as listing:
        for entry in listing:
            if not re.fullmatch(r'collection-[0-9a-f]{64}\.json',entry.name):
                continue
            if not entry.is_file(follow_symlinks=False):
                continue
            stat=entry.stat(follow_symlinks=False)
            if not 0<stat.st_size<=256*1024:
                continue
            count+=1
            candidate=(stat.st_mtime_ns,entry.name)
            if len(candidates)<maximum_files:
                heapq.heappush(candidates,candidate)
            elif candidate>candidates[0]:
                heapq.heapreplace(candidates,candidate)
    files=[root/name for _,name in sorted(candidates,reverse=True)]
    items=[]
    for path in files:
        if path.is_symlink() or path.stat().st_size>256*1024:
            continue
        try:
            wrapped=json.loads(path.read_text())
            body=wrapped['payload']
            if (wrapped['sha256']!=digest(body) or path.stem!='collection-'+wrapped['sha256']
                    or body.get('format')!='PLAYER_INPUT_COLLECTION_V1'
                    or body.get('status') not in ('BLOCKED','PROSPECTIVE_MINUTES_ARCHIVED',
                        'EXISTING_MINUTES_REPLAY')):
                continue
            diag=body.get('roster_diagnostics')
            diag=diag if isinstance(diag,dict) else {}
            rotation=body.get('rotation_diagnostics')
            rotation=rotation if isinstance(rotation,dict) else {}
            scenario=body.get('official_only_diagnostic')
            scenario=scenario if isinstance(scenario,dict) else {}
            item=dict(fixture_id=body.get('fixture_id'),
                provider_fixture_ids=body.get('provider_fixture_ids'),
                completed_at_utc=body.get('completed_at_utc'),
                status=body['status'],
                reason=body.get('reason'),
                missing_absence_corroboration_count=diag.get('missing_absence_count'),
                official_pdf_fixture_rows=diag.get('official_fixture_rows'),
                official_expected_matchup=diag.get('official_expected_matchup'),
                official_only_diagnostic_status=scenario.get('status'),
                diagnostic_downstream_reason=scenario.get('downstream_reason'),
                rotation_missing_history_counts={
                    side:rotation.get(side,{}).get('missing_history_count')
                    for side in ('home','away') if isinstance(rotation.get(side),dict)},
                real_projection_sha256=body.get('projection'))
            if (isinstance(item['fixture_id'],str) and
                    type(item['completed_at_utc']) is int):
                items.append(item)
        except (OSError,ValueError,KeyError,TypeError):
            continue
    newest={}
    for item in items:
        fid=item['fixture_id']
        if fid not in newest or (item['completed_at_utc'],str(item.get('real_projection_sha256'))) > (
                newest[fid]['completed_at_utc'],str(newest[fid].get('real_projection_sha256'))):
            newest[fid]=item
    recent=sorted(newest.values(),key=lambda x:(x['completed_at_utc'],x['fixture_id']),reverse=True)[:limit]
    return dict(status='ARCHIVED_COLLECTION_ATTEMPTS' if recent else 'NO_COLLECTION_ATTEMPTS',
        items=recent,read_only=True,source_calls=0,scores_recomputed=False,
        collection_files_found=count,collection_files_examined=len(files),
        collection_history_sampled=count>maximum_files)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger',required=True); parser.add_argument('--assets-directory',required=True)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--fixture-id'); group.add_argument('--all-pending',action='store_true')
    parser.add_argument('--dry-run',action='store_true'); parser.add_argument('--maximum',type=int,default=4)
    parser.add_argument('--output-directory',required=True)
    args=parser.parse_args(); ledger=local_path(args.ledger)
    if args.dry_run and not args.all_pending: parser.error('--dry-run requires --all-pending')
    if args.all_pending:
        report=collect_batch(ledger,local_path(args.assets_directory),args.output_directory,
                             maximum=args.maximum,dry_run=args.dry_run)
        print(json.dumps(report,sort_keys=True)); return
    before=file_sha256(ledger)
    snapshot=load_snapshot(ledger,args.fixture_id)
    report=collect(snapshot,local_path(args.assets_directory),args.output_directory)
    report['database_bytes_unchanged']=file_sha256(ledger)==before
    print(json.dumps(report,sort_keys=True))


if __name__=='__main__': main()

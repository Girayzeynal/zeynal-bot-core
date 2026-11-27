"""Manual personal-use projection observations, never an automated Lineups client.

The CSV is a user-normalized format, not a claimed native export schema.
No HTTP requests, inferred minutes, availability claims, training or score changes.
"""
import argparse
import csv
from contextlib import closing
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
import re
import sqlite3
import time

from core.team_identity import digest
from hybrid_engine.boxes import publish_json
from hybrid_engine.current_roster import PREFIX, context_for, player_key, team_key, roster_ids
from hybrid_engine.data import local_path
from hybrid_engine.runtime_reports import RuntimeLedgerReports
from hybrid_engine.time_policy import PREMATCH_MINIMUM_LEAD_SECONDS
from live_analysis_ledger import LiveAnalysisLedger

SOURCE_URL='https://www.lineups.com/nba/nba-player-minutes-per-game/'
FIELDS=('player','team','opponent','projected_minutes')
MAX_CSV=65536
MAX_ROSTER=16*1024*1024
SIDES=('home','away')


def fixture_context(ledger,fixture):
    path=local_path(ledger)
    report=RuntimeLedgerReports(path).read('NBA',fixture,summarize=False)
    rows=report.get('forecasts',[])
    if report.get('status')!='VERIFIED_LIVE_REPORT' or len(rows)!=1:
        raise ValueError('EXACT_VERIFIED_NBA_FORECAST_REQUIRED')
    row=rows[0]
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=.2)) as db:
        db.execute('PRAGMA query_only=ON')
        raw,pin=db.execute('SELECT payload,sha256 FROM live_analysis_snapshots WHERE league=? AND fixture_id=? AND model_digest=?',
            ('NBA',row['fixture_id'],row['model_digest'])).fetchone()
    snapshot=LiveAnalysisLedger._decode(raw,pin,expected=('NBA',row['fixture_id'],row['model_digest']))
    if pin!=row['snapshot_sha256']:raise ValueError('MANUAL_PROJECTION_FORECAST_PIN')
    return context_for(snapshot)


def parse_csv(raw,context):
    if type(raw) is not bytes or not 0<len(raw)<=MAX_CSV:
        raise ValueError('MANUAL_PROJECTION_CSV_SIZE')
    reader=csv.DictReader(io.StringIO(raw.decode('utf-8-sig'),newline=''),strict=True)
    if tuple(reader.fieldnames or ())!=FIELDS:
        raise ValueError('MANUAL_PROJECTION_CSV_HEADER')
    teams={side:team_key(context[side]['official_name']) for side in SIDES}
    if len(set(teams.values()))!=2:raise ValueError('MANUAL_PROJECTION_TEAM_IDENTITY')
    rows={side:[] for side in SIDES};seen=set()
    for row in reader:
        if None in row or any(type(row.get(k)) is not str or not 1<=len(row[k].strip())<=128 for k in FIELDS):
            raise ValueError('MANUAL_PROJECTION_CSV_ROW')
        name=row['player'].strip(); key=player_key(name)
        match=[s for s in SIDES if team_key(row['team'])==teams[s]]
        if len(match)!=1 or not key:raise ValueError('MANUAL_PROJECTION_TEAM_OR_PLAYER')
        side=match[0];other=SIDES[1-SIDES.index(side)]
        if team_key(row['opponent'])!=teams[other]:raise ValueError('MANUAL_PROJECTION_OPPONENT')
        if key in seen:raise ValueError('MANUAL_PROJECTION_DUPLICATE_PLAYER')
        seen.add(key)
        value=row['projected_minutes'].strip()
        if not re.fullmatch(r'\d{1,2}(?:\.\d{1,3})?',value):
            raise ValueError('MANUAL_PROJECTION_MINUTES')
        try:minutes=Decimal(value)
        except InvalidOperation:raise ValueError('MANUAL_PROJECTION_MINUTES')
        if not 0<=minutes<=48 or len(rows[side])>=30:
            raise ValueError('MANUAL_PROJECTION_MINUTES_OR_ROW_LIMIT')
        rows[side].append(dict(player=name,player_key=key,projected_minutes=float(minutes)))
    if not all(rows.values()):raise ValueError('MANUAL_PROJECTION_BOTH_TEAMS_REQUIRED')
    return rows


def roster_receipt(path,context,side,now):
    """Replay an existing local ESPN roster capture, not a new source request."""
    path=local_path(path)
    if not path.is_file() or path.stat().st_size>MAX_ROSTER:
        raise ValueError('MANUAL_ROSTER_RECEIPT_SIZE')
    receipt=json.loads(path.read_text())
    metadata={k:v for k,v in receipt.items() if k!='body_hex'}
    if path.name!='source-'+digest(metadata)+'.json':
        raise ValueError('MANUAL_ROSTER_RECEIPT_PIN')
    raw=bytes.fromhex(receipt['body_hex'])
    team=context[side]
    if (receipt['status']!='RECEIVED' or receipt['url']!=PREFIX+'teams/'+team['provider_id']+'/roster?season='+context['season'][-4:]
            or hashlib.sha256(raw).hexdigest()!=receipt['body_sha256']
            or type(receipt['started_at_utc']) is not int or type(receipt['observed_at_utc']) is not int
            or not 0<receipt['started_at_utc']<=receipt['observed_at_utc']<=now
            or now-receipt['observed_at_utc']>300):
        raise ValueError('MANUAL_ROSTER_RECEIPT_SCOPE_OR_CLOCK')
    document=json.loads(raw)
    names=roster_ids(document,dict(id=team['provider_id'],name=team['official_name']),context['season'])
    if not 8<=len(names)<=30 or len(names)!=len(document['athletes']):
        raise ValueError('MANUAL_ROSTER_INCOMPLETE_OR_AMBIGUOUS')
    return names,dict(receipt_sha256=digest(metadata),body_sha256=receipt['body_sha256'],
                      observed_at_utc=receipt['observed_at_utc'])


def audit(raw,context,*,home_roster=None,away_roster=None):
    now=int(time.time())
    if now>=context['fixture_start_utc']-PREMATCH_MINIMUM_LEAD_SECONDS:
        raise ValueError('MANUAL_PROJECTION_PREMATCH_WINDOW_CLOSED')
    if not context['prediction_generated_at_utc']<=now:
        raise ValueError('MANUAL_PROJECTION_ORIGINAL_CLOCK')
    rows=parse_csv(raw,context)
    if bool(home_roster)!=bool(away_roster):raise ValueError('MANUAL_ROSTER_BOTH_RECEIPTS_REQUIRED')
    result={};all_ids=set()
    for side,path in zip(SIDES,(home_roster,away_roster)):
        names,witness=roster_receipt(path,context,side,now) if path else ({},None)
        observed=set();unmatched=[]
        if all_ids.intersection(names.values()):raise ValueError('MANUAL_ROSTER_SHARED_PLAYER_ID')
        all_ids.update(names.values())
        for row in rows[side]:
            pid=names.get(row['player_key'])
            row['espn_player_id']=pid
            if pid is None:unmatched.append(row['player'])
            else:observed.add(pid)
        total=round(sum(row['projected_minutes'] for row in rows[side]),6)
        missing=sorted(set(names.values())-observed)
        result[side]=dict(team_id=context[side]['provider_id'],rows=rows[side],
            roster_receipt=witness,matched_count=len(observed),unmatched_players=unmatched,
            missing_roster_player_ids=missing,projected_total_minutes=total,
            difference_from_240=round(total-240,6),
            complete_roster_identity=bool(witness) and not unmatched and not missing,
            exact_240=abs(total-240)<1e-6)
    return dict(format='MANUAL_LINEUPS_ROTATION_OBSERVATION_V1',
        source_url=SOURCE_URL,source_kind='USER_NORMALIZED_MANUAL_TRANSCRIPTION',
        source_publication_utc=None,source_document_verified=False,
        source_fixture_independently_verified=False,local_import_utc=now,
        csv_sha256=hashlib.sha256(raw).hexdigest(),context=context,teams=result,
        personal_research_only=True,availability_verified=False,minutes_are_actual=False,
        inferred_minutes=False,normalized_to_240=False,eligible_for_fit=False,
        score_model_changed=False,forecast_changed=False,production_changed=False,
        status='MANUAL_OBSERVATION_ONLY_NOT_ADMITTED')


def capture(ledger,fixture,csv_path,*,home_roster=None,away_roster=None,output_directory=None):
    path=local_path(csv_path)
    if path.stat().st_size>MAX_CSV:raise ValueError('MANUAL_PROJECTION_CSV_SIZE')
    raw=path.read_bytes()
    context=fixture_context(ledger,fixture)
    report=audit(raw,context,home_roster=home_roster,away_roster=away_roster)
    if output_directory is not None:
        root=local_path(output_directory)
        # Explicit isolated destination; never place files in the model minutes registry.
        if root.name!='manual-lineups-research':
            raise ValueError('MANUAL_PROJECTION_SEPARATE_DIRECTORY_REQUIRED')
        root.mkdir(parents=True,exist_ok=True)
        if int(time.time())>=context['fixture_start_utc']-PREMATCH_MINIMUM_LEAD_SECONDS:
            raise ValueError('MANUAL_PROJECTION_PREMATCH_WINDOW_CLOSED')
        pin=digest(report)
        publish_json(root/('manual-'+pin+'.json'),dict(payload=report,sha256=pin))
        # Even after publication there is no fit eligibility or proof of source time.
        return dict(report,local_archive_sha256=pin,completed_at_utc=int(time.time()))
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ledger',required=True);p.add_argument('--fixture',required=True)
    p.add_argument('--csv',required=True);p.add_argument('--home-roster')
    p.add_argument('--away-roster');p.add_argument('--output-directory')
    p.add_argument('--personal-use',action='store_true',required=True,
                   help='Confirm manually obtained, non-published, non-commercial data')
    a=p.parse_args()
    try:
        result=capture(a.ledger,a.fixture,a.csv,home_roster=a.home_roster,
                       away_roster=a.away_roster,output_directory=a.output_directory)
    except (ValueError,KeyError,TypeError,OSError,sqlite3.Error,RuntimeError,csv.Error):
        p.exit(2,'MANUAL_LINEUPS_RESEARCH_BLOCKED: input, identity, clock or archive validation failed\n')
    print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))


if __name__=='__main__':main()

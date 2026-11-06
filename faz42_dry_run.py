"""Opt-in upcoming fixture discovery. Never stores real prediction snapshots.

python -m faz42_dry_run --live-discovery
No scheduler, external storage, model fitting, Telegram or deployment calls.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta
import json
import time
from zoneinfo import ZoneInfo

from prediction_inputs import digest
from faz41_transport import fetch
from faz42_schedule import seal_schedule,fixture_times
from faz42_snapshot import model_manifest,build_snapshot
from faz40_archive import require


def plan(asof_utc):
    today=datetime.fromtimestamp(asof_utc,ZoneInfo('America/New_York')).date()
    rows=[dict(key='NBA_'+str(i),provider='ESPN',league='NBA',url='https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates='+(today+timedelta(days=i)).strftime('%Y%m%d')) for i in range(3)]
    rows+=[dict(key=league,provider='EUROLEAGUE_LIVE',league=league,
                url=f'https://api-live.euroleague.net/v2/competitions/{code}/seasons/{code}2026/games?limit=1000')
           for league,code in [('EUROLEAGUE','E'),('EUROCUP','U')]]
    return rows


def run(*,live=False,collector=fetch,observations=None,model=None):
    if live is not True:return dict(status='ABSTAIN_LIVE_DISCOVERY_NOT_REQUESTED',network_requests=0,prospective_records_created=0)
    started=int(time.time());requests=plan(started)
    with ThreadPoolExecutor(max_workers=3) as pool:
        responses=list(pool.map(lambda item:collector(item['url'],provider=item['provider']),requests))
    schedules=[];sources=[]
    for item,response in zip(requests,responses):
        info={k:v for k,v in response.items() if k!='payload'};info.update(key=item['key'],league=item['league'])
        if response['status']=='DOCUMENT_RECEIVED':
            info['document_sha256']=digest(response['payload'])
            try:
                schedule=seal_schedule(response['payload'],provider=item['provider'],league=item['league'],season_end_year=2027,
                    source_url=item['url'],observed_at_utc=response['observed_at_utc'],ingested_at_utc=int(time.time()))
                schedules.append(schedule);info.update(discovery_sha256=schedule['sha256'],future_catalog_fixtures=len(schedule['payload']['fixtures']),
                                                      rejected_events=len(schedule['payload']['rejected']))
            except (ValueError,KeyError,TypeError) as ex:info.update(discovery_status='ABSTAIN',reason=str(ex) if type(ex) is ValueError else 'MALFORMED_PROVIDER_SCHEDULE')
        sources.append(info)
    if schedules and int(time.time())<=max(s['payload']['materialized_at_utc'] for s in schedules):time.sleep(1.05)
    cutoff=int(time.time());fixtures={};slots={}
    try:
        for schedule in schedules:
            for item in schedule['payload']['fixtures']:
                f=item['fixture']
                if not cutoff<f['start_utc']<=cutoff+48*3600:continue
                cid=f['canonical_id']
                for side in ('home','away'):
                    slot=(f['league'],f[side+'_team_id'],f['start_utc'])
                    require(slot not in slots or slots[slot]==cid,'CROSS_DOCUMENT_FIXTURE_CONFLICT');slots[slot]=cid
                fixtures.setdefault(cid,(f,schedule))
    except ValueError as ex:return dict(status='ABSTAIN_DISCOVERY_CONFLICT',reason=str(ex),sources=sources,prospective_records_created=0)
    model_error=None
    if model is None:
        try:model=model_manifest()
        except (ValueError,OSError) as ex:model_error=str(ex) if type(ex) is ValueError else 'MODEL_MANIFEST_UNAVAILABLE'
    reports=[]
    for cid,(f,schedule) in sorted(fixtures.items(),key=lambda item:(item[1][0]['start_utc'],item[0])):
        row=dict(fixture=f,**fixture_times(f),source_url=schedule['payload']['source_url'],source_digest=schedule['sha256'],
                 observed_at_utc=schedule['payload']['observed_at_utc'],cutoff_utc=cutoff,status='ABSTAIN',reason=model_error)
        if model is not None:
            try:
                snapshot=build_snapshot(observations or [],schedule,cid,model,cutoff_utc=cutoff)
                p=snapshot['payload'];row.update(status=p['status'],reason=p['abstain_reason'],snapshot_digest=snapshot['sha256'],
                    model_sha=model['payload']['git_sha'],model_digest=model['sha256'],prediction=p['prediction'])
            except (ValueError,KeyError,TypeError) as ex:row['reason']=str(ex) if type(ex) is ValueError else 'SNAPSHOT_INPUT_INVALID'
        reports.append(row)
    return dict(status='DRY_RUN_COMPLETE_NOT_RECORDED',started_at_utc=started,cutoff_utc=cutoff,network_requests=len(requests),
        sources=sources,upcoming_fixtures=reports,unique_upcoming_games=len(reports),
        unpersisted_predictions=sum(r['status']=='PREDICTED_EXPERIMENTAL' for r in reports),
        abstentions=sum(r['status']=='ABSTAIN' for r in reports),prospective_records_created=0,
        storage_status='NOT_ACTIVATED',scheduler_status='NOT_INSTALLED',independent_utc_attestation=False)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--live-discovery',action='store_true');a=p.parse_args()
    print(json.dumps(run(live=a.live_discovery),sort_keys=True,allow_nan=False));return 0


if __name__=='__main__':raise SystemExit(main())

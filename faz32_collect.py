"""Explicit manual/free research collector. No scheduler or forecast writes."""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time

from nba_research_store import ResearchStore, validate_summary
from providers.espn_adapter import ESPNAdapter, ESPN_BASE
from providers.espn_completed_event import parse_completed_nba_event


def write_json(path, value):
    with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as stream:
        json.dump(value, stream, sort_keys=True, allow_nan=False)
    path.chmod(0o600)
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def collect(days, destination, adapter=None):
    days=list(dict.fromkeys(days))
    for day in days:
        if len(day)!=8 or datetime.strptime(day,'%Y%m%d').strftime('%Y%m%d')!=day:
            raise ValueError('explicit YYYYMMDD dates required')
    root=Path(destination);root.mkdir(mode=0o700,parents=True,exist_ok=False)
    api=adapter or ESPNAdapter();manifest=dict(directory={},days=[],summaries=[])
    try:
        teams=await api._load_teams();observed=int(time.time())
        if not teams:raise ValueError('NBA team directory unavailable')
        directory={t['team']['id']:dict(name=t['team']['displayName'],abbr=t['team']['abbreviation']) for t in teams}
        manifest['directory']=dict(teams=directory,observed_utc=observed,source_url=ESPN_BASE+'/teams')
        seen=set()
        for day in days:
            raw=await api._get_json(ESPN_BASE+'/scoreboard?dates='+day)
            observed=int(time.time())
            if not isinstance(raw,dict) or not isinstance(raw.get('events'),list):
                manifest['days'].append(dict(day=day,status='PROVIDER_UNAVAILABLE',http_status=api.last_http_status));break
            events=[parse_completed_nba_event(e,datetime.fromtimestamp(observed,timezone.utc)) for e in raw['events']]
            manifest['days'].append(dict(day=day,raw_events=len(events),accepted_final_candidates=sum(e is not None for e in events),not_final_or_invalid=sum(e is None for e in events)))
            for event in events:
                if event is None or event['provider_fixture_id'] in seen:continue
                fixture=event['provider_fixture_id'];seen.add(fixture)
                summary=await api._get_json(ESPN_BASE+'/summary?event='+fixture);stamp=int(time.time())
                try:
                    parsed=validate_summary(summary,stamp,set(directory))
                    if parsed['event']!=event:raise ValueError('scoreboard-summary final mismatch')
                except (KeyError,ValueError,TypeError,IndexError) as exc:
                    manifest['summaries'].append(dict(fixture_id=fixture,status='REJECTED',error=str(exc),http_status=api.last_http_status));continue
                path=root/(fixture+'.json');sha=write_json(path,summary)
                manifest['summaries'].append(dict(fixture_id=fixture,path=str(path.resolve()),file_sha256=sha,observed_utc=stamp,http_status=api.last_http_status,scoreboard_final=event))
    finally:
        write_json(root/'fetch-manifest.json',manifest)
        if adapter is None:await api.aclose()
    return manifest


def import_downloads(manifest_path, database):
    """Replay actual response clocks; never substitute import time for fetch time."""
    path=Path(manifest_path);manifest=json.loads(path.read_text())
    store=ResearchStore(database,manifest['directory']['teams'])
    inserted=duplicate=0;rejected=[]
    for item in manifest['summaries']:
        if item.get('status')=='REJECTED':rejected.append(item);continue
        try:
            file=Path(item['path']);raw=file.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=item['file_sha256']:raise ValueError('download file checksum mismatch')
            summary=json.loads(raw);event=validate_summary(summary,item['observed_utc'],store.team_ids)['event']
            if event!=item['scoreboard_final'] or event['provider_fixture_id']!=item['fixture_id']:raise ValueError('manifest/source final identity mismatch')
            added=store.ingest(summary,item['observed_utc'],'NEW_DOWNLOAD',dict(path=str(file),file_sha256=item['file_sha256'],
                collection_started_utc=manifest['directory']['observed_utc'],fetch_manifest_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
            inserted+=int(added);duplicate+=int(not added)
        except (KeyError,ValueError,TypeError,IndexError,OSError) as exc:
            rejected.append(dict(fixture_id=item.get('fixture_id'),error=str(exc)))
    return dict(inserted=inserted,idempotent=duplicate,rejected=rejected,coverage=store.coverage())


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    c=sub.add_parser('collect');c.add_argument('destination');c.add_argument('dates',nargs='+')
    i=sub.add_parser('import');i.add_argument('manifest');i.add_argument('database')
    args=p.parse_args()
    result=asyncio.run(collect(args.dates,args.destination)) if args.action=='collect' else import_downloads(args.manifest,args.database)
    print(json.dumps(result,sort_keys=True,allow_nan=False))

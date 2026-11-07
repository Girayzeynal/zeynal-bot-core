"""Indexed, pinned, read-only development inputs. Not a prediction ledger.

Existing source files are read only; derived observations get real new ingestion
and materialization clocks. Defaults never grant source rights. Local bundle
publication is exclusive/atomic and cannot overwrite an older input artifact.
"""
from copy import deepcopy
from datetime import datetime,timedelta
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import time
from zoneinfo import ZoneInfo

from prediction_inputs import digest
from faz40_archive import require
from faz40_archive_audit import load_nba,load_euro,file_sha
from faz41_adapters import capture,replay
from faz41_evidence import REGISTRY,REGISTRY_PIN
from faz41_transport import fetch
from faz42_schedule import seal_schedule,validate_schedule
from faz42_snapshot import model_manifest,validate_model
from faz43_nba_refresh import replay_research_fact
from faz43_development import parse_request
from faz42_dry_run import plan

FORMAT='FAZ44_INDEXED_DEVELOPMENT_INPUTS_V1'
MAX_BYTES=8_000_000


def derive_history(nba_database,*,euro_evidence=None,nba_refresh=None,registry=REGISTRY,registry_pin=REGISTRY_PIN):
    archive,source=load_nba(nba_database);files=[source];candidates=[]
    if euro_evidence:
        extra,src=load_euro(euro_evidence);archive+=extra;files.append(src)
    for r in archive:
        p=r['payload'];f=p['facts'];candidates.append(dict(raw=p['raw'],provider=f['provider'],league=f['league'],season=f['season_end_year'],
            observed=p['source_observed_utc'],parent_sha256=r['sha256'],parent_kind='FAZ40_SOURCE_ARCHIVE',parent_materialized_utc=p['materialized_utc']))
    if nba_refresh:
        path=Path(nba_refresh);before=file_sha(path);doc=json.loads(path.read_text())
        for r in doc['new_games']:
            n=replay_research_fact(r,asof_utc=int(time.time()));p=r['payload']
            candidates.append(dict(raw=p['compact_summary'],provider='ESPN',league='NBA',season=n['fixture']['season_end_year'],observed=p['observed_at_utc'],
                parent_sha256=r['sha256'],parent_kind='FAZ43_NBA_RESEARCH_FACT',parent_materialized_utc=p['materialized_at_utc']))
        require(file_sha(path)==before,'SOURCE_ARCHIVE_CHANGED');files.append(dict(source=str(path),sha256=before,unchanged=True))
    observations={};fact_by_game={};parents={}
    for row in candidates:
        raw=deepcopy(row['raw']);raw['_faz44_derivation']={k:row[k] for k in ('parent_sha256','parent_kind','parent_materialized_utc')}
        raw['_faz44_derivation']['usage']='NEW_DERIVATION_NOT_ORIGINAL_PREMATCH_INPUT'
        child=capture(raw,provider=row['provider'],league=row['league'],season_end_year=row['season'],
            observed_at_utc=row['observed'],ingested_at_utc=int(time.time()),registry=registry,registry_pin=registry_pin)
        p=child['payload'];cid=p['fixture']['canonical_id']
        require(cid not in fact_by_game or fact_by_game[cid]==p['claims'],'CONFLICTING_DERIVED_GAME');fact_by_game[cid]=p['claims']
        parents.setdefault(cid,[]).append(row['parent_sha256'])
        if cid not in observations or (p['observed_at_utc'],child['sha256'])>(observations[cid]['payload']['observed_at_utc'],observations[cid]['sha256']):observations[cid]=child
    require(all(file_sha(f['source'])==f['sha256'] for f in files),'SOURCE_ARCHIVE_CHANGED')
    return list(observations.values()),dict(source_files=files,canonical_games=len(observations),
        reobservations_coalesced=len(candidates)-len(observations),parent_sha256_by_canonical_id=parents,
        original_timestamps_not_backfilled=True,player_data_not_fabricated=True)


def collect_schedules(*,live=False,collector=fetch,registry=REGISTRY,registry_pin=REGISTRY_PIN):
    if live is not True:return [],dict(status='ABSTAIN_LIVE_SCHEDULE_NOT_REQUESTED',sources=[],network_requests=0)
    requests=plan(int(time.time()));schedules=[];sources=[]
    for item in requests:
        response=collector(item['url'],provider=item['provider'],registry=registry,registry_pin=registry_pin)
        info={k:v for k,v in response.items() if k!='payload'};info['league']=item['league']
        if response['status']=='DOCUMENT_RECEIVED':
            try:
                schedule=seal_schedule(response['payload'],provider=item['provider'],league=item['league'],season_end_year=2027,
                    source_url=item['url'],observed_at_utc=response['observed_at_utc'],ingested_at_utc=int(time.time()),registry=registry,registry_pin=registry_pin)
                schedules.append(schedule);info.update(schedule_sha256=schedule['sha256'],source_json_sha256=digest(response['payload']))
            except (ValueError,KeyError,TypeError):info.update(status='ABSTAIN_INVALID_SCHEDULE')
        sources.append(info)
    return schedules,dict(status='LIVE_DISCOVERY_ONLY_NOT_PREDICTION',sources=sources,network_requests=len(requests))


def make_bundle(observations,schedules,model,*,days,registry=REGISTRY,registry_pin=REGISTRY_PIN,policy_bundle_sha256=None,collection=None):
    now=int(time.time());require(type(days) is list and 1<=len(days)<=3 and len(days)==len(set(days)),'ONE_TO_THREE_UNIQUE_DAYS_REQUIRED')
    for day in days:parse_request('/analyze NBA '+day+' A vs B')
    require(type(observations) is list and type(schedules) is list and digest(registry)==registry_pin,'INPUT_COLLECTION_SCHEMA_OR_POLICY')
    source_map={o['sha256']:deepcopy(o) for o in observations};schedule_map={s['sha256']:deepcopy(s) for s in schedules}
    require(all(o['sha256']==digest(o['payload']) for o in source_map.values()) and all(s['sha256']==digest(s['payload']) for s in schedule_map.values()),'INPUT_COLLECTION_DIGEST')
    partitions={}
    for league in ('NBA','EUROLEAGUE','EUROCUP'):
        hs=sorted(h for h,o in source_map.items() if o['payload']['fixture']['league']==league)
        for day in days:
            ss=sorted(h for h,s in schedule_map.items() if s['payload']['league']==league and any(
                datetime.fromtimestamp(r['fixture']['start_utc'],ZoneInfo('Europe/Istanbul')).date().isoformat()==day for r in s['payload']['fixtures']))
            seasons={r['fixture']['season_end_year'] for h in ss for r in schedule_map[h]['payload']['fixtures'] if datetime.fromtimestamp(r['fixture']['start_utc'],ZoneInfo('Europe/Istanbul')).date().isoformat()==day}
            require(len(seasons)<=1,'AMBIGUOUS_INPUT_SEASON')
            selected_hs=[h for h in hs if not seasons or source_map[h]['payload']['fixture']['season_end_year'] in seasons]
            partitions[league+':'+day]=dict(history_sha256=selected_hs,schedule_sha256=ss)
    p=dict(format=FORMAT,materialized_at_utc=now,registry_sha256=registry_pin,policy_bundle_sha256=policy_bundle_sha256,
        sources=source_map,schedules=schedule_map,model_manifest=deepcopy(model),partitions=partitions,
        usage='DEVELOPMENT_INPUTS_ONLY',prospective_records_created=0,storage_status='NOT_A_PREDICTION_LEDGER',collection=deepcopy(collection or {}))
    sealed=dict(payload=p,sha256=digest(p))
    IndexedInputsBackend(sealed,trusted_sha256=sealed['sha256'],registry=registry,registry_pin=registry_pin,policy_bundle_sha256=policy_bundle_sha256)
    return sealed


class IndexedInputsBackend:
    def __init__(self,sealed,*,trusted_sha256,registry=REGISTRY,registry_pin=REGISTRY_PIN,policy_bundle_sha256=None):
        require(type(sealed) is dict and set(sealed)=={'payload','sha256'} and sealed['sha256']==trusted_sha256 and
                digest(sealed['payload'])==trusted_sha256,'TRUSTED_INPUT_BUNDLE_PIN_MISMATCH')
        p=sealed['payload'];require(type(p) is dict and set(p)==set('format materialized_at_utc registry_sha256 policy_bundle_sha256 sources schedules model_manifest partitions usage prospective_records_created storage_status collection'.split()) and
            p['format']==FORMAT and p['usage']=='DEVELOPMENT_INPUTS_ONLY' and p['prospective_records_created']==0 and p['storage_status']=='NOT_A_PREDICTION_LEDGER' and type(p['collection']) is dict,'INDEXED_INPUT_SCHEMA')
        now=int(time.time());at=p['materialized_at_utc'];require(type(at) is int and 0<at<=now,'INPUT_BUNDLE_CLOCK')
        require(digest(registry)==registry_pin==p['registry_sha256'] and p['policy_bundle_sha256']==policy_bundle_sha256,'INPUT_POLICY_BINDING')
        validate_model(p['model_manifest'],at)
        require(type(p['sources']) is dict and type(p['schedules']) is dict and type(p['partitions']) is dict and len(p['partitions'])<=9,'INDEXED_INPUT_MAPS')
        categories=set();aliases={};slots={}
        for h,o in p['sources'].items():
            require(h==o['sha256'],'SOURCE_REFERENCE_DIGEST');q=replay(o,fixture=o['payload']['fixture'],cutoff_utc=at,maximum_age_seconds=100*366*86400,
                registry=registry,registry_pin=registry_pin,require_permitted=False)
            require(q['data_type']=='OFFICIAL_STAT','SCORE_HISTORY_REQUIRED');categories.add(q['usage']=='SYNTHETIC_TEST')
        for h,s in p['schedules'].items():
            require(h==s['sha256'],'SCHEDULE_REFERENCE_DIGEST');q=validate_schedule(s,cutoff_utc=at,maximum_age_seconds=100*366*86400,
                registry=registry,registry_pin=registry_pin,require_permitted=False);categories.add(q['usage']=='SYNTHETIC_TEST')
            for row in q['fixtures']:
                f=row['fixture'];cid=f['canonical_id']
                for pid in row['provider_fixture_ids']:
                    alias=(q['provider'],q['league'],q['season_end_year'],pid)
                    require(alias not in aliases or aliases[alias]==cid,'CROSS_DOCUMENT_PROVIDER_ID_CONFLICT');aliases[alias]=cid
                for side in ('home','away'):
                    slot=(f['league'],f[side+'_team_id'],f['start_utc'])
                    require(slot not in slots or slots[slot]==cid,'CROSS_DOCUMENT_TEAM_START_CONFLICT');slots[slot]=cid
        require(len(categories)<=1 and (not categories or next(iter(categories))==(p['model_manifest']['payload']['purpose']=='SYNTHETIC_TEST')),'MIXED_SYNTHETIC_REAL_INPUT_BUNDLE')
        for key,refs in p['partitions'].items():
            require(type(key) is str and ':' in key and type(refs) is dict and set(refs)=={'history_sha256','schedule_sha256'},'INPUT_PARTITION_SCHEMA')
            league,day=key.split(':',1);require(league in ('NBA','EUROLEAGUE','EUROCUP'),'INPUT_PARTITION_LEAGUE');parse_request('/analyze '+league+' '+day+' A vs B')
            for field,collection in [('history_sha256',p['sources']),('schedule_sha256',p['schedules'])]:
                values=refs[field];require(type(values) is list and len(values)==len(set(values)) and set(values)<=set(collection),'MISSING_OR_DUPLICATE_INPUT_REFERENCE')
                require(all((collection[h]['payload']['fixture']['league'] if field=='history_sha256' else collection[h]['payload']['league'])==league for h in values),'CROSS_LEAGUE_INPUT_REFERENCE')
            seasons=set()
            for h in refs['schedule_sha256']:
                matches=[r['fixture'] for r in p['schedules'][h]['payload']['fixtures'] if datetime.fromtimestamp(r['fixture']['start_utc'],ZoneInfo('Europe/Istanbul')).date().isoformat()==day]
                require(matches,'INPUT_SCHEDULE_DAY_MISMATCH');seasons.update(f['season_end_year'] for f in matches)
            require(len(seasons)<=1 and all(not seasons or p['sources'][h]['payload']['fixture']['season_end_year'] in seasons for h in refs['history_sha256']),'CROSS_SEASON_INPUT_REFERENCE')
        self.payload=deepcopy(p)

    async def load_inputs(self,league,day):
        refs=self.payload['partitions'].get(league+':'+day)
        if refs is None:return None
        if not refs['schedule_sha256']:
            receipts=[r for r in self.payload['collection'].get('schedule_collection',{}).get('sources',[]) if r.get('league')==league]
            if receipts and any(r.get('status')!='DOCUMENT_RECEIVED' for r in receipts):raise ValueError('SOURCE_COLLECTION_UNAVAILABLE')
        return dict(schedules=[deepcopy(self.payload['schedules'][h]) for h in refs['schedule_sha256']],
                    history=[deepcopy(self.payload['sources'][h]) for h in refs['history_sha256']],model=deepcopy(self.payload['model_manifest']))


def read_development_inputs(path,*,trusted_sha256,registry=REGISTRY,registry_pin=REGISTRY_PIN,policy_bundle_sha256=None):
    p=Path(path);require(not p.is_symlink() and Path('/data') not in p.resolve().parents and p.is_file() and p.stat().st_size<=MAX_BYTES,'READONLY_DEVELOPMENT_BUNDLE_REQUIRED')
    sealed=json.loads(p.read_text())
    require(type(sealed) is dict and set(sealed)=={'payload','sha256'} and type(sealed['payload']) is dict,'INPUT_BUNDLE_ENVELOPE')
    require(type(sealed) is dict and sealed.get('sha256')==trusted_sha256 and digest(sealed['payload'])==trusted_sha256,'TRUSTED_INPUT_BUNDLE_PIN_MISMATCH')
    if sealed['payload'].get('format')==FORMAT:return IndexedInputsBackend(sealed,trusted_sha256=trusted_sha256,registry=registry,registry_pin=registry_pin,policy_bundle_sha256=policy_bundle_sha256)
    from faz43_development import FrozenInputsBackend
    return FrozenInputsBackend(sealed,trusted_sha256=trusted_sha256)


def publish_local_bundle(path,sealed):
    return publish_development_artifact(path,sealed,expected_format=FORMAT,filename_prefix='faz44-inputs-')


def publish_development_artifact(path,sealed,*,expected_format,filename_prefix):
    require((expected_format,filename_prefix) in ((FORMAT,'faz44-inputs-'),('FAZ45_SUPPORT_EVIDENCE_V1','faz45-support-'),
            ('FAZ46_PREMATCH_AUDIT_V1','faz46-prematch-'),('FAZ47_RESEARCH_READINESS_V1','faz47-readiness-')),
            'DEVELOPMENT_ARTIFACT_FORMAT_REQUIRED')
    p=Path(path);root=p.parent.resolve();allowed=Path('/workspace/scratch')
    require(root.is_dir() and (root==Path(tempfile.gettempdir()).resolve() or Path(tempfile.gettempdir()).resolve() in root.parents or
            root==allowed or allowed in root.parents) and p.name.startswith(filename_prefix) and p.suffix=='.json' and not p.is_symlink(),'LOCAL_DEVELOPMENT_INPUT_PATH_REQUIRED')
    require(sealed['sha256']==digest(sealed['payload']) and sealed['payload'].get('format')==expected_format and sealed['payload'].get('prospective_records_created')==0,'INPUT_BUNDLE_DIGEST')
    body=(json.dumps(sealed,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode();require(len(body)<=MAX_BYTES,'INPUT_BUNDLE_SIZE_LIMIT')
    fd,temp=tempfile.mkstemp(prefix='.faz44-',dir=root);temp=Path(temp)
    try:
        with os.fdopen(fd,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
        try:os.link(temp,p,follow_symlinks=False);created=True
        except FileExistsError:
            require(not p.is_symlink() and p.read_bytes()==body,'IMMUTABLE_INPUT_BUNDLE_CONFLICT');created=False
        directory=os.open(root,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)
        return created
    finally:temp.unlink(missing_ok=True)


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--nba-database',required=True);parser.add_argument('--euro-evidence');parser.add_argument('--nba-refresh')
    parser.add_argument('--day',required=True);parser.add_argument('--days',type=int,default=2);parser.add_argument('--live-schedule',action='store_true');parser.add_argument('--output',required=True)
    parser.add_argument('--source-policy');parser.add_argument('--trusted-policy-sha256');a=parser.parse_args()
    try:
        require(1<=a.days<=3 and bool(a.source_policy)==bool(a.trusted_policy_sha256),'INPUT_BUILDER_CONFIGURATION')
        parse_request('/analyze NBA '+a.day+' A vs B');day=datetime.strptime(a.day,'%Y-%m-%d').date()
        policy=dict(registry=REGISTRY,registry_pin=REGISTRY_PIN);policy_ref=None;permitted=[]
        if a.source_policy:
            from faz44_policy import read_source_policy
            loaded=read_source_policy(a.source_policy,trusted_sha256=a.trusted_policy_sha256)
            policy=dict(registry=loaded['registry'],registry_pin=loaded['registry_sha256']);policy_ref=loaded['policy_bundle_sha256'];permitted=loaded['permitted_providers']
        observations,provenance=derive_history(a.nba_database,euro_evidence=a.euro_evidence,nba_refresh=a.nba_refresh,**policy)
        schedules,collection=collect_schedules(live=a.live_schedule,**policy);model=model_manifest()
        clocks=[o['payload']['materialized_at_utc'] for o in observations]+[s['payload']['materialized_at_utc'] for s in schedules]
        if clocks and int(time.time())<=max(clocks):time.sleep(1.05)
        bundle=make_bundle(observations,schedules,model,days=[(day+timedelta(days=i)).isoformat() for i in range(a.days)],
            policy_bundle_sha256=policy_ref,collection=dict(history_provenance=provenance,schedule_collection=collection),**policy)
        created=publish_local_bundle(a.output,bundle)
        counts={league:len({o['payload']['fixture']['canonical_id'] for o in observations if o['payload']['fixture']['league']==league}) for league in ('NBA','EUROLEAGUE','EUROCUP')}
        print(json.dumps(dict(status='DEVELOPMENT_INPUT_BUNDLE_PUBLISHED_NO_PREDICTIONS',created=created,path=str(Path(a.output).resolve()),
            trusted_bundle_sha256=bundle['sha256'],model_sha=model['payload']['git_sha'],history_games=counts,schedule_documents=len(schedules),
            partitions=len(bundle['payload']['partitions']),source_permissions_permitted=permitted,network_requests=collection['network_requests'],
            source_files_unchanged=all(file_sha(p['source'])==p['sha256'] for p in provenance['source_files']),prospective_records_created=0,
            scheduler_status='NOT_INSTALLED',storage_status='INPUT_FILE_ONLY_NOT_PREDICTION_STORAGE'),sort_keys=True));return 0
    except (ValueError,KeyError,TypeError,OSError,sqlite3.Error,subprocess.SubprocessError) as ex:
        # A failure after atomic linking may leave a valid but unacknowledged
        # input file. Do not falsely claim that no bytes were published.
        print(json.dumps(dict(status='ABSTAIN_INPUT_PUBLICATION_NOT_CONFIRMED',reason=str(ex) if type(ex) is ValueError else type(ex).__name__,prospective_records_created=0)));return 1


if __name__=='__main__':raise SystemExit(main())

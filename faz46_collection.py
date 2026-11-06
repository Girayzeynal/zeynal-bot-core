"""Bounded opt-in prematch source audit. No forecast, bot or real ledger writes."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import time

from prediction_inputs import digest
from faz40_archive import require
from faz41_evidence import REGISTRY,REGISTRY_PIN
from faz41_transport import fetch
from faz42_dry_run import plan
from faz42_schedule import seal_schedule
from faz44_inputs import publish_development_artifact,MAX_BYTES
from faz46_rosters import audit_endpoint,endpoint,replay_listing,derive_listings

FORMAT='FAZ46_PREMATCH_AUDIT_V1'
NBA_SCHEDULE='https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json'


def collect(*,live=False,collector=fetch,registry=REGISTRY,registry_pin=REGISTRY_PIN):
    if live is not True:return dict(status='ABSTAIN_LIVE_PREMATCH_NOT_REQUESTED',network_requests=0,audits=[],sources=[],observations=0,confirmed_lineups=0,prospective_records_created=0)
    sources=[];schedules=[];errors=[]
    for item in plan(int(time.time())):
        r=collector(item['url'],provider=item['provider'],registry=registry,registry_pin=registry_pin)
        receipt={k:v for k,v in r.items() if k!='payload'};sources.append(receipt)
        if r['status']!='DOCUMENT_RECEIVED':continue
        try:
            s=seal_schedule(r['payload'],provider=item['provider'],league=item['league'],season_end_year=2027,
                source_url=item['url'],observed_at_utc=r['observed_at_utc'],ingested_at_utc=int(time.time()),registry=registry,registry_pin=registry_pin)
            schedules.append(s)
        except (ValueError,KeyError,TypeError):errors.append(dict(league=item['league'],status='ABSTAIN_MALFORMED_SCHEDULE'))
    nba=collector(NBA_SCHEDULE,provider='NBA',registry=registry,registry_pin=registry_pin)
    sources.append({k:v for k,v in nba.items() if k!='payload'})
    selected={};aliases={};slots={}
    for s in schedules:
        for r in s['payload']['fixtures']:
            f=r['fixture'];league=f['league']
            if f['start_utc']<=int(time.time()):continue
            conflict=False
            for pid in r['provider_fixture_ids']:
                key=(s['payload']['provider'],league,pid)
                if key in aliases and aliases[key]!=f['canonical_id']:conflict=True
                aliases[key]=f['canonical_id']
            for side in ('home','away'):
                key=(league,f[side+'_team_id'],f['start_utc'])
                if key in slots and slots[key]!=f['canonical_id']:conflict=True
                slots[key]=f['canonical_id']
            if conflict:return dict(status='ABSTAIN_DISCOVERY_IDENTITY_CONFLICT',network_requests=len(sources),audits=[],sources=sources,
                errors=errors,observations=0,confirmed_lineups=0,prospective_records_created=0)
            if league not in selected or f['start_utc']<selected[league][1]['fixture']['start_utc']:selected[league]=(s,r)
    audits=[]
    for league,(s,row) in selected.items():
        f=row['fixture'];p=s['payload'];url=endpoint(p['provider'],league,row['provider_fixture_ids'][0],p['season_end_year'])
        response=collector(url,provider=p['provider'],data_type='ROSTER',registry=registry,registry_pin=registry_pin)
        sources.append({k:v for k,v in response.items() if k!='payload'})
        if int(time.time())<=s['payload']['materialized_at_utc']:time.sleep(1.05)
        try:audits.append(audit_endpoint(s,f['canonical_id'],response,registry=registry,registry_pin=registry_pin))
        except (ValueError,KeyError,TypeError,AttributeError) as ex:errors.append(dict(league=league,status=str(ex) if type(ex) is ValueError else 'ABSTAIN_MALFORMED_PREMATCH_SOURCE'))
    observations=[o for a in audits for o in a['observations']]
    if observations and int(time.time())<=max(o['payload']['materialized_at_utc'] for o in observations):time.sleep(1.05)
    return dict(status='PREMATCH_SOURCE_AUDIT_NOT_PREDICTION',network_requests=len(sources),audits=audits,sources=sources,errors=errors,
        observations=len(observations),confirmed_lineups=0,prospective_records_created=0,
        nba_official_access=nba['status'],nba_schedule_is_not_lineup_evidence=True,
        news='ABSTAIN_NO_PERMISSIONED_NEWS_SOURCE',storage='LOCAL_RESEARCH_FILE_ONLY',scheduler='NOT_INSTALLED')


def seal_audit(report,*,registry=REGISTRY,registry_pin=REGISTRY_PIN):
    p=dict(format=FORMAT,schema_version=1,usage='DEVELOPMENT_PREMATCH_SOURCE_AUDIT',created_at_utc=int(time.time()),
        registry_sha256=registry_pin,report=deepcopy(report),prospective_records_created=0)
    sealed=dict(payload=p,sha256=digest(p));validate_audit(sealed,trusted_sha256=sealed['sha256'],registry=registry,registry_pin=registry_pin);return sealed


def validate_audit(sealed,*,trusted_sha256,registry=REGISTRY,registry_pin=REGISTRY_PIN):
    require(type(sealed) is dict and set(sealed)=={'payload','sha256'} and sealed['sha256']==trusted_sha256 and digest(sealed['payload'])==trusted_sha256,'TRUSTED_PREMATCH_AUDIT_PIN_MISMATCH')
    p=sealed['payload'];require(type(p) is dict and set(p)==set('format schema_version usage created_at_utc registry_sha256 report prospective_records_created'.split()) and
        p['format']==FORMAT and type(p['schema_version']) is int and p['schema_version']==1 and p['usage']=='DEVELOPMENT_PREMATCH_SOURCE_AUDIT' and
        p['prospective_records_created']==0 and p['registry_sha256']==registry_pin==digest(registry),'PREMATCH_AUDIT_SCHEMA_OR_POLICY')
    require(type(p['created_at_utc']) is int and 0<p['created_at_utc']<=int(time.time()),'PREMATCH_AUDIT_CLOCK')
    r=p['report'];require(type(r) is dict and type(r['audits']) is list and type(r['sources']) is list and r['network_requests']==len(r['sources']) and
        r['confirmed_lineups']==0 and r['prospective_records_created']==0,'PREMATCH_AUDIT_REPORT_SCHEMA')
    count=0
    for audit in r['audits']:
        require(audit['confirmed_lineups']==0 and audit['prospective_records_created']==0,'PREMATCH_UNVERIFIED_LINEUP_CLAIM')
        require(audit['receipt'] in r['sources'],'PREMATCH_RECEIPT_NOT_IN_MANIFEST')
        if audit['status'] in ('UNCONFIRMED_SOURCE_LISTING_AVAILABLE','ABSTAIN_ROSTER_NOT_PUBLISHED','ABSTAIN_UNSUPPORTED_ROSTER_SCHEMA','ABSTAIN_BOXSCORE_IS_NOT_PREMATCH_ROSTER'):
            require('raw_proof' in audit and digest(audit['raw_proof'])==audit['compact_json_sha256'],'PREMATCH_RAW_PROOF_REQUIRED')
            receipt=audit['receipt']
            require(receipt['status']=='DOCUMENT_RECEIVED' and receipt['http_status']==200 and receipt['source_url']==audit['source_url'] and
                receipt['provider']==audit['provider'] and 0<receipt['observed_at_utc']<=audit['audited_at_utc']<audit['fixture']['start_utc'] and
                audit['audited_at_utc']<=p['created_at_utc'],'PREMATCH_RECEIPT_BINDING')
            derived=derive_listings(audit['raw_proof'],fixture=audit['fixture'],provider=audit['provider'],pid=audit['provider_fixture_id'],observed_at_utc=receipt['observed_at_utc'])
            require(derived['source_url']==audit['source_url'] and derived['status']==audit['status'] and len(derived['listings'])==len(audit['observations']),'PREMATCH_AUDIT_CANNOT_REPLAY')
        for observation in audit['observations']:
            o=replay_listing(observation,fixture=audit['fixture'],cutoff_utc=p['created_at_utc'],maximum_age_seconds=100*366*86400,
                require_permitted=False,registry=registry,registry_pin=registry_pin)
            require(o['provider']==audit['provider'] and o['provider_fixture_id']==audit['provider_fixture_id'] and o['source_url']==audit['source_url'] and
                audit['receipt']['status']=='DOCUMENT_RECEIVED' and audit['receipt']['http_status']==200 and audit['receipt']['source_url']==o['source_url'] and
                audit['receipt']['provider']==o['provider'] and audit['receipt']['observed_at_utc']==o['observed_at_utc'] and
                digest(o['raw']['snapshot'])==audit['compact_json_sha256'],'PREMATCH_RECEIPT_BINDING')
            count+=1
    require(count==r['observations'],'PREMATCH_OBSERVATION_COUNT_MISMATCH')
    return deepcopy(p)


def read_audit(path,**validation):
    p=Path(path);require(p.is_file() and not p.is_symlink() and Path('/data') not in p.resolve().parents and p.stat().st_size<=MAX_BYTES,'READONLY_PREMATCH_AUDIT_REQUIRED')
    return validate_audit(json.loads(p.read_text()),**validation)


def main():
    import argparse
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('--live',action='store_true');a.add_argument('--output');a.add_argument('--source-policy');a.add_argument('--trusted-policy-sha256');args=a.parse_args()
    try:
        require(bool(args.source_policy)==bool(args.trusted_policy_sha256),'SOURCE_POLICY_PAIR_REQUIRED')
        policy=dict(registry=REGISTRY,registry_pin=REGISTRY_PIN)
        if args.source_policy:
            from faz44_policy import read_source_policy
            p=read_source_policy(args.source_policy,trusted_sha256=args.trusted_policy_sha256);policy=dict(registry=p['registry'],registry_pin=p['registry_sha256'])
        report=collect(live=args.live,**policy);out={k:v for k,v in report.items() if k not in ('audits','sources')}
        out['fixture_statuses']=[dict(league=r['fixture']['league'],provider_fixture_id=r['provider_fixture_id'],status=r['status'],source_observations=len(r['observations'])) for r in report['audits']]
        if args.output:
            sealed=seal_audit(report,**policy);created=publish_development_artifact(args.output,sealed,expected_format=FORMAT,filename_prefix='faz46-prematch-')
            out.update(path=str(Path(args.output).resolve()),trusted_audit_sha256=sealed['sha256'],created=created)
        print(json.dumps(out,sort_keys=True,allow_nan=False));return 0
    except (ValueError,KeyError,TypeError,OSError,AttributeError):print(json.dumps(dict(status='ABSTAIN_PREMATCH_AUDIT_NOT_CONFIRMED',prospective_records_created=0)));return 1


if __name__=='__main__':raise SystemExit(main())

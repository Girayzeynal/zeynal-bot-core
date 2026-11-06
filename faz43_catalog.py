"""Official EL/EC catalog inventory. No fabricated per-game HTTP observations.

Catalog completeness and replay are distinct from permission, PIT eligibility,
independent corroboration, player coverage or prospective model performance.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import time

from prediction_inputs import digest
from faz40_archive import require
from faz41_evidence import REGISTRY,REGISTRY_PIN,_policy
from faz41_transport import fetch
from providers.euroleague_live import BASE,identity,audit_catalog,parse_game


def _inventory(raw,league,year,observed):
    catalog=audit_catalog(raw['competition'],raw['season'],raw['games'],league=league,year=year,observed_at_utc=observed)
    completed=[]
    for f in catalog['games']:
        if f['status']!='PLAYED':continue
        g=catalog['raw_games'][f['provider_fixture_id']]
        quarters={s:[int(g[key]['partials']['partials'+str(i)]) for i in range(1,5)] for s,key in [('home','local'),('away','road')]}
        completed.append(dict(provider_fixture_id=f['provider_fixture_id'],start_utc=f['start_ts_utc'],home_team_id=f['home_team_id'],
            away_team_id=f['away_team_id'],quarters=quarters,regulation_home=sum(quarters['home']),regulation_away=sum(quarters['away']),
            final_home=f['actual_home'],final_away=f['actual_away'],scope='FINAL_WITH_OT',duration_minutes=f['duration_minutes']))
    return dict(league=league,season_end_year=year+1,total_catalog_rows=catalog['total_raw'],accepted_unique=catalog['accepted_unique'],
        completed_period_games=len(completed),scheduled_games=sum(g['status']=='UNPLAYED' for g in catalog['games']),
        invalid_records=catalog['invalid_records'],duplicate_identical=catalog['duplicate_identical'],
        conflicting_records=catalog['conflicting_records'],completed=completed,
        player_stats_games=0,verified_pbp_games=0,verified_lineup_games=0,
        per_game_endpoint_requests=0,catalog_is_not_per_game_fetch=True)


def seal_catalog(raw,*,league,year,source_receipts,registry=REGISTRY,registry_pin=REGISTRY_PIN):
    league,code,_,season=identity(league,year);now=int(time.time())
    urls=[f'{BASE}/{code}',f'{BASE}/{code}/seasons/{season}',f'{BASE}/{code}/seasons/{season}/games']
    require(type(source_receipts) is list and len(source_receipts)==3,'THREE_CATALOG_SOURCE_RECEIPTS_REQUIRED')
    for name,url,receipt in zip(('competition','season','games'),urls,source_receipts):
        policy=_policy('EUROLEAGUE_LIVE',url,'OFFICIAL_STAT',registry,registry_pin)
        require(set(receipt)==set('source_url observed_at_utc ingested_at_utc response_sha256'.split()) and receipt['source_url']==url and
                all(type(receipt[k]) is int for k in ('observed_at_utc','ingested_at_utc')) and
                0<receipt['observed_at_utc']<=receipt['ingested_at_utc']<=now and receipt['response_sha256']==digest(raw[name]),
                'CATALOG_RECEIPT_ORIGIN_TIME_OR_DIGEST')
    observed=max(s['observed_at_utc'] for s in source_receipts)
    facts=_inventory(raw,league,year,observed)
    p=dict(schema_version=1,league=league,year=year,raw=deepcopy(raw),raw_sha256=digest(raw),
        source_receipts=deepcopy(source_receipts),materialized_at_utc=now,registry_sha256=registry_pin,
        usage_status=policy['usage'],usage='RETROSPECTIVE_CATALOG_RESEARCH',facts=facts,
        provenance='LOCAL_HASH_NOT_INDEPENDENT_SOURCE_ATTESTATION')
    return dict(payload=p,sha256=digest(p))


def replay_catalog(sealed,*,asof_utc,registry=REGISTRY,registry_pin=REGISTRY_PIN,require_permitted=True):
    try:
        p=sealed['payload']
        require(set(sealed)=={'payload','sha256'} and set(p)==set('schema_version league year raw raw_sha256 source_receipts materialized_at_utc registry_sha256 usage_status usage facts provenance'.split()),'CATALOG_SCHEMA')
        require(type(p['schema_version']) is int and p['schema_version']==1 and digest(p)==sealed['sha256'] and
                digest(p['raw'])==p['raw_sha256'] and p['registry_sha256']==registry_pin,'CATALOG_DIGEST_OR_POLICY')
        require(type(asof_utc) is int and type(p['materialized_at_utc']) is int and
                0<p['materialized_at_utc']<asof_utc<=int(time.time()),'CATALOG_UNAVAILABLE_AT_CUTOFF')
        require(all(type(s['ingested_at_utc']) is int and s['ingested_at_utc']<=p['materialized_at_utc'] for s in p['source_receipts']),'RECEIPT_AFTER_MATERIALIZATION')
        rebuilt=seal_catalog(p['raw'],league=p['league'],year=p['year'],source_receipts=p['source_receipts'],registry=registry,registry_pin=registry_pin)['payload']
        rebuilt['materialized_at_utc']=p['materialized_at_utc'];require(rebuilt==p,'CATALOG_CANNOT_REPLAY')
        if require_permitted:
            policy=registry['EUROLEAGUE_LIVE'];require(policy['usage']=='PERMITTED','CATALOG_USAGE_NOT_ESTABLISHED')
            require(policy['reviewed_at_utc']<asof_utc<=policy['expires_at_utc'],'CATALOG_PERMISSION_NOT_VALID_AT_CUTOFF')
        return deepcopy(p['facts'])
    except (KeyError,TypeError,AttributeError,OverflowError) as ex:raise ValueError('MALFORMED_CATALOG_EVIDENCE') from ex


def collect(*,live=False,year=2026,collector=fetch):
    if live is not True:return dict(status='ABSTAIN_LIVE_ACCESS_NOT_REQUESTED',network_requests=0,prospective_records_created=0)
    reports=[]
    for league in ('EUROLEAGUE','EUROCUP'):
        _,code,_,season=identity(league,year)
        urls=[f'{BASE}/{code}',f'{BASE}/{code}/seasons/{season}',f'{BASE}/{code}/seasons/{season}/games']
        with ThreadPoolExecutor(max_workers=3) as pool:responses=list(pool.map(lambda u:collector(u,provider='EUROLEAGUE_LIVE'),urls))
        sources=[{k:v for k,v in r.items() if k!='payload'} for r in responses]
        row=dict(league=league,sources=sources,status='ABSTAIN_PROVIDER_UNAVAILABLE')
        if all(r['status']=='DOCUMENT_RECEIVED' for r in responses):
            raw=dict(zip(('competition','season','games'),[r['payload'] for r in responses]))
            receipts=[dict(source_url=url,observed_at_utc=r['observed_at_utc'],ingested_at_utc=int(time.time()),response_sha256=digest(r['payload'])) for url,r in zip(urls,responses)]
            try:
                sealed=seal_catalog(raw,league=league,year=year,source_receipts=receipts)
                p=sealed['payload'];row.update(status='CATALOG_INVENTORY_ONLY',facts=p['facts'],source_receipts=receipts,
                    materialized_at_utc=p['materialized_at_utc'],catalog_sha256=sealed['sha256'],usage_status=p['usage_status'],
                    model_eligible_games=0,model_status='ABSTAIN_USAGE_NOT_ESTABLISHED')
            except (ValueError,KeyError,TypeError) as ex:row.update(status='ABSTAIN_INVALID_CATALOG',reason=str(ex) if type(ex) is ValueError else 'INVALID_PROVIDER_SCHEMA')
        reports.append(row)
    return dict(status='LIVE_CATALOG_AUDIT_NOT_MODEL_PERFORMANCE',reports=reports,network_requests=6,
                prospective_records_created=0,training_performed=False,raw_payloads_published=False)

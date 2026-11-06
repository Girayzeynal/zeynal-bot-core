"""Track B fixture discovery; reuses FAZ33 NBA and official EL/EC parsers."""
from copy import deepcopy
from datetime import datetime,timezone
import time
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from prediction_inputs import digest
from faz40_archive import require
from faz41_evidence import REGISTRY,REGISTRY_PIN,_policy,fixture_identity
from faz41_adapters import ESPN_ABBREVIATIONS
from nba_season_2027 import parse_scheduled
from providers.euroleague_live import parse_game,BASE


def _parse(raw,provider,league,season,at):
    if provider=='ESPN':
        require(league=='NBA' and season==2027,'UNSUPPORTED_SCHEDULE_PARTITION')
        events=raw['events'];require(type(events) is list,'SCHEDULE_EVENTS_REQUIRED')
    else:
        require(provider=='EUROLEAGUE_LIVE' and league in ('EUROLEAGUE','EUROCUP'),'UNSUPPORTED_SCHEDULE_PROVIDER')
        events=raw['data'];require(type(events) is list and type(raw['total']) is int and len(events)==raw['total'],'INCOMPLETE_SCHEDULE_CATALOG')
    require(len(events)<=1000,'SCHEDULE_SIZE_LIMIT')
    fixtures={};aliases={};slots={};rejected=[]
    for event in events:
        try:
            if provider=='ESPN':p=parse_scheduled(event,set(ESPN_ABBREVIATIONS))
            else:
                p=parse_game(event,league=league,year=season-1,observed_at_utc=at)
                require(p is not None and p['status']=='UNPLAYED','NOT_CONFIRMED_UNPLAYED')
            f=fixture_identity(league=league,season_end_year=season,start_utc=p['start_ts_utc'],
                               home_team_id=p['home_team_id'],away_team_id=p['away_team_id'])
            require(f['start_utc']>at,'ALREADY_STARTED')
            cid=f['canonical_id'];pid=p['provider_fixture_id']
            require(pid not in aliases or aliases[pid]==cid,'PROVIDER_FIXTURE_IDENTITY_CONFLICT');aliases[pid]=cid
            for side in ('home','away'):
                slot=(f[side+'_team_id'],f['start_utc'])
                require(slot not in slots or slots[slot]==cid,'SAME_TEAM_START_CONFLICT');slots[slot]=cid
            if cid not in fixtures:fixtures[cid]=dict(fixture=f,provider_fixture_ids=[])
            fixtures[cid]['provider_fixture_ids']=sorted(set(fixtures[cid]['provider_fixture_ids']+[pid]))
        except (ValueError,KeyError,TypeError,AttributeError) as ex:
            if str(ex) in ('PROVIDER_FIXTURE_IDENTITY_CONFLICT','SAME_TEAM_START_CONFLICT'):raise
            rejected.append(dict(provider_fixture_id=event.get('id',event.get('identifier')) if type(event) is dict else None,
                                 reason=str(ex) if type(ex) is ValueError else 'MALFORMED_SCHEDULE_EVENT'))
    return sorted(fixtures.values(),key=lambda r:(r['fixture']['start_utc'],r['fixture']['canonical_id'])),rejected


def _endpoint(provider,league,season,source_url):
    expected='/apis/site/v2/sports/basketball/nba/scoreboard' if provider=='ESPN' else \
             '/v2/competitions/'+('E' if league=='EUROLEAGUE' else 'U')+'/seasons/'+('E' if league=='EUROLEAGUE' else 'U')+str(season-1)+'/games'
    require(urlsplit(source_url).path==expected,'SCHEDULE_ENDPOINT_MISMATCH')


def seal_schedule(raw,*,provider,league,season_end_year,source_url,observed_at_utc,ingested_at_utc,
                  usage='LIVE_DISCOVERY',registry=REGISTRY,registry_pin=REGISTRY_PIN):
    policy=_policy(provider,source_url,'OFFICIAL_STAT',registry,registry_pin)
    _endpoint(provider,league,season_end_year,source_url)
    now=int(time.time());require(type(observed_at_utc) is int and type(ingested_at_utc) is int and
                               0<observed_at_utc<=ingested_at_utc<=now,'SCHEDULE_CHRONOLOGY')
    require(usage in ('SYNTHETIC_TEST','LIVE_DISCOVERY'),'SCHEDULE_USAGE_REQUIRED')
    fixtures,rejected=_parse(raw,provider,league,season_end_year,now)
    p=dict(schema_version=1,provider=provider,league=league,season_end_year=season_end_year,source_url=source_url,
        observed_at_utc=observed_at_utc,ingested_at_utc=ingested_at_utc,materialized_at_utc=now,
        registry_sha256=registry_pin,usage_status=policy['usage'],usage=usage,raw=deepcopy(raw),raw_sha256=digest(raw),
        fixtures=fixtures,rejected=rejected,source_attestation='NOT_INDEPENDENTLY_VERIFIED')
    return dict(payload=p,sha256=digest(p))


def validate_schedule(sealed,*,cutoff_utc,maximum_age_seconds=300,require_permitted=True,
                      registry=REGISTRY,registry_pin=REGISTRY_PIN):
    try:
        require(type(cutoff_utc) is int and 0<cutoff_utc<=int(time.time()) and
                type(maximum_age_seconds) is int and maximum_age_seconds>0,'INVALID_SCHEDULE_CUTOFF')
        require(type(sealed) is dict and set(sealed)=={'payload','sha256'},'SCHEDULE_ENVELOPE')
        p=sealed['payload'];require(type(p) is dict and set(p)==set('schema_version provider league season_end_year source_url observed_at_utc ingested_at_utc materialized_at_utc registry_sha256 usage_status usage raw raw_sha256 fixtures rejected source_attestation'.split()),'SCHEDULE_PAYLOAD_SCHEMA')
        require(p['source_attestation']=='NOT_INDEPENDENTLY_VERIFIED' and digest(p)==sealed['sha256'] and type(p['schema_version']) is int and p['schema_version']==1 and
                                   digest(p['raw'])==p['raw_sha256'],'SCHEDULE_DIGEST_MISMATCH')
        require(all(type(p[k]) is int for k in ('observed_at_utc','ingested_at_utc','materialized_at_utc')) and
                0<p['observed_at_utc']<=p['ingested_at_utc']<=p['materialized_at_utc']<cutoff_utc,'SCHEDULE_NOT_AVAILABLE_AT_CUTOFF')
        policy=_policy(p['provider'],p['source_url'],'OFFICIAL_STAT',registry,registry_pin)
        _endpoint(p['provider'],p['league'],p['season_end_year'],p['source_url'])
        require(p['registry_sha256']==registry_pin and p['usage_status']==policy['usage'],'SCHEDULE_POLICY_BINDING')
        # Replay captured schedule at its original creation time, also after tipoff.
        fixtures,rejected=_parse(p['raw'],p['provider'],p['league'],p['season_end_year'],p['materialized_at_utc'])
        require(fixtures==p['fixtures'] and rejected==p['rejected'] and p['usage'] in ('SYNTHETIC_TEST','LIVE_DISCOVERY'),
                'SCHEDULE_CANNOT_REPLAY')
        require(cutoff_utc-p['observed_at_utc']<=maximum_age_seconds,'STALE_SCHEDULE')
        if require_permitted:
            require(policy['usage']=='PERMITTED','SCHEDULE_USAGE_NOT_ESTABLISHED')
            require(policy['reviewed_at_utc']<cutoff_utc<=policy['expires_at_utc'],'SCHEDULE_PERMISSION_NOT_VALID_AT_CUTOFF')
        return deepcopy(p)
    except (KeyError,TypeError,AttributeError,OverflowError) as ex:raise ValueError('MALFORMED_SCHEDULE_EVIDENCE') from ex


def fixture_times(fixture):
    utc=datetime.fromtimestamp(fixture['start_utc'],timezone.utc)
    return dict(start_utc=utc.isoformat(),start_turkey=utc.astimezone(ZoneInfo('Europe/Istanbul')).isoformat())

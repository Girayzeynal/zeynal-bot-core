"""Replay-bound historical game observations; no fetch, DB writes or live claims.

Integrity/semantic replay is not independent attestation of source timestamps.
INGESTION_TIME includes materialization; ARCHIVED_SOURCE_CLOCK is research only.
"""
from copy import deepcopy
import time

from nba_research_store import validate_summary
from prediction_inputs import digest
from providers.euroleague_live import BASE, parse_game

LEAGUES = ('NBA','EUROLEAGUE','EUROCUP')
MODES = ('INGESTION_TIME','ARCHIVED_SOURCE_CLOCK')


def require(condition,reason):
    if not condition:raise ValueError(reason)


def _facts(raw,league,season_end_year,observed,team_ids):
    require(league in LEAGUES,'UNSUPPORTED_ARCHIVE_PROVIDER_OR_LEAGUE')
    require(type(season_end_year) is int and 2001<=season_end_year<=2100,'INVALID_SEASON')
    require(type(team_ids) is list and len(set(team_ids))==len(team_ids) and len(team_ids)>=2 and
            all(type(t) is str and t and t==t.strip() for t in team_ids),'INVALID_TEAM_DIRECTORY')
    if league=='NBA':
        parsed=validate_summary(raw,observed,set(team_ids));event=parsed['event']
        require(raw['header']['season']['year']==season_end_year,'SEASON_MISMATCH')
        home,away=parsed['periods']['home'],parsed['periods']['away']
        provider='ESPN';url='https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event='+event['provider_fixture_id']
    else:
        event=parse_game(raw,league=league,year=season_end_year-1,observed_at_utc=observed)
        require(event is not None and event['status']=='PLAYED','VERIFIED_COMPLETED_GAME_REQUIRED')
        require(all(event[s+'_team_id'] in team_ids for s in ('home','away')),'UNKNOWN_CANONICAL_TEAM')
        def periods(side):
            part=raw[side]['partials']
            return [int(part['partials'+str(i)]) for i in range(1,5)]+[int(part['extraPeriods'][str(i+1)]) for i in range(len(part['extraPeriods']))]
        home,away=periods('local'),periods('road')
        provider='EUROLEAGUE_LIVE'
        url=BASE+'/'+event['competition_code']+'/seasons/'+event['season_code']+'/games/'+str(event['game_code'])
    identity=dict(league=league,season_end_year=season_end_year,start_utc=event['start_ts_utc'],
                  home_team_id=event['home_team_id'],away_team_id=event['away_team_id'])
    return dict(identity,canonical_id=digest(identity),provider=provider,fixture_id=event['provider_fixture_id'],
                source_url=url,quarters_home=home[:4],quarters_away=away[:4],
                overtime_home=home[4:],overtime_away=away[4:],regulation_home=sum(home[:4]),
                regulation_away=sum(away[:4]),final_home=sum(home),final_away=sum(away),
                regulation_scope='REGULATION_ONLY',final_scope='FINAL_WITH_OT')


def seal_game(raw,*,league,season_end_year,source_observed_utc,ingested_utc,team_ids,
              usage='RETROSPECTIVE_RESEARCH'):
    now=int(time.time())
    require(usage in ('RETROSPECTIVE_RESEARCH','SYNTHETIC_TEST'),'LIVE_RECORD_CREATION_FORBIDDEN')
    require(type(source_observed_utc) is int and type(ingested_utc) is int and
            0<source_observed_utc<=ingested_utc<=now,'INVALID_SOURCE_INGESTION_CLOCKS')
    require(isinstance(team_ids,(list,tuple,set)) and
            all(type(t) is str and t and t==t.strip() for t in team_ids),'INVALID_TEAM_DIRECTORY')
    directory=sorted(team_ids)
    facts=_facts(raw,league,season_end_year,source_observed_utc,directory)
    p=dict(schema_version=1,usage=usage,league=league,season_end_year=season_end_year,
           source_observed_utc=source_observed_utc,ingested_utc=ingested_utc,materialized_utc=now,
           source_json_sha256=digest(raw),raw=deepcopy(raw),team_ids=directory,
           directory_sha256=digest(directory),facts=facts,
           provenance='JSON_REPLAY_BOUND_NOT_INDEPENDENTLY_ATTESTED')
    return dict(payload=p,sha256=digest(p))


def replay_game(record):
    try:
        require(type(record) is dict and set(record)=={'payload','sha256'},'ARCHIVE_ENVELOPE_SCHEMA')
        p=record['payload']
        require(type(p) is dict and set(p)==set('schema_version usage league season_end_year source_observed_utc '
                'ingested_utc materialized_utc source_json_sha256 raw team_ids directory_sha256 facts provenance'.split()),'ARCHIVE_PAYLOAD_SCHEMA')
        require(record['sha256']==digest(p) and p['source_json_sha256']==digest(p['raw']) and
                p['directory_sha256']==digest(p['team_ids']),'ARCHIVE_DIGEST_MISMATCH')
        require(type(p['schema_version']) is int and p['schema_version']==1 and
                p['usage'] in ('RETROSPECTIVE_RESEARCH','SYNTHETIC_TEST') and
                p['provenance']=='JSON_REPLAY_BOUND_NOT_INDEPENDENTLY_ATTESTED','ARCHIVE_USAGE_SCHEMA')
        require(all(type(p[k]) is int for k in ('source_observed_utc','ingested_utc','materialized_utc')) and
                0<p['source_observed_utc']<=p['ingested_utc']<=p['materialized_utc']<=int(time.time()),'ARCHIVE_CHRONOLOGY')
        expected=_facts(p['raw'],p['league'],p['season_end_year'],p['source_observed_utc'],p['team_ids'])
        require(p['facts']==expected,'ARCHIVE_SEMANTIC_MISMATCH')
        return deepcopy(p)
    except (KeyError,TypeError,AttributeError,IndexError,OverflowError) as exc:
        raise ValueError('MALFORMED_ARCHIVE_OBSERVATION') from exc


def select_games(records,*,league,season_end_year,cutoff_utc,mode='INGESTION_TIME'):
    require(league in LEAGUES and type(season_end_year) is int,'INVALID_ARCHIVE_PARTITION')
    require(type(cutoff_utc) is int and 0<cutoff_utc<=int(time.time()) and mode in MODES,'INVALID_ARCHIVE_CUTOFF_OR_MODE')
    require(type(records) is list,'ARCHIVE_LIST_REQUIRED')
    games={};slots={};provider_ids={};usages=set()
    for record in records:
        p=replay_game(record);f=p['facts']
        if p['league']!=league or p['season_end_year']!=season_end_year:continue
        available=p['source_observed_utc'] if mode=='ARCHIVED_SOURCE_CLOCK' else p['materialized_utc']
        if available>=cutoff_utc:continue
        usages.add(p['usage']);require(len(usages)==1,'MIXED_SYNTHETIC_REAL_ARCHIVE')
        cid=f['canonical_id'];pid=(f['provider'],f['fixture_id'])
        require(pid not in provider_ids or provider_ids[pid]==cid,'PROVIDER_FIXTURE_IDENTITY_CONFLICT')
        provider_ids[pid]=cid
        for team in (f['home_team_id'],f['away_team_id']):
            slot=(team,f['start_utc'])
            require(slot not in slots or slots[slot]==cid,'SAME_TEAM_START_CONFLICT')
            slots[slot]=cid
        if cid in games:
            old=games[cid]
            semantic=lambda item:{k:v for k,v in item.items() if k not in ('fixture_id','provider','source_url')}
            require(semantic(old['facts'])==semantic(f),'CONFLICTING_CANONICAL_GAME')
            old['observation_sha256']=sorted(set(old['observation_sha256']+[record['sha256']]))
            old['provider_aliases']=sorted(set(old['provider_aliases']+[f['provider']+':'+f['fixture_id']]))
            old['available_utc']=min(old['available_utc'],available)
            if (f['provider'],f['fixture_id'])<(old['facts']['provider'],old['facts']['fixture_id']):old['facts']=f
        else:
            games[cid]=dict(facts=f,available_utc=available,observation_sha256=[record['sha256']],
                            provider_aliases=[f['provider']+':'+f['fixture_id']],usage=p['usage'])
    return sorted(games.values(),key=lambda g:(g['facts']['start_utc'],g['facts']['canonical_id']))

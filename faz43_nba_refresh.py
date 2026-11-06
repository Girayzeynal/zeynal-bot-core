"""Bounded, read-only NBA research refresh. No legacy DB/forecast writes.

Persists normalized public score facts in returned research evidence, not full
provider articles/odds/player text. New observations retain today's timestamps.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import time
import re
from zoneinfo import ZoneInfo

from prediction_inputs import digest
from faz40_archive import require,replay_game
from faz41_adapters import normalize,ESPN_ABBREVIATIONS
from faz41_transport import fetch
from nba_research_store import compact_summary
from nba_season_2027 import require_regular
from providers.espn_completed_event import parse_completed_nba_event

BASE='https://site.api.espn.com/apis/site/v2/sports/basketball/nba'


def completed_candidate(event,observed,*,day):
    e=parse_completed_nba_event(event,datetime.fromtimestamp(observed,timezone.utc));require(e is not None,'VERIFIED_COMPLETED_SCOREBOARD_REQUIRED')
    require(event['id']==event['competitions'][0]['id'] and e['provider_fixture_id'].isascii() and e['provider_fixture_id'].isdigit(),'SCOREBOARD_EVENT_ID_CONFLICT')
    for status in (event.get('status'),event['competitions'][0].get('status')):
        if status is not None:require(status['type']['completed'] is True and status['type']['state'] in ('post','completed'),'SCOREBOARD_STATUS_CONFLICT')
    require_regular(event,e['start_ts_utc'])
    require(e['home_team_id'] in ESPN_ABBREVIATIONS and e['away_team_id'] in ESPN_ABBREVIATIONS,'UNKNOWN_NBA_TEAM')
    require(datetime.fromtimestamp(e['start_ts_utc'],ZoneInfo('America/New_York')).date().strftime('%Y%m%d')==day,'SCOREBOARD_CALENDAR_MISMATCH')
    return e


def replay_research_fact(record,*,asof_utc):
    p=record['payload'];require(set(record)=={'payload','sha256'} and set(p)==set('schema_version usage usage_status source_url observed_at_utc ingested_at_utc materialized_at_utc published_at_utc response_sha256 compact_summary normalized scoreboard_fact scoreboard_url scoreboard_response_sha256 provenance prospective_records_created'.split()),'RESEARCH_FACT_SCHEMA')
    require(p['published_at_utc'] is None and p['prospective_records_created']==0 and p['provenance']=='NORMALIZED_SECONDARY_SOURCE_FACTS_NOT_INDEPENDENT_ATTESTATION' and all(type(p[k]) is str and re.fullmatch('[0-9a-f]{64}',p[k]) for k in ('response_sha256','scoreboard_response_sha256')),'RESEARCH_FACT_UNVERIFIED_CLAIMS')
    require(record['sha256']==digest(p) and type(p['schema_version']) is int and p['schema_version']==1 and
        p['usage']=='RETROSPECTIVE_RESEARCH' and p['usage_status']=='UNKNOWN','RESEARCH_FACT_SCHEMA_OR_DIGEST')
    require(all(type(p[k]) is int for k in ('observed_at_utc','ingested_at_utc','materialized_at_utc')) and
            0<p['observed_at_utc']<=p['ingested_at_utc']<=p['materialized_at_utc']<=asof_utc<=int(time.time()),'RESEARCH_FACT_CHRONOLOGY')
    n=normalize(p['compact_summary'],provider='ESPN',league='NBA',season_end_year=2027,observed_at_utc=p['observed_at_utc'],data_type='OFFICIAL_STAT')
    require(n==p['normalized'] and n['source_url']==p['source_url'],'RESEARCH_SUMMARY_CANNOT_REPLAY')
    e=p['scoreboard_fact'];f=n['fixture'];q=n['claims']
    day=datetime.fromtimestamp(f['start_utc'],ZoneInfo('America/New_York')).date().strftime('%Y%m%d')
    require(p['scoreboard_url']==BASE+'/scoreboard?dates='+day,'SCOREBOARD_ORIGIN_MISMATCH')
    require(e['provider_fixture_id']==n['provider_fixture_id'] and e['start_ts_utc']==f['start_utc'] and
            all(e[s+'_team_id']==f[s+'_team_id'] and e['actual_'+s]==q['final_'+s] for s in ('home','away')),
            'SCOREBOARD_SUMMARY_CONFLICT')
    return deepcopy(n)


def collect(existing,*,live=False,history_days=2,max_new_games=12,collector=fetch):
    require(type(history_days) is int and 1<=history_days<=3 and type(max_new_games) is int and 1<=max_new_games<=12,'BOUNDED_REFRESH_REQUIRED')
    require(type(existing) is list,'EXISTING_ARCHIVE_REQUIRED')
    baseline={};aliases={};slots={};merged_claims={}
    for sealed in existing:
        p=replay_game(sealed);f=p['facts'];require(f['league']=='NBA','NBA_ARCHIVE_ONLY')
        cid=f['canonical_id'];prior=baseline.get(cid)
        if prior:require(all(prior[k]==f[k] for k in ('final_home','final_away','quarters_home','quarters_away','overtime_home','overtime_away')),'CONFLICTING_EXISTING_FINAL')
        require(f['fixture_id'] not in aliases or aliases[f['fixture_id']]==cid,'EXISTING_PROVIDER_ID_CONFLICT')
        baseline[cid]=f;aliases[f['fixture_id']]=cid
        merged_claims[cid]={k:f[k] for k in ('quarters_home','quarters_away','overtime_home','overtime_away','regulation_home','regulation_away','final_home','final_away')}
        for side in ('home','away'):
            slot=(f[side+'_team_id'],f['start_utc']);require(slot not in slots or slots[slot]==cid,'EXISTING_TEAM_START_CONFLICT');slots[slot]=cid
    if live is not True:return dict(status='ABSTAIN_LIVE_ACCESS_NOT_REQUESTED',existing_games=len(baseline),network_requests=0,new_games=[],prospective_records_created=0)
    today=datetime.fromtimestamp(time.time(),ZoneInfo('America/New_York')).date();sources=[];candidates={};rejected=[]
    for offset in range(history_days):
        day=(today-timedelta(days=offset)).strftime('%Y%m%d');url=BASE+'/scoreboard?dates='+day;response=collector(url,provider='ESPN')
        sources.append({k:v for k,v in response.items() if k!='payload'})
        if response['status']!='DOCUMENT_RECEIVED':continue
        require(type(response['payload'].get('events')) is list,'SCOREBOARD_EVENTS_REQUIRED')
        for event in response['payload']['events']:
            try:
                e=completed_candidate(event,response['observed_at_utc'],day=day)
                pid=e['provider_fixture_id']
                if pid in aliases:
                    f=baseline[aliases[pid]];require(e['start_ts_utc']==f['start_utc'] and all(e[s+'_team_id']==f[s+'_team_id'] and e['actual_'+s]==f['final_'+s] for s in ('home','away')),'EXISTING_SCOREBOARD_CONFLICT')
                    continue
                if pid in candidates:require(candidates[pid]['fact']==e,'CONFLICTING_SCOREBOARD_OBSERVATIONS')
                candidates[pid]=dict(fact=e,scoreboard_url=url,scoreboard_response_sha256=digest(response['payload']))
            except (ValueError,KeyError,TypeError) as ex:
                if str(ex) in ('EXISTING_SCOREBOARD_CONFLICT','CONFLICTING_SCOREBOARD_OBSERVATIONS'):raise
                rejected.append(dict(provider_fixture_id=event.get('id') if type(event) is dict else None,reason=str(ex) if type(ex) is ValueError else 'MALFORMED_SCOREBOARD_EVENT'))
    selected=sorted(candidates.values(),key=lambda x:(x['fact']['start_ts_utc'],x['fact']['provider_fixture_id']))[:max_new_games]
    with ThreadPoolExecutor(max_workers=3) as pool:
        responses=list(pool.map(lambda x:collector(BASE+'/summary?event='+x['fact']['provider_fixture_id'],provider='ESPN'),selected))
    added=[];new_cids=set();players={}
    for item,response in zip(selected,responses):
        sources.append({k:v for k,v in response.items() if k!='payload'})
        if response['status']!='DOCUMENT_RECEIVED':continue
        try:
            observed=response['observed_at_utc'];raw=response['payload'];n=normalize(raw,provider='ESPN',league='NBA',season_end_year=2027,observed_at_utc=observed,data_type='OFFICIAL_STAT')
            p=dict(schema_version=1,usage='RETROSPECTIVE_RESEARCH',usage_status='UNKNOWN',source_url=response['source_url'],
                observed_at_utc=observed,ingested_at_utc=int(time.time()),materialized_at_utc=int(time.time()),
                published_at_utc=None,response_sha256=digest(raw),compact_summary=compact_summary(raw),normalized=n,
                scoreboard_fact=item['fact'],scoreboard_url=item['scoreboard_url'],scoreboard_response_sha256=item['scoreboard_response_sha256'],
                provenance='NORMALIZED_SECONDARY_SOURCE_FACTS_NOT_INDEPENDENT_ATTESTATION',prospective_records_created=0)
            record=dict(payload=p,sha256=digest(p));replay_research_fact(record,asof_utc=int(time.time()));f=n['fixture'];cid=f['canonical_id']
            for side in ('home','away'):
                slot=(f[side+'_team_id'],f['start_utc']);require(slot not in slots or slots[slot]==cid,'NEW_TEAM_START_ALIAS_CONFLICT')
            if cid in merged_claims:require(merged_claims[cid]==n['claims'],'NEW_ALIAS_FINAL_CONFLICT')
            else:merged_claims[cid]=n['claims']
            if cid not in baseline and cid not in new_cids:added.append(record);new_cids.add(cid)
            for side in ('home','away'):slots[(f[side+'_team_id'],f['start_utc'])]=cid
            try:
                minute=normalize(raw,provider='ESPN',league='NBA',season_end_year=2027,observed_at_utc=observed,data_type='PLAYER_MINUTES')
                rows=[r for entries in minute['claims']['teams'].values() for r in entries]
                players[cid]=dict(canonical_id=cid,status='SOURCE_MINUTES_RECONCILED_PERMISSION_UNKNOWN',player_entries=len(rows),
                                    reported_minutes_rows=sum(r['minutes'] is not None for r in rows))
            except (ValueError,KeyError,TypeError):players[cid]=dict(canonical_id=cid,status='ABSTAIN_PLAYER_DATA')
        except (ValueError,KeyError,TypeError) as ex:
            if str(ex) in ('NEW_TEAM_START_ALIAS_CONFLICT','NEW_ALIAS_FINAL_CONFLICT'):raise
            rejected.append(dict(provider_fixture_id=item['fact']['provider_fixture_id'],reason=str(ex) if type(ex) is ValueError else 'INVALID_SUMMARY'))
    return dict(status='BOUNDED_NBA_RESEARCH_REFRESH',existing_games=len(baseline),discovered_missing_games=len(candidates),
        selected_missing_games=len(selected),deferred_by_budget=max(0,len(candidates)-len(selected)),new_games=added,
        unique_new_games=len(new_cids),union_period_games=len(baseline)+len(new_cids),player_coverage=[players[k] for k in sorted(players)],
        sources=sources,rejected=rejected,network_requests=history_days+len(selected),usage_status='UNKNOWN',
        model_eligible_games=0,prospective_records_created=0,legacy_database_modified=False,
        independent_nba_confirmation=False,model_coefficients_changed=False)

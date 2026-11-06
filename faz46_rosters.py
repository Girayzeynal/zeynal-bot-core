"""Actual endpoint listings, never inferred official lineups or future starters.

Only EuroLeague/EuroCup stats player-list metadata has a replayable listing
adapter here. ESPN pregame headers are checked, but historical boxscore players
and unknown roster schemas remain ABSTAIN. NBA official access is audited apart.
"""
from copy import deepcopy
import re
import time

from prediction_inputs import digest
from faz40_archive import require
from faz41_evidence import fixture_identity,_fixture,seal_observation,validate_observation,REGISTRY,REGISTRY_PIN
from faz41_adapters import ESPN_ABBREVIATIONS
from faz42_schedule import validate_schedule
from nba_season_2027 import parse_scheduled
from providers.euroleague_live import parse_game,BASE


def _unplayed_value(value):
    return value is None or type(value) in (int,float) and value==0 or type(value) is str and value in ('','0','0.0')


def endpoint(provider,league,pid,season):
    if provider=='ESPN':
        require(league=='NBA' and re.fullmatch('[0-9]+',pid),'PREMATCH_PROVIDER_ID_REQUIRED')
        return 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event='+pid
    require(provider=='EUROLEAGUE_LIVE' and league in ('EUROLEAGUE','EUROCUP'),'PREMATCH_PROVIDER_ADAPTER_UNAVAILABLE')
    code='E' if league=='EUROLEAGUE' else 'U';m=re.fullmatch(code+str(season-1)+r'_([1-9]\d{0,3})',pid)
    require(m is not None,'PREMATCH_PROVIDER_ID_REQUIRED')
    return BASE+'/'+code+'/seasons/'+code+str(season-1)+'/games/'+m[1]+'/stats'


def compact_endpoint(raw,provider):
    if provider!='ESPN':return deepcopy(raw)
    proof=dict(header=deepcopy(raw['header']))
    if 'rosters' in raw:proof['rosters']=deepcopy(raw['rosters'])
    if type(raw.get('boxscore')) is dict and 'players' in raw['boxscore']:
        proof['boxscore']={'players':deepcopy(raw['boxscore']['players'])}
    return proof


def derive_listings(raw,*,fixture,provider,pid,observed_at_utc):
    _fixture(fixture);require(type(observed_at_utc) is int and 0<observed_at_utc<fixture['start_utc'],'PREMATCH_OBSERVATION_REQUIRED')
    league=fixture['league'];season=fixture['season_end_year'];url=endpoint(provider,league,pid,season)
    if provider=='ESPN':
        event=deepcopy(raw['header']);c=event['competitions'][0]
        for status in (event.get('status'),c.get('status')):
            if status is not None:require(status['type']['state']=='pre' and status['type']['completed'] is False and status['type']['name']=='STATUS_SCHEDULED','PREMATCH_STATUS_REQUIRED')
        event.setdefault('date',c['date']);event.setdefault('status',c['status'])
        require(event['id']==c['id']==pid,'PREMATCH_PROVIDER_ID_CONFLICT')
        parsed=parse_scheduled(event,set(ESPN_ABBREVIATIONS))
        require(all(_unplayed_value(t.get('score')) for t in c['competitors']),'PREMATCH_HAS_PLAYED_STATISTICS')
        reason='ABSTAIN_UNSUPPORTED_ROSTER_SCHEMA' if raw.get('rosters') else 'ABSTAIN_BOXSCORE_IS_NOT_PREMATCH_ROSTER' if raw.get('boxscore',{}).get('players') else 'ABSTAIN_ROSTER_NOT_PUBLISHED'
        listings={}
    else:
        parsed=parse_game(raw['game'],league=league,year=season-1,observed_at_utc=observed_at_utc)
        require(parsed is not None and parsed['status']=='UNPLAYED' and parsed['provider_fixture_id']==pid,'PREMATCH_GAME_REQUIRED')
        for side in ('local','road'):
            team=raw['game'][side];parts=team.get('partials') or {}
            require(_unplayed_value(team.get('score')) and all(_unplayed_value(parts.get('partials'+str(i))) for i in range(1,5)) and not parts.get('extraPeriods'),'PREMATCH_HAS_PLAYED_STATISTICS')
        listings={};seen=set();reason='ABSTAIN_ROSTER_NOT_PUBLISHED'
        for side,team in [('local',fixture['home_team_id']),('road',fixture['away_team_id'])]:
            rows=raw['stats'][side]['players'];require(type(rows) is list and len(rows)<=30,'PREMATCH_PLAYER_LIST_REQUIRED');players=[]
            for row in rows:
                p=row['player'];player=p['person']['code']
                require(p['club']['code']==team and p['season']['code']==('E' if league=='EUROLEAGUE' else 'U')+str(season-1),'PREMATCH_PLAYER_TEAM_SEASON_MISMATCH')
                require(type(player) is str and re.fullmatch('[A-Za-z0-9_-]{1,64}',player) and player not in seen,'PREMATCH_PLAYER_ID_CONFLICT');seen.add(player)
                stats=row.get('stats')
                require(stats is None or type(stats) is dict,'PREMATCH_STATS_SCHEMA')
                if stats is not None:require(all(stats.get(k) is None or type(stats[k]) in (int,float) and stats[k]==0 for k in ('timePlayed','points')),'PREMATCH_HAS_PLAYED_STATISTICS')
                players.append('EUROLEAGUE_LIVE:'+player)
            if players:listings[team]=dict(team_id=team,players=sorted(players),roster_status='SOURCE_LISTED_UNCONFIRMED',starting_five=None,
                active_for_target=None,injuries=None,rotation=None)
        if listings:reason='UNCONFIRMED_SOURCE_LISTING_AVAILABLE'
    require(parsed is not None,'PREMATCH_IDENTITY_REQUIRED')
    actual=fixture_identity(league=league,season_end_year=season,start_utc=parsed['start_ts_utc'],home_team_id=parsed['home_team_id'],away_team_id=parsed['away_team_id'])
    require(actual==fixture,'PREMATCH_FIXTURE_MISMATCH')
    return dict(source_url=url,listings=listings,status=reason)


def capture_listings(raw,*,fixture,provider,pid,observed_at_utc,ingested_at_utc,usage='PROSPECTIVE_EVIDENCE',registry=REGISTRY,registry_pin=REGISTRY_PIN):
    now=int(time.time());require(now<fixture['start_utc'],'PREMATCH_CAPTURE_WINDOW_CLOSED')
    require(type(observed_at_utc) is int and type(ingested_at_utc) is int and 0<observed_at_utc<=ingested_at_utc<=now,'PREMATCH_SOURCE_CHRONOLOGY')
    raw=compact_endpoint(raw,provider);n=derive_listings(raw,fixture=fixture,provider=provider,pid=pid,observed_at_utc=observed_at_utc)
    result=[]
    for team,claims in n['listings'].items():
        result.append(seal_observation(fixture=fixture,provider=provider,provider_fixture_id=pid,source_url=n['source_url'],data_type='ROSTER',
            raw=dict(format='FAZ46_ENDPOINT_LISTING_V1',snapshot=raw,team_id=team),claims=claims,scope='NOT_APPLICABLE',
            observed_at_utc=observed_at_utc,ingested_at_utc=ingested_at_utc,usage=usage,registry=registry,registry_pin=registry_pin))
    require(int(time.time())<fixture['start_utc'],'PREMATCH_CAPTURE_WINDOW_CLOSED')
    return result,n['status']


def replay_listing(observation,**validation):
    p=validate_observation(observation,**validation);raw=p['raw']
    require(set(raw)=={'format','snapshot','team_id'} and raw['format']=='FAZ46_ENDPOINT_LISTING_V1' and p['data_type']=='ROSTER' and
        p['scope']=='NOT_APPLICABLE' and p['published_at_utc'] is None,'PREMATCH_LISTING_FORMAT_REQUIRED')
    n=derive_listings(raw['snapshot'],fixture=p['fixture'],provider=p['provider'],pid=p['provider_fixture_id'],observed_at_utc=p['observed_at_utc'])
    require(p['source_url']==n['source_url'] and n['listings'].get(raw['team_id'])==p['claims'],'PREMATCH_LISTING_CANNOT_REPLAY')
    return p


def audit_endpoint(schedule,canonical_id,response,*,registry=REGISTRY,registry_pin=REGISTRY_PIN):
    now=int(time.time());p=validate_schedule(schedule,cutoff_utc=now,require_permitted=False,registry=registry,registry_pin=registry_pin)
    matches=[r for r in p['fixtures'] if r['fixture']['canonical_id']==canonical_id];require(len(matches)==1,'PREMATCH_SCHEDULE_BINDING_REQUIRED')
    row=matches[0];fixture=row['fixture'];pid=row['provider_fixture_ids'][0];url=endpoint(p['provider'],p['league'],pid,p['season_end_year'])
    require(response['source_url']==url and response['provider']==p['provider'],'PREMATCH_RECEIPT_ORIGIN_MISMATCH')
    out=dict(fixture=fixture,provider=p['provider'],provider_fixture_id=pid,source_url=url,schedule_sha256=schedule['sha256'],
        receipt={k:v for k,v in response.items() if k!='payload'},audited_at_utc=now,observations=[],confirmed_lineups=0,prospective_records_created=0)
    if response['status']!='DOCUMENT_RECEIVED':out['status']='ABSTAIN_SOURCE_'+response['status'];return out
    out['response_json_sha256']=digest(response['payload'])
    try:
        require(response['http_status']==200,'PREMATCH_COMPLETED_RECEIPT_REQUIRED')
        require(now<fixture['start_utc'],'PREMATCH_CAPTURE_WINDOW_CLOSED')
        require(type(response['observed_at_utc']) is int and p['observed_at_utc']<=response['observed_at_utc']<=now,'PREMATCH_SOURCE_CHRONOLOGY')
        if p['provider']=='ESPN':raw=response['payload']
        else:
            games=[g for g in p['raw']['data'] if g['identifier']==pid];require(len(games)==1,'PREMATCH_GAME_SOURCE_BINDING')
            raw=dict(game=games[0],stats=response['payload'])
        out['raw_proof']=compact_endpoint(raw,p['provider']);out['compact_json_sha256']=digest(out['raw_proof'])
        observations,status=capture_listings(raw,fixture=fixture,provider=p['provider'],pid=pid,
            observed_at_utc=response['observed_at_utc'],ingested_at_utc=now,
            usage='SYNTHETIC_TEST' if p['usage']=='SYNTHETIC_TEST' else 'PROSPECTIVE_EVIDENCE',registry=registry,registry_pin=registry_pin)
        out.update(status=status,observations=observations)
    except (ValueError,KeyError,TypeError,AttributeError,IndexError) as ex:out['status']=str(ex) if type(ex) is ValueError else 'ABSTAIN_MALFORMED_PREMATCH_SOURCE'
    return out

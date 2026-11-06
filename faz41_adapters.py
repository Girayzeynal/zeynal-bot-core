"""Deterministic replay adapters. No network, inferred lineup or licence grants."""
from datetime import datetime
import math
import re

from faz40_archive import seal_game, require
from faz41_evidence import (fixture_identity, seal_observation, validate_observation,
                           REGISTRY, REGISTRY_PIN)
from nba_season_2027 import require_regular
from providers.nba_com_adapter import NBA_TEAMS

# Explicit provider namespaces; player IDs are deliberately NOT cross-mapped.
ESPN_ABBREVIATIONS=dict(zip(map(str,range(1,31)),
    'ATL BOS NOP CHI CLE DAL DEN DET GSW HOU IND LAC LAL MIA MIL MIN BKN NYK ORL PHI PHX POR SAC SAS OKC UTA WAS TOR MEM CHA'.split()))
NBA_TO_ESPN={str(NBA_TEAMS[abbr]):eid for eid,abbr in ESPN_ABBREVIATIONS.items()}


def _utc(value):
    require(type(value) is str, 'PRECISE_UTC_REQUIRED')
    date=datetime.fromisoformat(value.replace('Z','+00:00'))
    require(date.tzinfo is not None and date.utcoffset().total_seconds()==0, 'PRECISE_UTC_REQUIRED')
    return int(date.timestamp())


def _count(value):
    require(type(value) in (int,float) and math.isfinite(value) and 0<=value<=100000 and int(value)==value, 'INVALID_SOURCE_COUNT')
    return int(value)


def _nba(raw,season,observed):
    g=raw['game'];gid=g['gameId'];start=_utc(g['gameTimeUTC'])
    require(type(gid) is str and re.fullmatch(r'002\d{7}',gid) and
            int(gid[3:5])+2001==season, 'NBA_GAME_SEASON_MISMATCH')
    require(type(g['gameStatus']) is int and g['gameStatus']==3 and start<observed, 'NBA_FINAL_REQUIRED')
    if season==2027:require_regular({'season':{'year':season,'type':2}},start)
    teams={side:g[side+'Team'] for side in ('home','away')}
    ids={side:NBA_TO_ESPN[str(t['teamId'])] for side,t in teams.items()}
    require(ids['home']!=ids['away'], 'DISTINCT_TEAMS_REQUIRED')
    periods={}
    for side,t in teams.items():
        rows=t['periods'];require(type(rows) is list and 4<=len(rows)<=12, 'NBA_PERIODS_REQUIRED')
        require(all(type(r['period']) is int and r['period']==i+1 and r['periodType']==('REGULAR' if i<4 else 'OVERTIME')
                    for i,r in enumerate(rows)), 'NBA_PERIOD_SEQUENCE')
        periods[side]=[_count(r['score']) for r in rows]
        require(sum(periods[side])==_count(t['score']), 'NBA_SCORE_PERIOD_MISMATCH')
    h,a=periods['home'],periods['away']
    require(len(h)==len(a) and sum(h)!=sum(a) and
            all(sum(h[:i])==sum(a[:i]) for i in range(4,len(h))), 'NBA_OVERTIME_OR_FINAL_INVALID')
    f=fixture_identity(league='NBA',season_end_year=season,start_utc=start,
        home_team_id=ids['home'],away_team_id=ids['away'])
    return dict(f,fixture_id=gid,source_url=f'https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json',
        quarters_home=h[:4],quarters_away=a[:4],overtime_home=h[4:],overtime_away=a[4:],
        final_home=sum(h),final_away=sum(a),regulation_home=sum(h[:4]),regulation_away=sum(a[:4]))


def _game(raw,provider,league,season,observed):
    if provider=='NBA':
        require(league=='NBA','PROVIDER_LEAGUE_MISMATCH');return _nba(raw,season,observed)
    require((provider=='ESPN' and league=='NBA') or
            (provider=='EUROLEAGUE_LIVE' and league in ('EUROLEAGUE','EUROCUP')), 'PROVIDER_LEAGUE_MISMATCH')
    teams=list(ESPN_ABBREVIATIONS) if league=='NBA' else [raw[s]['club']['code'] for s in ('local','road')]
    return seal_game(raw,league=league,season_end_year=season,source_observed_utc=observed,
                     ingested_utc=observed,team_ids=teams)['payload']['facts']


def _espn_minutes(raw,facts):
    blocks=raw['boxscore']['players'];require(type(blocks) is list and len(blocks)==2,'PLAYER_TEAM_BLOCKS_REQUIRED')
    all_ids=set();teams={};duration=48+5*len(facts['overtime_home'])
    for block in blocks:
        team=block['team']['id'];require(team in (facts['home_team_id'],facts['away_team_id']) and team not in teams,
                                       'PLAYER_TEAM_MISMATCH')
        require(len(block['statistics'])==1,'AMBIGUOUS_PLAYER_STAT_BLOCK')
        stats=block['statistics'][0];labels=stats['labels'];rows=[]
        require(type(labels) is list and len(labels)==len(set(labels)) and {'MIN','PTS'}<=set(labels),'PLAYER_LABELS_REQUIRED')
        for a in stats['athletes']:
            pid=a['athlete']['id'];require(type(pid) is str and pid.isascii() and pid.isdigit() and pid not in all_ids,
                                          'DUPLICATE_OR_INVALID_PLAYER')
            all_ids.add(pid);require(type(a['didNotPlay']) is bool and type(a['starter']) is bool,'PLAYER_STATUS_REQUIRED')
            if a['didNotPlay']:
                require(not a['starter'],'DNP_CANNOT_START')
                rows.append(dict(player_id='ESPN:'+pid,did_not_play=True,minutes=None,minutes_precision=None,points=None,historical_starter=False));continue
            values=a['stats'];require(type(values) is list and len(values)==len(labels),'PLAYER_VALUES_REQUIRED')
            text=values[labels.index('MIN')];points=values[labels.index('PTS')]
            require(type(text) is str and re.fullmatch(r'\d{1,2}(:[0-5]\d)?',text) and
                    type(points) is str and points.isascii() and points.isdigit(),'PLAYER_MINUTES_OR_POINTS_INVALID')
            bits=text.split(':');minutes=int(bits[0])+(int(bits[1])/60 if len(bits)==2 else 0)
            require(0<=minutes<=duration,'PLAYER_MINUTES_EXCEED_DURATION')
            rows.append(dict(player_id='ESPN:'+pid,did_not_play=False,minutes=minutes,
                minutes_precision='SECOND_DISPLAY' if len(bits)==2 else 'WHOLE_MINUTE_DISPLAY',
                points=int(points),historical_starter=a['starter']))
        side='home' if team==facts['home_team_id'] else 'away';played=[r for r in rows if not r['did_not_play']]
        require(played and sum(r['points'] for r in played)==facts['final_'+side], 'PLAYER_POINTS_DO_NOT_RECONCILE')
        # Whole-minute displays have unknown rounding, not exact observed seconds.
        tolerance=sum(r['minutes_precision']=='WHOLE_MINUTE_DISPLAY' for r in played)
        require(abs(sum(r['minutes'] for r in played)-5*duration)<=tolerance, 'PLAYER_MINUTES_DO_NOT_RECONCILE')
        teams[team]=sorted(rows,key=lambda r:r['player_id'])
    return dict(teams=teams,role='HISTORICAL_BOXSCORE_NOT_FUTURE_ROSTER',
                rotation_stints=None,lineup_combinations=None,player_identity_crosswalk='NOT_AVAILABLE')


def _euro_minutes(raw,facts):
    stats=raw['stats'];seen=set();teams={};duration=40+5*len(facts['overtime_home'])
    for side,label in (('local','home'),('road','away')):
        team=facts[label+'_team_id'];rows=[]
        for p in stats[side]['players']:
            m=p['player'];pid=m['person']['code']
            require(m['club']['code']==team and m['season']['code']==('E' if facts['league']=='EUROLEAGUE' else 'U')+str(facts['season_end_year']-1),
                    'PLAYER_TEAM_OR_SEASON_MISMATCH')
            require(type(pid) is str and pid and pid==pid.strip() and pid not in seen,'DUPLICATE_OR_INVALID_PLAYER');seen.add(pid)
            seconds=_count(p['stats']['timePlayed']);points=_count(p['stats']['points'])
            require(seconds<=duration*60,'PLAYER_MINUTES_EXCEED_DURATION')
            rows.append(dict(player_id='EUROLEAGUE_LIVE:'+pid,minutes=seconds/60,minutes_precision='SOURCE_SECONDS',points=points))
        require(rows and sum(round(r['minutes']*60) for r in rows)==5*duration*60 and
                sum(r['points'] for r in rows)==facts['final_'+label], 'PLAYER_TOTALS_DO_NOT_RECONCILE')
        teams[team]=sorted(rows,key=lambda r:r['player_id'])
    return dict(teams=teams,role='HISTORICAL_BOXSCORE_NOT_FUTURE_ROSTER',rotation_stints=None,
                lineup_combinations=None,player_identity_crosswalk='NOT_AVAILABLE')


def normalize(raw, *, provider, league, season_end_year, observed_at_utc, data_type):
    try:
        require(data_type in ('OFFICIAL_STAT','PLAYER_MINUTES'), 'UNSUPPORTED_REPLAY_DATA_TYPE')
        game_raw=raw['game'] if provider=='EUROLEAGUE_LIVE' and data_type=='PLAYER_MINUTES' else raw
        f=_game(game_raw,provider,league,season_end_year,observed_at_utc)
        identity={k:f[k] for k in ('league','season_end_year','start_utc','home_team_id','away_team_id','canonical_id')}
        if data_type=='OFFICIAL_STAT':
            claims={k:f[k] for k in ('quarters_home','quarters_away','overtime_home','overtime_away',
                                     'regulation_home','regulation_away','final_home','final_away')}
            url=f['source_url']
        else:
            require(provider in ('ESPN','EUROLEAGUE_LIVE'),'PLAYER_MINUTES_ADAPTER_NOT_AVAILABLE')
            claims=_espn_minutes(raw,f) if provider=='ESPN' else _euro_minutes(raw,f)
            url=f['source_url']+('/stats' if provider=='EUROLEAGUE_LIVE' else '')
        return dict(fixture=identity,provider_fixture_id=f['fixture_id'],source_url=url,claims=claims,scope='FINAL_WITH_OT')
    except (KeyError,TypeError,AttributeError,IndexError,OverflowError) as ex:
        raise ValueError('MALFORMED_PROVIDER_PAYLOAD') from ex


def capture(raw, *, provider, league, season_end_year, observed_at_utc, ingested_at_utc,
            data_type='OFFICIAL_STAT',usage='RETROSPECTIVE_RESEARCH',registry=REGISTRY,registry_pin=REGISTRY_PIN):
    n=normalize(raw,provider=provider,league=league,season_end_year=season_end_year,
                observed_at_utc=observed_at_utc,data_type=data_type)
    return seal_observation(**n,provider=provider,data_type=data_type,raw=raw,
        observed_at_utc=observed_at_utc,ingested_at_utc=ingested_at_utc,usage=usage,registry=registry,registry_pin=registry_pin)


def replay(observation, **validation):
    p=validate_observation(observation,**validation)
    n=normalize(p['raw'],provider=p['provider'],league=p['fixture']['league'],season_end_year=p['fixture']['season_end_year'],
                observed_at_utc=p['observed_at_utc'],data_type=p['data_type'])
    require(all(p[k]==v for k,v in n.items()) and p['published_at_utc'] is None,'PROVIDER_CLAIMS_CANNOT_REPLAY')
    return p

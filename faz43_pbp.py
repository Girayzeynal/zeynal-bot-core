"""Source-replayed ESPN score timeline and explicit-role rotation arithmetic.

No text-inferred substitutions, permission grants, fitted garbage-time model or
claim that score reconciliation proves every non-scoring event was supplied.
"""
from collections import defaultdict
from copy import deepcopy
from datetime import datetime
from decimal import Decimal,InvalidOperation
import re

from prediction_inputs import digest
from faz40_archive import require
from faz41_evidence import seal_observation,validate_observation,REGISTRY,REGISTRY_PIN
from faz41_adapters import normalize,_count


def clock_ms(text,duration):
    require(type(text) is str and re.fullmatch(r'\d{1,2}(:[0-5]\d)?(\.\d{1,3})?',text),'INVALID_GAME_CLOCK')
    try:
        parts=text.split(':');seconds=Decimal(parts[-1])+(Decimal(parts[0])*60 if len(parts)==2 else 0)
        require(0<=seconds<=duration,'GAME_CLOCK_EXCEEDS_PERIOD')
        return int(seconds*1000)
    except InvalidOperation as ex:raise ValueError('INVALID_GAME_CLOCK') from ex


def _timeline(summary,observed):
    n=normalize(summary,provider='ESPN',league='NBA',season_end_year=summary['header']['season']['year'],
                observed_at_utc=observed,data_type='OFFICIAL_STAT')
    f=n['fixture'];facts=n['claims'];period_home=facts['quarters_home']+facts['overtime_home'];period_away=facts['quarters_away']+facts['overtime_away']
    lengths=[720]*4+[300]*(len(period_home)-4);raw=summary['plays'];require(type(raw) is list and raw,'PLAY_BY_PLAY_REQUIRED')
    events=[];seen={};previous_seq=-1;sequence_ids=set();sequence_reversals=0;previous_elapsed=-1;h=a=0;missing_wallclock=0;duplicates=0
    for p in raw:
        pid=p['id'];require(type(pid) is str and pid and pid==pid.strip(),'EVENT_ID_REQUIRED')
        if pid in seen:
            require(seen[pid]==p,'CONFLICTING_PLAY_ID');duplicates+=1;continue
        seen[pid]=deepcopy(p)
        seq=p['sequenceNumber'];require(type(seq) is str and seq.isascii() and seq.isdigit() and int(seq) not in sequence_ids,'PLAY_SEQUENCE_ID_NOT_UNIQUE')
        if int(seq)<previous_seq:sequence_reversals+=1
        sequence_ids.add(int(seq));previous_seq=int(seq);period=p['period']['number'];require(type(period) is int and 1<=period<=len(lengths),'PLAY_PERIOD_INVALID')
        remaining=clock_ms(p['clock']['displayValue'],lengths[period-1]);elapsed=sum(lengths[:period-1])*1000+lengths[period-1]*1000-remaining
        require(elapsed>=previous_elapsed,'PLAY_CLOCK_NOT_MONOTONIC');previous_elapsed=elapsed
        home=_count(p['homeScore']);away=_count(p['awayScore'])
        require(home>=h and away>=a and (home==h or away==a) and max(home-h,away-a)<=4,'SCORE_CORRECTION_OR_MISSING_SCORING_EVENT')
        team=p.get('team',{}).get('id');require(team is None or team in (f['home_team_id'],f['away_team_id']),'PLAY_TEAM_MISMATCH')
        stamp=p.get('wallclock')
        if stamp is None:missing_wallclock+=1
        else:
            date=datetime.fromisoformat(stamp.replace('Z','+00:00'))
            require(date.tzinfo is not None and f['start_utc']<=date.timestamp()<=observed,'PLAY_WALLCLOCK_NOT_AVAILABLE')
        kind=p['type']['id'];require(type(kind) is str and kind,'PLAY_TYPE_REQUIRED')
        # ESPN participants do not carry verified incoming/outgoing roles. Do
        # not infer these from participant order or free-form English text.
        events.append(dict(event_id=pid,sequence=int(seq),period=period,remaining_ms=remaining,elapsed_ms=elapsed,
            home_score=home,away_score=away,team_id=team,wallclock=stamp,
            substitution_roles='UNVERIFIED' if kind=='584' else 'NOT_APPLICABLE',
            garbage_rule_flag=period==4 and remaining<=180000 and abs(home-away)>=20))
        h,a=home,away
    for period,length in enumerate(lengths,1):
        rows=[e for e in events if e['period']==period];require(rows,'MISSING_PERIOD_EVENTS')
        prior_h=sum(period_home[:period-1]);prior_a=sum(period_away[:period-1]);last_h=sum(period_home[:period]);last_a=sum(period_away[:period])
        require(rows[0]['remaining_ms']==length*1000 and (rows[0]['home_score'],rows[0]['away_score'])==(prior_h,prior_a),'MISSING_PERIOD_OPENING')
        require(rows[-1]['remaining_ms']==0 and (rows[-1]['home_score'],rows[-1]['away_score'])==(last_h,last_a),'PERIOD_END_SCORE_MISMATCH')
    require((h,a)==(facts['final_home'],facts['final_away']),'PLAY_FINAL_SCORE_MISMATCH')
    half_h=sum(period_home[:2]);half_a=sum(period_away[:2]);rh=facts['regulation_home'];ra=facts['regulation_away']
    comeback=lambda eh,ea:'HOME' if half_h<half_a and eh>ea else 'AWAY' if half_a<half_h and ea>eh else None
    claims=dict(events=events,event_count=len(events),duplicate_identical_events=duplicates,
        source_sequence_reversals=sequence_reversals,event_order='PROVIDER_ARRAY_VALIDATED_BY_PERIOD_CLOCK_AND_SCORE_NOT_SEQUENCE_SORT',
        period_games=1,quarters_home=facts['quarters_home'],quarters_away=facts['quarters_away'],
        final_home=h,final_away=a,regulation_home=rh,regulation_away=ra,
        halftime_home=half_h,halftime_away=half_a,regulation_comeback=comeback(rh,ra),final_comeback=comeback(h,a),
        missing_wallclock_events=missing_wallclock,substitution_events=sum(e['substitution_roles']=='UNVERIFIED' for e in events),
        rotation_status='ABSTAIN_SUBSTITUTION_ROLES_UNVERIFIED',lineup_stints=None,
        garbage_rule='Q4_REMAINING_LE_180S_AND_ABS_MARGIN_GE_20_DESCRIPTIVE_NOT_TRAINED',
        garbage_rule_events=sum(e['garbage_rule_flag'] for e in events),
        event_completeness='PERIOD_BOUNDARIES_AND_FINAL_RECONCILED_NOT_INDEPENDENTLY_ATTESTED',parameters_fitted=False)
    return n,claims


def capture_espn_timeline(summary,*,observed_at_utc,ingested_at_utc,usage='RETROSPECTIVE_RESEARCH',registry=REGISTRY,registry_pin=REGISTRY_PIN):
    n,claims=_timeline(summary,observed_at_utc)
    return seal_observation(fixture=n['fixture'],provider='ESPN',provider_fixture_id=n['provider_fixture_id'],source_url=n['source_url'],
        data_type='OFFICIAL_STAT',scope='FINAL_WITH_OT',raw=dict(format='FAZ43_ESPN_TIMELINE_V1',summary=summary),claims=claims,
        observed_at_utc=observed_at_utc,ingested_at_utc=ingested_at_utc,usage=usage,registry=registry,registry_pin=registry_pin)


def replay_timeline(sealed,**validation):
    p=validate_observation(sealed,**validation)
    require(set(p['raw'])=={'format','summary'} and p['raw']['format']=='FAZ43_ESPN_TIMELINE_V1' and
            p['provider']=='ESPN' and p['data_type']=='OFFICIAL_STAT' and p['scope']=='FINAL_WITH_OT','TIMELINE_FORMAT_REQUIRED')
    n,claims=_timeline(p['raw']['summary'],p['observed_at_utc'])
    require(p['published_at_utc'] is None and all(p[k]==n[k] for k in ('fixture','provider_fixture_id','source_url')) and p['claims']==claims,'TIMELINE_CANNOT_REPLAY')
    return deepcopy(p)


def explicit_rotation(events,*,starters,rosters,total_ms):
    """Pure synthetic/normalized explicit-role arithmetic, not a live adapter.

    Inputs must already carry source-proved player_in/player_out roles. Returns
    durations only; no causal lineup strength or invented possession effects.
    """
    require(type(total_ms) is int and total_ms>0 and type(events) is list and set(starters)==set(rosters) and len(starters)==2,'ROTATION_INPUT_SCHEMA')
    current={};all_ids=set();groups=defaultdict(list);previous=-1
    for team,players in rosters.items():
        require(type(players) is list and len(players)==len(set(players)) and all(type(p) is str and p and p==p.strip() for p in players),'ROTATION_PLAYER_IDS_REQUIRED')
        require(not all_ids.intersection(players),'PLAYER_BELONGS_TO_TWO_TEAMS');all_ids.update(players)
        five=starters[team];require(type(five) is list and len(set(five))==len(five)==5 and set(five)<=set(players),'FIVE_CONFIRMED_STARTERS_REQUIRED')
        current[team]=set(five)
    for event in events:
        at=event['elapsed_ms'];require(type(at) is int and 0<=at and previous<=at<=total_ms,'ROTATION_EVENT_TIME_INVALID');previous=at
        require(set(event)=={'elapsed_ms','team_id','player_in','player_out'} and event['team_id'] in rosters,'EXPLICIT_SUBSTITUTION_ROLES_REQUIRED')
        require(event['player_in']!=event['player_out'] and event['player_in'] in rosters[event['team_id']] and event['player_out'] in rosters[event['team_id']], 'SUBSTITUTION_TEAM_MEMBERSHIP')
        groups[at].append(event)
    last=0;stints=[];minutes=defaultdict(int)
    for at,changes in sorted(groups.items()):
        if at>last:
            for team,players in current.items():
                stints.append(dict(team_id=team,start_ms=last,end_ms=at,players=sorted(players)))
                for pid in players:minutes[pid]+=at-last
        for team in current:
            changes_team=[e for e in changes if e['team_id']==team]
            outs=[e['player_out'] for e in changes_team];ins=[e['player_in'] for e in changes_team]
            require(len(outs)==len(set(outs)) and len(ins)==len(set(ins)) and set(outs)<=current[team] and
                    not set(ins).intersection(current[team]-set(outs)),'CONFLICTING_SUBSTITUTION_BATCH')
            current[team]=(current[team]-set(outs))|set(ins);require(len(current[team])==5,'ROTATION_NOT_FIVE_PLAYERS')
        last=at
    if last<total_ms:
        for team,players in current.items():
            stints.append(dict(team_id=team,start_ms=last,end_ms=total_ms,players=sorted(players)))
            for pid in players:minutes[pid]+=total_ms-last
    for team in rosters:require(sum(minutes[p] for p in rosters[team])==5*total_ms,'PLAYER_DURATION_CONSERVATION')
    return dict(status='EXPLICIT_ROLE_ARITHMETIC_ONLY',stints=stints,player_ms=dict(minutes),
                causal_lineup_effect=None,possessions=None,production_coefficients_changed=False)

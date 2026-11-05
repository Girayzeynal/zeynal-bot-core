"""Normalize ESPN team-schedule finals without inventing missing score or season facts."""
from copy import deepcopy
from datetime import datetime,timezone
import math
from providers.espn_completed_event import parse_completed_nba_event
from nba_season_2027 import require_regular


def completed_history(payload,observed_utc,team_id):
    scope=payload.get('season',{})
    if scope.get('year')!=2027 or scope.get('type')!=2:raise ValueError('HISTORY_SEASON_SCOPE_UNVERIFIED')
    if not isinstance(payload.get('events'),list):raise ValueError('MALFORMED_TEAM_HISTORY')
    by_id={}
    for source in payload['events']:
        event=deepcopy(source)
        try:
            status=event['competitions'][0]['status']['type']
            if status.get('completed') is not True or status.get('state') not in ('post','completed'):continue
            if event.get('season',{}).get('year')!=scope['year']:raise ValueError('history event season differs from response scope')
            # ESPN team schedules expose type on the response and year on events.
            if 'type' not in event['season']:event['season']['type']=scope['type']
            for competitor in event['competitions'][0]['competitors']:
                score=competitor.get('score')
                if isinstance(score,dict):
                    value=score.get('value');display=score.get('displayValue')
                    if (type(value) not in (int,float) or not math.isfinite(value) or value<0 or not float(value).is_integer()
                        or not isinstance(display,str) or not display.isascii() or not display.isdigit() or int(display)!=value):
                        raise ValueError('inconsistent score object value/displayValue')
                    competitor['score']=display
            parsed=parse_completed_nba_event(event,datetime.fromtimestamp(observed_utc,timezone.utc))
            if parsed is None:raise ValueError('completed team schedule event cannot be verified')
            require_regular(event,parsed['start_ts_utc'])
            if team_id not in (parsed['home_team_id'],parsed['away_team_id']):raise ValueError('wrong team schedule response')
            key=parsed['provider_fixture_id']
            if key in by_id and by_id[key]!=parsed:raise ValueError('conflicting duplicate history fixture')
            by_id[key]=parsed
        except (KeyError,TypeError,IndexError) as exc:raise ValueError('MALFORMED_HISTORY_FINAL') from exc
    return sorted(by_id.values(),key=lambda e:(e['start_ts_utc'],e['provider_fixture_id']))

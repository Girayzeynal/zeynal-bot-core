"""Pinned NBA.com regular-season calendar; ESPN broad season dates are not bounds."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import json
from pathlib import Path
from prediction_inputs import digest

ZONE=ZoneInfo('America/New_York')
START=int(datetime(2026,10,20,tzinfo=ZONE).timestamp())
END=int(datetime(2027,4,12,tzinfo=ZONE).timestamp())  # exclusive; includes Apr11 US night
EVIDENCE=Path(__file__).parent/'docs/evidence/faz33-official-season-20261105.json'


def policy():
    record=json.loads(EVIDENCE.read_text());p=record['payload']
    if digest(p)!=record['sha256'] or p['season_year']!=2027 or p['regular_start_local']!='2026-10-20' or p['regular_end_local_inclusive']!='2027-04-11':
        raise ValueError('invalid pinned official season evidence')
    return record


def require_regular(event,start):
    if event.get('season',{}).get('year')!=2027 or event['season'].get('type')!=2:
        raise ValueError('OUTSIDE_2026_27_REGULAR_SEASON')
    if not START<=start<END:raise ValueError('OUTSIDE_OFFICIAL_REGULAR_SEASON_DATES')


def parse_scheduled(event,team_ids):
    from providers.espn_scheduled_fixture import parse_scheduled_nba_fixture
    fixture=parse_scheduled_nba_fixture(event)
    if fixture is None:raise ValueError('INVALID_OR_UNSCHEDULED_EVENT')
    c=event['competitions'][0]
    if any(row.get('dateValid') is False or row.get('timeValid') is False or row.get('tbd') is True for row in (event,c)):
        raise ValueError('UNVERIFIED_START_TIME')
    for status in (event.get('status'),c.get('status')):
        t=(status or {}).get('type',{})
        if (t.get('name')!='STATUS_SCHEDULED' or t.get('state')!='pre' or t.get('completed') is not False):
            raise ValueError('STARTED_POSTPONED_OR_UNVERIFIABLE_STATUS')
    if c.get('id')!=fixture['provider_fixture_id'] or c.get('date',event['date'])!=event['date']:
        raise ValueError('CONFLICTING_SCHEDULE_ID_OR_TIME')
    if not fixture['provider_fixture_id'].isascii() or not fixture['provider_fixture_id'].isdigit():raise ValueError('INVALID_ESPN_ID')
    if any(fixture[side+'_team_id'] not in team_ids for side in ('home','away')):raise ValueError('UNKNOWN_NBA_TEAM_ID')
    require_regular(event,fixture['start_ts_utc'])
    return fixture

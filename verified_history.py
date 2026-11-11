"""League-native completed history for a current prematch score projection."""
from copy import deepcopy
import time

from core.team_identity import digest
from season_archive_inventory import archive_catalog
from universal_analysis import require_fresh_source
from providers.season_participants import ParticipantSourceError


def checked_fetch(fetcher,provider,url):
    r=fetcher(provider,url)
    if r.get('status')!='DOCUMENT_RECEIVED':raise ParticipantSourceError(r.get('status','SOURCE_RECEIPT_INVALID'))
    if r.get('provider')!=provider or r.get('source_url')!=url or r.get('http_status')!=200 or digest(r['document'])!=r.get('document_sha256'):
        raise ParticipantSourceError('HISTORY_SOURCE_BINDING_MISMATCH')
    require_fresh_source(r)
    return r


def nba_history(fetcher,team_id,year,cutoff,*,result_sink=None):
    url=f'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team_id}/schedule?season={year+1}&seasontype=2'
    schedule=checked_fetch(fetcher,'ESPN',url);d=schedule['document']
    if d['team']['id']!=team_id or d['season']['year']!=year+1 or d['season']['type']!=2:
        raise ParticipantSourceError('NBA_HISTORY_TEAM_OR_SEASON_CONFLICT')
    candidates=[]
    from datetime import datetime
    for e in d['events']:
        if e['season']['year']!=year+1 or e['seasonType']['type']!=2:raise ParticipantSourceError('NBA_HISTORY_SEASON_CONFLICT')
        c=e['competitions'][0];status=c['status']['type']
        if status.get('completed') is not True:continue
        start=datetime.fromisoformat(e['date'].replace('Z','+00:00'))
        if start.tzinfo is None:raise ParticipantSourceError('NBA_HISTORY_UTC_REQUIRED')
        if start.timestamp()<cutoff:candidates.append(e)
    rows=[];pins=[{k:v for k,v in schedule.items() if k!='document'}]
    seen={}
    for e in sorted(candidates,key=lambda e:e['date'],reverse=True):
        if len(rows)>=10:break
        pid=e['id']
        if type(pid) is not str or not pid.isascii() or not pid.isdigit():raise ParticipantSourceError('NBA_HISTORY_ID_INVALID')
        u='https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event='+pid
        r=checked_fetch(fetcher,'ESPN',u);h=deepcopy(r['document']['header']);c=h['competitions'][0]
        if h['id']!=pid or c['id']!=pid or c['date']!=e['date']:
            raise ParticipantSourceError('NBA_HISTORY_SUMMARY_FIXTURE_CONFLICT')
        # Native summary linescores may contain displayValue without value.
        # Bind every derived integer to the original pinned receipt.
        for t in c['competitors']:
            for part in t.get('linescores',[]):
                text=part.get('displayValue')
                if 'value' not in part:
                    if type(text) is not str or not text.isascii() or not text.isdigit():
                        raise ParticipantSourceError('NBA_HISTORY_PERIOD_INVALID')
                    part['value']=int(text)
        h['date']=c['date']
        b=archive_catalog({'events':[h]},provider='ESPN',season_start_year=year,
            observed_at_utc=r['observed_at_utc'],ingested_at_utc=r['ingested_at_utc'])
        g=b['payload']['fixtures'][0]
        if not g['completed'] or g['periods'] is None:raise ParticipantSourceError('NBA_HISTORY_PERIODS_OR_FINAL_MISSING')
        if team_id not in (g['home_team_id'],g['away_team_id']):raise ParticipantSourceError('NBA_HISTORY_TEAM_CONFLICT')
        # Summary and schedule must agree on teams and final scores.
        for side in ('home','away'):
            st=[t for t in e['competitions'][0]['competitors'] if t['homeAway']==side]
            if len(st)!=1 or st[0]['team']['id']!=g[side+'_team_id']:
                raise ParticipantSourceError('NBA_HISTORY_SUMMARY_TEAM_CONFLICT')
            score=st[0]['score'];value=score.get('value',score.get('displayValue')) if type(score) is dict else score
            if float(value)!=g['final_scores'][0 if side=='home' else 1]:raise ParticipantSourceError('NBA_HISTORY_SUMMARY_SCORE_CONFLICT')
        slot=(team_id,g['start_ts_utc'])
        identity={k:v for k,v in g.items() if k not in ('canonical_id','provider_fixture_ids')}
        if slot in seen:
            if seen[slot]!=identity:raise ParticipantSourceError('NBA_HISTORY_TEAM_START_CONFLICT')
            continue
        seen[slot]=identity;rows.append(g);pins.append({k:v for k,v in r.items() if k!='document'})
        if result_sink is not None:result_sink(b)
    return rows,pins

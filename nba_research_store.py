"""Separate immutable historical observations; source time is never ingest time."""
from copy import deepcopy
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import sqlite3
import time

from prediction_inputs import digest,canonical_json
from prospective_error_audit import period_final
from providers.espn_boxscore_pace import estimate_pace_from_summary


def compact_summary(raw):
    h=raw['header'];c=h['competitions'][0]
    header={k:deepcopy(h[k]) for k in ('id','season','status') if k in h}
    comp={k:deepcopy(c[k]) for k in ('id','date','status') if k in c}
    comp['competitors']=[dict(homeAway=t['homeAway'],score=t['score'],team={'id':t['team']['id']},linescores=deepcopy(t['linescores'])) for t in c['competitors']]
    header['competitions']=[comp];out={'header':header}
    if 'format' in raw:out['format']=deepcopy(raw['format'])
    if isinstance(raw.get('boxscore'),dict) and isinstance(raw['boxscore'].get('teams'),list):
        out['boxscore']={'teams':[dict(homeAway=t['homeAway'],team={'id':t['team']['id']},statistics=deepcopy(t['statistics'])) for t in raw['boxscore']['teams']]}
    return out


def validate_summary(raw,observed,team_ids):
    parsed=period_final(raw,observed);event=parsed['event']
    fixture=event['provider_fixture_id']
    if not fixture.isascii() or not fixture.isdigit():raise ValueError('numeric ESPN fixture ID required')
    if any(event[side+'_team_id'] not in team_ids for side in ('home','away')):raise ValueError('unknown source NBA team ID')
    season=raw['header']['season'];start=datetime.fromtimestamp(event['start_ts_utc'],timezone.utc)
    expected_end_year=start.year+int(start.month>=7)
    if type(season.get('year')) is not int or season['year']!=expected_end_year or season.get('type')!=2:
        raise ValueError('explicit regular-season/year mapping mismatch')
    return parsed


class ResearchStore:
    def __init__(self,path,team_ids):
        self.path=str(path);self.team_ids=set(team_ids)
        if not self.team_ids or any(not isinstance(t,str) or not t.isascii() or not t.isdigit() for t in self.team_ids):raise ValueError('verified NBA directory IDs required')
        with sqlite3.connect(self.path) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS observations (
                observation_id TEXT PRIMARY KEY,fixture_id TEXT NOT NULL,start_utc INTEGER NOT NULL,
                source_observed_utc INTEGER NOT NULL,ingested_utc INTEGER NOT NULL,
                origin TEXT NOT NULL,payload TEXT NOT NULL,sha256 TEXT NOT NULL)''')
            db.execute('CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            old=db.execute("SELECT value FROM metadata WHERE key='team_ids'").fetchone()
            encoded=canonical_json(sorted(self.team_ids))
            if old and old[0]!=encoded:raise ValueError('directory identity set changed; explicit migration required')
            db.execute("INSERT OR IGNORE INTO metadata VALUES ('team_ids',?)",(encoded,))
            for op in ('UPDATE','DELETE'):
                db.execute(f"CREATE TRIGGER IF NOT EXISTS research_no_{op} BEFORE {op} ON observations BEGIN SELECT RAISE(ABORT,'immutable research observation'); END")
        os.chmod(self.path,0o600)

    def ingest(self,raw,source_observed_utc,origin,archive_ref=None):
        now=int(time.time())
        if type(source_observed_utc) is not int or not 0<source_observed_utc<=now:raise ValueError('invalid source observation time')
        if origin=='NEW_DOWNLOAD':
            if not isinstance(archive_ref,dict) or type(archive_ref.get('collection_started_utc')) is not int or not 0<archive_ref['collection_started_utc']<=source_observed_utc or not archive_ref.get('file_sha256'):
                raise ValueError('actual fetch manifest and collection-start clock required')
        elif origin=='ARCHIVED_SOURCE':
            if not isinstance(archive_ref,dict) or not archive_ref.get('file_sha256') or not archive_ref.get('path'):
                raise ValueError('auditable archive reference required')
        else:raise ValueError('unknown observation origin')
        summary=compact_summary(raw);p=validate_summary(summary,source_observed_utc,self.team_ids);e=p['event']
        facts=dict(event=e,periods=p['periods'])
        payload=dict(schema_version=1,summary=summary,source_url='https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event='+e['provider_fixture_id'],
            source_observed_utc=source_observed_utc,ingested_utc=now,origin=origin,archive_ref=archive_ref,
            facts=facts,usage='HISTORICAL_OBSERVATION_NOT_PROSPECTIVE_FORECAST')
        oid=digest(dict(summary=summary,source_observed_utc=source_observed_utc));sha=digest(payload)
        with sqlite3.connect(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            prior=db.execute('SELECT payload,sha256 FROM observations WHERE fixture_id=?',(e['provider_fixture_id'],)).fetchall()
            for value,stored_sha in prior:
                old=json.loads(value)
                if digest(old)!=stored_sha:raise ValueError('stored research observation corruption')
                if old['facts']!=facts:raise ValueError('conflicting source game facts')
                if old['source_observed_utc']==source_observed_utc and old['summary']!=summary:
                    raise ValueError('conflicting same-clock source observation')
            for (value,) in db.execute('SELECT payload FROM observations WHERE start_utc=? AND fixture_id!=?',(e['start_ts_utc'],e['provider_fixture_id'])):
                other=json.loads(value)['facts']['event']
                if set((e['home_team_id'],e['away_team_id'])).intersection((other['home_team_id'],other['away_team_id'])):
                    raise ValueError('same-team start/provider-ID alias conflict')
            existing=db.execute('SELECT observation_id FROM observations WHERE observation_id=?',(oid,)).fetchone()
            if existing:return False
            db.execute('INSERT INTO observations VALUES (?,?,?,?,?,?,?,?)',
                (oid,e['provider_fixture_id'],e['start_ts_utc'],source_observed_utc,now,origin,canonical_json(payload),sha))
        return True

    def observations(self):
        with sqlite3.connect(Path(self.path).resolve().as_uri()+'?mode=ro',uri=True) as db:
            rows=db.execute('SELECT observation_id,payload,sha256,fixture_id,start_utc,source_observed_utc,ingested_utc,origin FROM observations').fetchall()
        result=[]
        for oid,raw,sha,fixture,start,observed,ingested,origin in rows:
            p=json.loads(raw)
            if digest(p)!=sha:raise ValueError('research payload digest mismatch')
            parsed=validate_summary(p['summary'],p['source_observed_utc'],self.team_ids)
            if (oid!=digest(dict(summary=p['summary'],source_observed_utc=p['source_observed_utc']))
                or (fixture,start,observed,ingested,origin)!=(parsed['event']['provider_fixture_id'],parsed['event']['start_ts_utc'],p['source_observed_utc'],p['ingested_utc'],p['origin'])):
                raise ValueError('research index/payload mismatch')
            if p['facts']!=dict(event=parsed['event'],periods=parsed['periods']):raise ValueError('research semantic mismatch')
            if not p['source_observed_utc']<=p['ingested_utc']<=int(time.time()):raise ValueError('research time mismatch')
            result.append(dict(observation_id=oid,payload=p,sha256=sha))
        return result

    def select(self,cutoff,mode='PROSPECTIVE',season_year=None):
        if type(cutoff) is not int or cutoff<=0 or mode not in ('PROSPECTIVE','RESEARCH_SOURCE_CLOCK'):raise ValueError('invalid research selection')
        by_game={}
        for r in self.observations():
            p=r['payload']
            available=p['source_observed_utc'] if mode=='RESEARCH_SOURCE_CLOCK' else max(p['source_observed_utc'],p['ingested_utc'])
            if available>=cutoff:continue
            if season_year is not None and p['summary']['header']['season']['year']!=season_year:continue
            key=p['facts']['event']['provider_fixture_id']
            if key not in by_game or (p['source_observed_utc'],r['observation_id'])>(by_game[key]['payload']['source_observed_utc'],by_game[key]['observation_id']):by_game[key]=r
        return sorted(by_game.values(),key=lambda r:(r['payload']['facts']['event']['start_ts_utc'],r['observation_id']))

    def coverage(self):
        observations=self.observations();by_game={}
        for r in observations:by_game.setdefault(r['payload']['facts']['event']['provider_fixture_id'],[]).append(r)
        return dict(observations=len(observations),distinct_games=len(by_game),
            seasons=sorted({r['payload']['summary']['header']['season']['year'] for r in observations}),
            source_after_own_tipoff_games=sum(min(r['payload']['source_observed_utc'] for r in values)>values[0]['payload']['facts']['event']['start_ts_utc'] for values in by_game.values()),
            earliest_source_observed_utc=min((r['payload']['source_observed_utc'] for r in observations),default=None),
            latest_ingested_utc=max((r['payload']['ingested_utc'] for r in observations),default=None),
            pace_supported_observations=sum(estimate_pace_from_summary(r['payload']['summary'],r['payload']['facts']['event']) is not None for r in observations),
            original_prospective_forecasts_created=0)

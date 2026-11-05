"""Immutable multi-horizon NBA packets; distinct games and cuts are separate units."""
from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from prediction_inputs import canonical_json,digest,validate_prediction_inputs
from faz24 import validate_stage_bundle
from shadow_features import replay_features
from nba_season_2027 import parse_scheduled,policy,require_regular
from prospective_error_audit import period_final

HORIZONS={'T24H':86400,'T6H':21600,'T60M':3600}
GRACE=300


def due(fixture,horizon,now):
    planned=fixture['start_ts_utc']-HORIZONS[horizon]
    return 'NOT_DUE' if now<planned else 'MISSED_CUT' if now>planned+GRACE else 'DUE'


def validate_packet(p,recorded,mode):
    if p.get('schema_version')!=1 or p.get('usage')!=mode:raise ValueError('packet schema/mode mismatch')
    target=p['fixture'];cutoff=p['cutoff_utc'];start=target['start_ts_utc'];ref=p['reference'];b=ref['bundle'];inputs=ref['inputs']
    if not re.fullmatch('[0-9a-f]{40}',p['model_sha']) or b['model_version']!=p['model_sha']:raise ValueError('model SHA mismatch')
    if p['season_policy_sha256']!=policy()['sha256']:raise ValueError('season policy mismatch')
    if mode=='PROSPECTIVE' and policy()['payload']['ingested_utc']>cutoff:raise ValueError('season policy not yet observed')
    if not 0<cutoff<=b['generated_at']<=p['created_utc']<=recorded<int(start) or recorded>int(time.time()):raise ValueError('cut chronology mismatch')
    if p['scheduled_cutoff_utc']!=start-HORIZONS[p['horizon']] or due(target,p['horizon'],cutoff)!='DUE' or due(target,p['horizon'],recorded)!='DUE':raise ValueError('cut missed; no backdating')
    if p['reference_input_cutoff_utc']!=cutoff or p['reference_window_games']!=6:raise ValueError('reference source cutoff/window mismatch')
    teams=set(p['team_ids'])
    directory=p['directory']
    if (directory is None or set(directory['teams'])!=teams or digest(directory['teams'])!=directory['sha256']
        or not 0<directory['source_observed_utc']<=directory['ingested_utc']<cutoff):raise ValueError('directory unavailable at shared cutoff')
    if any(directory['teams'][target[side+'_team_id']]['abbr']!=p['team_keys'][side] for side in ('home','away')):raise ValueError('directory/target reference keys differ')
    for schedule in (p['schedule'],p['precommit_schedule']):
        observed,ingested=schedule['source_observed_utc'],schedule['ingested_utc']
        if not 0<observed<=ingested<=recorded or recorded-observed>GRACE:raise ValueError('stale schedule evidence')
        if schedule['sha256']!=digest(schedule['event']) or parse_scheduled(schedule['event'],teams)!=target:raise ValueError('schedule identity/status changed')
    f=replay_features(p['features'])
    if f['target']!=target or f['cutoff_utc']!=cutoff:raise ValueError('feature cutoff/identity mismatch')
    source_map={r['observation_id']:r for r in p['sources']}
    if len(source_map)!=len(p['sources']):raise ValueError('duplicate observation binding')
    if len(source_map)!=len(f['source_records']):raise ValueError('unused or missing frozen sources')
    period_by_game={}
    ids=set()
    for record in f['source_records']:
        r=record['payload'];source=source_map[r['input_ref']['observation_id']]
        if (source['payload_sha256']!=r['source_evidence_sha256'] or source['summary_sha256']!=digest(r['original_summary'])
            or source['source_observed_utc']!=r['source_observed_utc'] or not 0<source['source_observed_utc']<=source['ingested_utc']<cutoff):raise ValueError('source/ingestion cutoff leak')
        raw=r['original_summary'];event=period_final(raw,r['source_observed_utc'])['event'];require_regular(raw['header'],event['start_ts_utc'])
        if source['observation_id']!=digest(dict(summary=raw,source_observed_utc=r['source_observed_utc'])):raise ValueError('source observation ID mismatch')
        fixture=event['provider_fixture_id']
        if fixture in ids or fixture==target['provider_fixture_id']:raise ValueError('duplicate/self-target feature game')
        ids.add(fixture)
        period_by_game[fixture]=r
    validate_prediction_inputs(inputs,league='NBA',prediction_utc=b['generated_at'],expected_home=inputs['payload']['expected_home'],expected_away=inputs['payload']['expected_away'])
    for side,item in inputs['payload']['teams'].items():
        if item['key']!=p['team_keys'][side]:raise ValueError('reference team key mismatch')
        if len(item['records'])!=6:raise ValueError('reference input window changed')
        for row in item['records']:
            if row['game_id'] not in ids:raise ValueError('reference input not in frozen source cut')
            evidence=row.get('pace_evidence');event=evidence['snapshot']['game'] if evidence else {}
            # Side here refers to the historical game, independent of target venue.
            historic_side='home' if row['home'] else 'away'
            if event.get(historic_side+'_team_id')!=target[side+'_team_id']:raise ValueError('reference source team ID mismatch')
            from providers.espn_pace_evidence import capture_pace_evidence
            original=period_by_game[row['game_id']]
            original_event=period_final(original['original_summary'],original['source_observed_utc'])['event']
            expected=capture_pace_evidence(original['original_summary'],original_event,observed_at_utc=original['source_observed_utc'])
            if evidence!=expected:raise ValueError('reference and shadow sources differ')
    validate_stage_bundle(b,fixture_id=target['provider_fixture_id'],tipoff=start,prediction_utc=b['generated_at'],input_snapshot=inputs,asof_utc=recorded)
    shadow=p['shadow'];artifact=shadow['artifact'];prediction=shadow['prediction']
    if artifact is None:
        if shadow['status']!='NO_MODEL_AVAILABLE' or prediction is not None:raise ValueError('missing model must abstain explicitly')
    elif prediction is not None:
        from shadow_ridge import predict
        if shadow['status']!='PREDICTED_EXPERIMENTAL' or predict(artifact,p['features'])!=prediction:raise ValueError('shadow prediction replay mismatch')
    elif shadow['status'] not in ('FEATURES_UNAVAILABLE','MODEL_UNAVAILABLE_AT_CUTOFF'):raise ValueError('invalid shadow abstention')
    return p


class CutLedger:
    def __init__(self,path,mode='PROSPECTIVE'):
        if mode not in ('PROSPECTIVE','SYNTHETIC_TEST'):raise ValueError('invalid ledger mode')
        self.path=str(path);self.mode=mode
        with sqlite3.connect(self.path,timeout=1) as db:
            db.execute('CREATE TABLE IF NOT EXISTS faz33_meta (mode TEXT NOT NULL)')
            old=db.execute('SELECT mode FROM faz33_meta').fetchall()
            if old and old!=[(mode,)]:raise ValueError('ledger mode cannot change')
            if not old:db.execute('INSERT INTO faz33_meta VALUES (?)',(mode,))
            db.execute('''CREATE TABLE IF NOT EXISTS faz33_fixtures (fixture_id TEXT PRIMARY KEY,home_id TEXT,away_id TEXT,start_utc INTEGER)''')
            db.execute('''CREATE TABLE IF NOT EXISTS faz33_cuts (fixture_id TEXT,horizon TEXT,cutoff_utc INTEGER,recorded_utc INTEGER,payload TEXT,sha256 TEXT,PRIMARY KEY(fixture_id,horizon))''')
            db.execute('''CREATE TABLE IF NOT EXISTS faz33_evaluations (fixture_id TEXT PRIMARY KEY,recorded_utc INTEGER,payload TEXT,sha256 TEXT)''')
            db.execute('''CREATE TABLE IF NOT EXISTS faz33_attempts (id INTEGER PRIMARY KEY,status TEXT,fixture_id TEXT,horizon TEXT,observed_utc INTEGER,details TEXT)''')
            for table in ('faz33_meta','faz33_fixtures','faz33_cuts','faz33_evaluations'):
                for op in ('UPDATE','DELETE'):
                    db.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_{op} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'immutable FAZ33'); END")
            for table,condition in (
                ('faz33_meta','EXISTS (SELECT 1 FROM faz33_meta)'),
                ('faz33_fixtures','EXISTS (SELECT 1 FROM faz33_fixtures WHERE fixture_id=NEW.fixture_id)'),
                ('faz33_cuts','EXISTS (SELECT 1 FROM faz33_cuts WHERE fixture_id=NEW.fixture_id AND horizon=NEW.horizon)'),
                ('faz33_evaluations','EXISTS (SELECT 1 FROM faz33_evaluations WHERE fixture_id=NEW.fixture_id)')):
                db.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_replace BEFORE INSERT ON {table} WHEN {condition} BEGIN SELECT RAISE(ABORT,'immutable FAZ33 replacement'); END")
        os.chmod(self.path,0o600)

    def connect(self):return sqlite3.connect(self.path,timeout=1)

    def has(self,fixture,horizon):
        with self.connect() as db:return db.execute('SELECT 1 FROM faz33_cuts WHERE fixture_id=? AND horizon=?',(fixture,horizon)).fetchone() is not None

    def log(self,status,fixture=None,horizon=None,details=None):
        with self.connect() as db:db.execute('INSERT INTO faz33_attempts(status,fixture_id,horizon,observed_utc,details) VALUES (?,?,?,?,?)',(status,fixture,horizon,int(time.time()),canonical_json(details or {})))

    def insert(self,p):
        now=int(time.time());validate_packet(p,now,self.mode);e=p['fixture'];fixture=e['provider_fixture_id'];sha=digest(p)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            prior=db.execute('SELECT payload,sha256 FROM faz33_cuts WHERE fixture_id=? AND horizon=?',(fixture,p['horizon'])).fetchone()
            if prior:
                if prior!=(canonical_json(p),sha):raise ValueError('immutable cut differs')
                return False
            identity=(e['home_team_id'],e['away_team_id'],e['start_ts_utc'])
            existing=db.execute('SELECT home_id,away_id,start_utc FROM faz33_fixtures WHERE fixture_id=?',(fixture,)).fetchone()
            if existing and existing!=identity:raise ValueError('RESCHEDULED_OR_CHANGED_IDENTITY')
            for other,home,away,start in db.execute('SELECT * FROM faz33_fixtures WHERE start_utc=?',(e['start_ts_utc'],)):
                if other!=fixture and set(identity[:2]).intersection((home,away)):raise ValueError('SAME_TEAM_START_ALIAS')
            if existing is None:db.execute('INSERT INTO faz33_fixtures VALUES (?,?,?,?)',(fixture,*identity))
            recorded=int(time.time())
            if recorded>=e['start_ts_utc'] or due(e,p['horizon'],recorded)!='DUE':raise ValueError('cut expired during validation')
            if any(recorded-p[k]['source_observed_utc']>GRACE for k in ('schedule','precommit_schedule')):raise ValueError('schedule expired during validation')
            db.execute('INSERT INTO faz33_cuts VALUES (?,?,?,?,?,?)',(fixture,p['horizon'],p['cutoff_utc'],recorded,canonical_json(p),sha))
        return True

    def record_final(self,raw,source_observed_utc):
        parsed=period_final(raw,source_observed_utc);e=parsed['event'];require_regular(raw['header'],e['start_ts_utc'])
        now=int(time.time());fixture=e['provider_fixture_id']
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            identity=db.execute('SELECT home_id,away_id,start_utc FROM faz33_fixtures WHERE fixture_id=?',(fixture,)).fetchone()
            if identity!=(e['home_team_id'],e['away_team_id'],e['start_ts_utc']):raise ValueError('final/prematch identity mismatch')
            prior=db.execute('SELECT payload,sha256 FROM faz33_evaluations WHERE fixture_id=?',(fixture,)).fetchone()
            if prior:
                old=json.loads(prior[0])
                if digest(old)!=prior[1] or old['parsed']!=parsed:raise ValueError('conflicting immutable final')
                return False
            from nba_research_store import compact_summary
            p=dict(summary=compact_summary(raw),parsed=parsed,source_observed_utc=source_observed_utc,ingested_utc=now,source_url='https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event='+fixture)
            db.execute('INSERT INTO faz33_evaluations VALUES (?,?,?,?)',(fixture,now,canonical_json(p),digest(p)))
        return True


def inspect(path,training_horizon='T60M'):
    from collections import Counter
    from shadow_ridge import validate_example
    ledger=object.__new__(CutLedger);ledger.path=str(path)
    ledger.connect=lambda:sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
    with ledger.connect() as db:
        ledger.mode=db.execute('SELECT mode FROM faz33_meta').fetchone()[0]
        if db.execute('PRAGMA integrity_check').fetchone()!=('ok',):raise ValueError('SQLite integrity failure')
        cuts=db.execute('SELECT fixture_id,horizon,cutoff_utc,recorded_utc,payload,sha256 FROM faz33_cuts').fetchall()
        identities={r[0]:r[1:] for r in db.execute('SELECT * FROM faz33_fixtures')}
        if set(identities)!={r[0] for r in cuts}:raise ValueError('orphan fixture/cut registry')
        finals={}
        for fixture,recorded,raw,sha in db.execute('SELECT * FROM faz33_evaluations'):
            p=json.loads(raw)
            if digest(p)!=sha or period_final(p['summary'],p['source_observed_utc'])!=p['parsed'] or not p['source_observed_utc']<=p['ingested_utc']==recorded<=int(time.time()):raise ValueError('invalid final evidence')
            e=p['parsed']['event'];require_regular(p['summary']['header'],e['start_ts_utc'])
            if e['provider_fixture_id']!=fixture or identities.get(fixture)!=(e['home_team_id'],e['away_team_id'],e['start_ts_utc']):raise ValueError('final/registry identity mismatch')
            finals[fixture]=p
    examples=[];ready=set();counts=Counter();missing=Counter();fixtures=set();shadows=Counter()
    for fixture,horizon,cutoff,recorded,raw,sha in cuts:
        p=json.loads(raw)
        if digest(p)!=sha or (fixture,horizon,cutoff)!=(p['fixture']['provider_fixture_id'],p['horizon'],p['cutoff_utc']):raise ValueError('cut digest/index mismatch')
        validate_packet(p,recorded,ledger.mode);fixtures.add(fixture);counts[horizon]+=1;shadows[p['shadow']['status']]+=1
        e=p['fixture']
        if identities[fixture]!=(e['home_team_id'],e['away_team_id'],e['start_ts_utc']):raise ValueError('cut/registry identity mismatch')
        missing.update(p['missing_data']);missing.update(p['features']['payload']['missing'])
        if fixture not in finals or p['features']['payload']['status']!='READY':continue
        final=finals[fixture];e=final['parsed']['event']
        if any(e[k]!=p['fixture'][k] for k in ('provider_fixture_id','home_team_id','away_team_id','start_ts_utc')):raise ValueError('final identity changed')
        ready.add(fixture)
        if horizon==training_horizon:
            label=dict(summary=final['summary'],observed_utc=final['ingested_utc']);example=dict(features=p['features'],label=label,label_sha256=digest(label))
            validate_example(example);examples.append(example)
    return dict(mode=ledger.mode,prospective_cuts=len(cuts) if ledger.mode=='PROSPECTIVE' else 0,synthetic_cuts=len(cuts) if ledger.mode=='SYNTHETIC_TEST' else 0,
        distinct_games=len(fixtures),cuts_by_horizon=dict(counts),verified_final_games=len(finals),ready_unique_feature_label_games=len(ready),training_horizon=training_horizon,
        eligible_training_examples=len(examples) if ledger.mode=='PROSPECTIVE' else 0,synthetic_eligible_examples=len(examples) if ledger.mode=='SYNTHETIC_TEST' else 0,examples=examples if ledger.mode=='PROSPECTIVE' else [],shadow_statuses=dict(shadows),missing_data=dict(missing),integrity='ok',original_predictions_modified=False)

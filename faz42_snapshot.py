"""Unpersisted FAZ42 experimental snapshots and separate final reconciliation.

Real storage activation requires separate approval. No automatic fitting or sends.
"""
from copy import deepcopy
import hashlib
import math
from pathlib import Path
import re
import subprocess
import time

from prediction_inputs import digest
from faz40_archive import require
from faz40_research import MODEL,MISSING
from faz41_evidence import REGISTRY,REGISTRY_PIN,_fixture
from faz41_adapters import replay
from faz42_history import forecast,period_errors
from faz42_schedule import validate_schedule

MODULES=('faz40_research.py','prematch_monte_carlo.py','faz41_adapters.py','faz41_evidence.py',
         'faz42_history.py','faz42_schedule.py','faz42_snapshot.py')


def model_manifest():
    root=Path(__file__).resolve().parent
    git=lambda *args:subprocess.check_output(['git',*args],cwd=root,text=True).strip()
    require(git('branch','--show-current').startswith('feature/') and not git('status','--porcelain'), 'MODEL_SOURCE_NOT_CLEAN_FEATURE_BRANCH')
    p=dict(schema_version=1,model=MODEL,git_sha=git('rev-parse','HEAD'),commit_utc=int(git('show','-s','--format=%ct','HEAD')),
        materialized_at_utc=int(time.time()),purpose='EXPERIMENTAL_DRY_RUN',
        modules_sha256={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in MODULES})
    require(git('rev-parse','HEAD')==p['git_sha'] and not git('status','--porcelain'),'MODEL_SOURCE_CHANGED_DURING_MANIFEST')
    return dict(payload=p,sha256=digest(p))


def validate_model(m,cutoff):
    p=m['payload'];require(set(m)=={'payload','sha256'} and set(p)==set('schema_version model git_sha commit_utc materialized_at_utc purpose modules_sha256'.split()) and m['sha256']==digest(p) and p['schema_version']==1 and
        p['model']==MODEL and re.fullmatch('[0-9a-f]{40}',p['git_sha']) and p['purpose'] in ('SYNTHETIC_TEST','EXPERIMENTAL_DRY_RUN') and
        type(p['commit_utc']) is int and type(p['materialized_at_utc']) is int and
        0<p['commit_utc']<=p['materialized_at_utc']<=cutoff and type(p['modules_sha256']) is dict and p['modules_sha256'] and
        all(type(k) is str and type(v) is str and re.fullmatch('[0-9a-f]{64}',v) for k,v in p['modules_sha256'].items()),'MODEL_MANIFEST_MISMATCH')
    return p


def build_snapshot(observations,schedule,canonical_id,model,*,cutoff_utc,registry=REGISTRY,registry_pin=REGISTRY_PIN,
                   minimum_team_games=5,simulations=10000,seed=20261106):
    now=int(time.time());require(type(cutoff_utc) is int and 0<cutoff_utc<=now<=cutoff_utc+60,'SNAPSHOT_CREATION_CLOCK')
    m=validate_model(model,cutoff_utc)
    d=validate_schedule(schedule,cutoff_utc=cutoff_utc,maximum_age_seconds=100*366*86400,
                        registry=registry,registry_pin=registry_pin,require_permitted=False)
    matches=[r['fixture'] for r in d['fixtures'] if r['fixture']['canonical_id']==canonical_id]
    require(len(matches)==1,'DISCOVERED_FIXTURE_REQUIRED');f=matches[0]
    usage='SYNTHETIC_TEST' if d['usage']=='SYNTHETIC_TEST' else 'UNPERSISTED_DRY_RUN'
    require((usage=='SYNTHETIC_TEST')==(m['purpose']=='SYNTHETIC_TEST'),'MODEL_SCHEDULE_USAGE_MISMATCH')
    reason=None;out=None
    try:
        require(now<f['start_utc'],'ALREADY_STARTED')
        validate_schedule(schedule,cutoff_utc=cutoff_utc,registry=registry,registry_pin=registry_pin)
        out=forecast(observations,f,cutoff_utc,registry=registry,registry_pin=registry_pin,
                     minimum_team_games=minimum_team_games,simulations=simulations,seed=seed)
        if out['prediction'] is None:reason=out['abstain_reason']
        if out['prediction'] is not None:
            require((out['usage']=='SYNTHETIC_TEST')==(usage=='SYNTHETIC_TEST'),'MIXED_SYNTHETIC_REAL_SNAPSHOT')
    except ValueError as ex:reason=str(ex)
    created=int(time.time())
    if created>=f['start_utc']:reason='TIPOFF_REACHED_DURING_GENERATION'
    if created>cutoff_utc+60:reason='GENERATION_DEADLINE_EXCEEDED'
    ids=[] if out is None else out['evidence_sha256'];sources=sorted({o['sha256']:o for o in observations if o['sha256'] in ids}.values(),key=lambda o:o['sha256'])
    p=dict(schema_version=1,usage=usage,fixture=f,cutoff_utc=cutoff_utc,created_utc=created,
        status='ABSTAIN' if reason else 'PREDICTED_EXPERIMENTAL',abstain_reason=reason,model_manifest=deepcopy(model),
        source_digest=digest(dict(schedule=schedule['sha256'],history=sorted(ids))),schedule=deepcopy(schedule),
        history=deepcopy(sources),scope='REGULATION_ONLY',model=MODEL,
        prediction=None if reason else out['prediction'],simulation=None if reason else out['simulation'],
        minimum_team_games=minimum_team_games,seed=seed,simulations=simulations,registry_sha256=registry_pin,
        missing=list(MISSING)+['HISTORY_NOT_EVALUATED'] if out is None else out['missing'],calibration_status='NOT_ESTABLISHED',
        prospective_records_created=0,storage_status='NOT_ACTIVATED')
    return dict(payload=p,sha256=digest(p))


def validate_snapshot(snapshot,*,registry=REGISTRY,registry_pin=REGISTRY_PIN,recompute=False):
    p=snapshot['payload'];require(set(p)==set('schema_version usage fixture cutoff_utc created_utc status abstain_reason model_manifest source_digest schedule history scope model prediction simulation minimum_team_games seed simulations registry_sha256 missing calibration_status prospective_records_created storage_status'.split()),'SNAPSHOT_PAYLOAD_SCHEMA')
    require(p['calibration_status']=='NOT_ESTABLISHED' and p['prospective_records_created']==0 and p['storage_status']=='NOT_ACTIVATED' and set(MISSING)<=set(p['missing']),'SNAPSHOT_UNVERIFIED_CLAIMS')
    require(set(snapshot)=={'payload','sha256'} and digest(p)==snapshot['sha256'] and
        p['schema_version']==1 and p['scope']=='REGULATION_ONLY' and p['model']==MODEL and
        p['usage'] in ('SYNTHETIC_TEST','UNPERSISTED_DRY_RUN') and p['registry_sha256']==registry_pin,'SNAPSHOT_DIGEST_OR_SCHEMA')
    f=p['fixture'];_fixture(f);m=validate_model(p['model_manifest'],p['cutoff_utc'])
    require((p['usage']=='SYNTHETIC_TEST')==(m['purpose']=='SYNTHETIC_TEST'),'MODEL_SCHEDULE_USAGE_MISMATCH')
    require(all(type(p[k]) is int for k in ('cutoff_utc','created_utc')) and 0<p['cutoff_utc']<=p['created_utc']<=int(time.time()),'SNAPSHOT_CHRONOLOGY')
    ids=sorted({o['sha256'] for o in p['history']})
    require(len(ids)==len(p['history']) and p['source_digest']==digest(dict(schedule=p['schedule']['sha256'],history=ids)),'SNAPSHOT_SOURCE_BINDING')
    d=validate_schedule(p['schedule'],cutoff_utc=p['cutoff_utc'],maximum_age_seconds=100*366*86400,
                        registry=registry,registry_pin=registry_pin,require_permitted=False)
    require(any(r['fixture']==f for r in d['fixtures']),'SNAPSHOT_FIXTURE_BINDING')
    if p['status']=='ABSTAIN':
        require(type(p['abstain_reason']) is str and p['abstain_reason'] and p['prediction'] is None and p['simulation'] is None,'ABSTAIN_CANNOT_HAVE_FORECAST')
        return p
    require(p['status']=='PREDICTED_EXPERIMENTAL' and p['abstain_reason'] is None and
            p['created_utc']<f['start_utc'] and p['created_utc']<=p['cutoff_utc']+60,'PREDICTION_NOT_PREMATCH')
    validate_schedule(p['schedule'],cutoff_utc=p['cutoff_utc'],registry=registry,registry_pin=registry_pin)
    for o in p['history']:
        replay(o,fixture=o['payload']['fixture'],cutoff_utc=p['cutoff_utc'],maximum_age_seconds=90*86400,registry=registry,registry_pin=registry_pin)
        require(o['payload']['fixture']['start_utc']<p['cutoff_utc'],'SNAPSHOT_FUTURE_LABEL')
    q=p['prediction'];s=p['simulation']
    for side in ('home','away'):
        v=q[side];require(type(v['quarters']) is list and len(v['quarters'])==4 and all(type(x) in (int,float) and math.isfinite(x) and x>=0 for x in v['quarters']), 'INVALID_QUARTER_PROJECTION')
        require(abs(sum(v['quarters'])-v['total'])<1e-8 and abs(sum(v['quarters'][:2])-v['first_half'])<1e-8 and
                abs(sum(v['quarters'][2:])-v['second_half'])<1e-8,'INCONSISTENT_PERIOD_TOTALS')
    require(abs(q['total']-q['home']['total']-q['away']['total'])<1e-8 and
            abs(q['home_margin']-q['home']['total']+q['away']['total'])<1e-8,'INCONSISTENT_MATCH_TOTALS')
    require(type(s['simulations']) is int and s['simulations']>=10000 and len(s['probabilities'])==3 and
            all(type(x) in (int,float) and math.isfinite(x) and 0<=x<=1 for x in s['probabilities']) and abs(sum(s['probabilities'])-1)<1e-10,
            'INVALID_REGULATION_SIMULATION')
    if recompute:
        check=forecast(p['history'],f,p['cutoff_utc'],registry=registry,registry_pin=registry_pin,
            minimum_team_games=p['minimum_team_games'],simulations=p['simulations'],seed=p['seed'])
        require(check['prediction']==q and check['simulation']==s and check['evidence_sha256']==ids,'FROZEN_PREDICTION_CANNOT_REPLAY')
    return p


def reconcile(snapshot,final,*,asof_utc,registry=REGISTRY,registry_pin=REGISTRY_PIN):
    p=validate_snapshot(snapshot,registry=registry,registry_pin=registry_pin)
    require(p['status']=='PREDICTED_EXPERIMENTAL','ABSTAIN_HAS_NO_EVALUATION')
    r=replay(final,fixture=p['fixture'],cutoff_utc=asof_utc,maximum_age_seconds=100*366*86400,registry=registry,registry_pin=registry_pin)
    require(r['data_type']=='OFFICIAL_STAT' and r['observed_at_utc']>p['fixture']['start_utc'],'VERIFIED_FINAL_REQUIRED')
    require((r['usage']=='SYNTHETIC_TEST')==(p['usage']=='SYNTHETIC_TEST'),'MIXED_SYNTHETIC_REAL_RESULT')
    actual=r['claims'];errors=period_errors(p['prediction'],actual);h=actual['regulation_home'];a=actual['regulation_away']
    probs=p['simulation']['probabilities'];index=0 if h>a else 1 if h<a else 2
    out=dict(schema_version=1,fixture=p['fixture'],usage=p['usage'],model=MODEL,scope='REGULATION_ONLY',
        prediction_sha256=snapshot['sha256'],result_sha256=final['sha256'],result=deepcopy(final),asof_utc=asof_utc,
        actual_final=dict(home=actual['final_home'],away=actual['final_away']),actual_regulation=dict(home=h,away=a),
        period_errors=errors,regulation_brier=sum((v-float(i==index))**2 for i,v in enumerate(probs)),
        regulation_log_loss=-math.log(max(probs[index],1e-15)),calibration_status='NOT_ESTABLISHED',
        prospective_records_created=0,parameters_updated=False)
    return dict(payload=out,sha256=digest(out))

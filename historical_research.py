"""Source-clock historical reconstructions, explicitly incompatible with live artifacts."""
from datetime import datetime,timezone
import time
from prediction_inputs import digest
from period_feature_layer import materialize_period,export_observations
from shadow_features import _calculate_selected
from prospective_error_audit import period_final
from nba_research_store import validate_summary


def reconstruct(store,target,cutoff):
    now=int(time.time())
    if type(cutoff) is not int or not 0<cutoff<target['start_ts_utc']<=now:
        raise ValueError('research target must be historical; never a live snapshot')
    start=datetime.fromtimestamp(target['start_ts_utc'],timezone.utc)
    year=start.year+int(start.month>=7)
    selected=store.select(cutoff,'RESEARCH_SOURCE_CLOCK',year)
    selected=[r for r in selected if cutoff-45*86400<r['payload']['facts']['event']['start_ts_utc']<cutoff]
    records=[]
    for r in selected:
        p=r['payload']
        records.append(materialize_period(p['summary'],source_observed_utc=p['source_observed_utc'],
            source_evidence_sha256=r['sha256'],input_ref=dict(research_observation_id=r['observation_id'])))
    records=export_observations(records)
    features=_calculate_selected(records,target,cutoff,now)
    features['payload'].update(usage='RETROSPECTIVE_RESEARCH',availability_policy='ARCHIVED_SOURCE_CLOCK_NOT_LIVE_INGEST',
                               team_ids=sorted(store.team_ids))
    features['sha256']=digest(features['payload'])
    return features


def validate_research_example(example):
    envelope=example['features'];f=envelope['payload'];label=example['label']
    if digest(f)!=envelope['sha256'] or f.get('usage')!='RETROSPECTIVE_RESEARCH':raise ValueError('research envelope required')
    if not f['cutoff_utc']<f['target']['start_ts_utc']<=f['created_utc']<=int(time.time()):raise ValueError('research time labels inconsistent')
    records=export_observations(f['source_records'])
    for r in records:
        p=r['payload'];event=period_final(p['original_summary'],p['source_observed_utc'])['event']
        validate_summary(p['original_summary'],p['source_observed_utc'],set(f['team_ids']))
        target_start=datetime.fromtimestamp(f['target']['start_ts_utc'],timezone.utc)
        year=target_start.year+int(target_start.month>=7)
        if (p['original_summary']['header']['season']['year']!=year
            or not f['cutoff_utc']-45*86400<event['start_ts_utc']<f['cutoff_utc']
            or not p['source_observed_utc']<f['cutoff_utc'] or event['provider_fixture_id']==f['target']['provider_fixture_id']):
            raise ValueError('future or self-target source in research features')
    expected=_calculate_selected(records,f['target'],f['cutoff_utc'],f['created_utc'])
    expected['payload'].update(usage='RETROSPECTIVE_RESEARCH',availability_policy='ARCHIVED_SOURCE_CLOCK_NOT_LIVE_INGEST',team_ids=f['team_ids'])
    expected['sha256']=digest(expected['payload'])
    if expected!=envelope or f['status']!='READY':raise ValueError('unavailable or changed retrospective features')
    if digest(label)!=example['label_sha256']:raise ValueError('label digest mismatch')
    parsed=period_final(label['summary'],label['observed_utc']);e=parsed['event']
    validate_summary(label['summary'],label['observed_utc'],set(f['team_ids']))
    if any(e[k]!=f['target'][k] for k in ('provider_fixture_id','start_ts_utc','home_team_id','away_team_id')) or not e['start_ts_utc']<label['observed_utc']<=int(time.time()):
        raise ValueError('research label identity/time mismatch')
    if min(parsed['regulation_home'],parsed['regulation_away'])<=0:raise ValueError('invalid quarter share target')
    return f,parsed


def examples_from_store(store):
    observations=store.observations();targets={}
    for r in observations:
        p=r['payload'];key=p['facts']['event']['provider_fixture_id']
        if key not in targets or p['source_observed_utc']<targets[key]['payload']['source_observed_utc']:targets[key]=r
    examples=[];rejected=[]
    for fixture,record in targets.items():
        p=record['payload'];event=p['facts']['event'];target={k:event[k] for k in ('provider','provider_fixture_id','start_ts_utc','home_team_id','away_team_id')}
        # Explicit hypothetical cutoff, not an asserted original prediction time.
        cutoff=target['start_ts_utc']-1
        features=reconstruct(store,target,cutoff)
        if features['payload']['status']!='READY':
            rejected.append(dict(fixture_id=fixture,reason='INSUFFICIENT_PRESTART_FEATURE_COVERAGE',missing=features['payload']['missing'],source_games=len(features['payload']['source_records'])));continue
        label=dict(summary=p['summary'],observed_utc=p['source_observed_utc'])
        example=dict(features=features,label=label,label_sha256=digest(label))
        validate_research_example(example);examples.append(example)
    return examples,rejected

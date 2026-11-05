"""Optional atomic shadow/reference bundle; never enrich an existing forecast."""
from copy import deepcopy
import time
from prediction_inputs import digest
from shadow_features import make_features
from shadow_ridge import predict


def build_attempt(reference_bundle,input_snapshot,config):
    target=config['target'];cutoff=reference_bundle['generated_at']
    p=dict(model_id='FAZ31_RIDGE_V1',source_version=reference_bundle['model_version'],
        fixture=target,cutoff_utc=cutoff,reference_input_sha256=input_snapshot['sha256'],
        reference_multilayer_sha256=digest(reference_bundle['multilayer']),created_utc=int(time.time()),
        artifact=config.get('artifact'),features=None,prediction=None,
        calibration_status='NOT_ESTABLISHED',production_promoted=False,
        shadow_model_version=config['artifact']['payload']['source_version'] if config.get('artifact') else reference_bundle['model_version'])
    try:
        p['features']=make_features(config['period_records'],target,cutoff)
        if p['features']['payload']['status']!='READY':
            p.update(status='ABSTAIN_FEATURE_COVERAGE',missing=p['features']['payload']['missing'])
        elif p['artifact'] is None:p.update(status='ABSTAIN_NOT_TRAINED',missing=['TIMESTAMPED_TRAIN_VALIDATION_TEST_DATA'])
        else:p.update(status='PREDICTED_EXPERIMENTAL',prediction=predict(p['artifact'],p['features']),missing=[])
    except ValueError as exc:
        p.update(status='ABSTAIN_UNAVAILABLE_AT_CUTOFF',missing=[str(exc)])
    return dict(payload=p,sha256=digest(p))


def validate_attempt(attempt,reference_bundle,input_snapshot,fixture_id,tipoff,now,replay_prediction=True):
    p=attempt['payload']
    if p.get('model_id')!='FAZ31_RIDGE_V1' or p.get('production_promoted') is not False or p.get('calibration_status')!='NOT_ESTABLISHED':raise ValueError('invalid shadow policy flags')
    if digest(p)!=attempt['sha256']:raise ValueError('shadow digest mismatch')
    if (p['reference_input_sha256']!=input_snapshot['sha256'] or p['cutoff_utc']!=reference_bundle['generated_at']
        or p['source_version']!=reference_bundle['model_version'] or p['reference_multilayer_sha256']!=digest(reference_bundle['multilayer'])
        or p['fixture']['provider_fixture_id']!=fixture_id or p['fixture']['start_ts_utc']!=tipoff
        or not p['cutoff_utc']<=p['created_utc']<=now<tipoff):
        raise ValueError('shadow/reference identity or chronology mismatch')
    if p['prediction'] is not None:
        if p['status']!='PREDICTED_EXPERIMENTAL' or p['features'] is None or p['artifact'] is None:
            raise ValueError('incomplete trained shadow')
        if digest(p['artifact']['payload'])!=p['artifact']['sha256'] or p['prediction']['artifact_sha256']!=p['artifact']['sha256'] or p['prediction']['feature_sha256']!=p['features']['sha256']:
            raise ValueError('shadow artifact/feature binding mismatch')
        if replay_prediction:
            expected=predict(p['artifact'],p['features'])
            if expected!=p['prediction']:raise ValueError('shadow prediction replay mismatch')
    elif not p['status'].startswith('ABSTAIN_'):raise ValueError('missing shadow prediction not marked')


def evaluate_pairs(database):
    """Read stored same-cutoff normal-time outputs; no forecast recalculation."""
    import json
    from prospective_error_audit import audit,read_only_ledger
    from model_evaluation import paired_compare
    from shadow_probability import probability_metrics
    verified=audit([database]);ledger=read_only_ledger(database)
    indexed={r['fixture_id']:r for r in verified['rows'] if r.get('scope')=='REGULATION_ONLY' and r['status']=='evaluated'}
    pairs=[];pending=[]
    with ledger._connect() as db:rows=db.execute('SELECT fixture_id,start_utc,recorded_utc,payload FROM faz24_stages').fetchall()
    for fixture,start,recorded,raw in rows:
        bundle=json.loads(raw);attempt=bundle.get('shadow_pair')
        if attempt is None:continue
        p=attempt['payload']
        if digest(p)!=attempt['sha256']:raise ValueError('shadow pair corruption')
        inputs=ledger.load_prediction_inputs('NBA',fixture)
        validate_attempt(attempt,bundle,inputs,fixture,start,recorded,replay_prediction=False)
        if p['prediction'] is None:
            pending.append(dict(fixture_id=fixture,status=p['status']));continue
        reference=indexed.get(fixture)
        if reference is None:
            pending.append(dict(fixture_id=fixture,status='AWAITING_VERIFIED_REGULATION_RESULT'));continue
        shadow=deepcopy(reference);prediction=p['prediction']
        shadow.update(model='FAZ31_RIDGE_V1',model_version=p['shadow_model_version'],
            expected_home=prediction['expected_home'],expected_away=prediction['expected_away'])
        comparison=paired_compare([reference],[shadow])
        margin=reference['actual_home']-reference['actual_away']
        outcome='home' if margin>0 else 'away' if margin<0 else 'tie'
        probabilities=prediction['probabilities']
        pairs.append(dict(fixture_id=fixture,comparison=comparison,
            probability_metrics=probability_metrics([probabilities],[outcome]) if probabilities else probability_metrics([],[])))
    return dict(pairs=pairs,pending_or_abstained=pending,real_paired_games=len(pairs),
                statistical_claim='NONE_SMALL_SAMPLE',production_promoted=False)

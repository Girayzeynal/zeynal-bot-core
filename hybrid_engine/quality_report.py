"""UserLAnd/local read-only quality report; existing forecasts are never re-created."""
import argparse
import json

from core.team_identity import digest
from hybrid_engine.archive_audit import audit_ledger
from hybrid_engine.boxes import publish_json
from hybrid_engine.data import local_path
from hybrid_engine.quality_monitor import monitor


def read_existing_plan(directory):
    """Inspect a previously registered plan without registering or creating one."""
    from hybrid_engine.calibration_guard import CalibrationPlan
    root=local_path(directory)
    files=list(root.glob('plan-*.json')) if root.is_dir() else []
    if len(files)!=1:raise ValueError('EXACTLY_ONE_EXISTING_CALIBRATION_PLAN_REQUIRED')
    path=local_path(files[0])
    if path.stat().st_size>128*1024:raise ValueError('EXISTING_CALIBRATION_PLAN_SIZE')
    w=json.loads(path.read_text());plan=CalibrationPlan(w['payload'],w['sha256'])
    if path.stem!='plan-'+plan.sha256:raise ValueError('EXISTING_CALIBRATION_PLAN_PIN')
    plan.validate();return plan


def report(ledger, *, assets_directory=None, plan=None):
    audit = audit_ledger(ledger, assets_directory=assets_directory)
    performance = audit.get('performance')
    quality = None
    cards = []
    if performance is not None:
        quality = monitor(performance['forecasts'], asof_utc=audit['observed_at_utc'])
        for row in audit['rows']:
            # audit_snapshot's pin, not this report, authenticates native sources.
            # Full cards are constructed in the isolated inference service; the
            # CLI publishes per-row evidence and prior-only metrics without
            # reading/serializing another raw database copy.
            generated = row.get('prediction_generated_at_utc')
            if type(generated) is int and row.get('source_audit'):
                prior = monitor(performance['forecasts'], asof_utc=generated)
                cards.append(dict(fixture_id=row['fixture_id'], snapshot_sha256=row['snapshot_sha256'],
                    prior_only_quality=prior,
                    native_source_audit=row['source_audit'],
                    calibration_status='NOT_CALIBRATED', confidence_index=None))
    from hybrid_engine.calibration_review import review
    from hybrid_engine.forecast_error_review import review as error_review
    return dict(format='PHASE92_READ_ONLY_QUALITY_REPORT_V1', archive_audit=audit,
        error_review=None if performance is None else error_review(performance['forecasts'],asof_utc=audit['observed_at_utc'],
            profiles=[r['input_profile'] for r in audit['rows'] if r.get('input_profile') and not r['findings']]),
        calibration_review=review(audit,plan=plan),
        current_quality=quality, prediction_time_evidence=cards,
        real_telegram_e2e='BLOCKED_NOT_TESTED_BY_THIS_OFFLINE_REPORT',
        calibration_fit=False, predictions_recomputed=False, production_changed=False)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ledger', required=True)
    p.add_argument('--assets-directory')
    plans=p.add_mutually_exclusive_group()
    plans.add_argument('--calibration-plan-directory',help='Optional new/existing isolated forward plan; never backdated')
    plans.add_argument('--existing-calibration-plan-directory',help='Read an existing plan only; never register or write one')
    p.add_argument('--output-directory', required=True)
    a = p.parse_args()
    plan=None
    if a.calibration_plan_directory:
        from hybrid_engine.calibration_guard import read_or_register_plan
        plan=read_or_register_plan(a.calibration_plan_directory)
    elif a.existing_calibration_plan_directory:plan=read_existing_plan(a.existing_calibration_plan_directory)
    result = report(a.ledger, assets_directory=a.assets_directory,plan=plan)
    root = local_path(a.output_directory)
    root.mkdir(parents=True, exist_ok=True)
    path = root / ('quality-'+digest(result)+'.json')
    publish_json(path, dict(payload=result, sha256=digest(result)))
    errors=result['error_review'];groups=[] if errors is None else errors['groups']
    print(json.dumps(dict(path=str(path), snapshots=result['archive_audit']['snapshots_examined'],
        sqlite_integrity=result['archive_audit']['sqlite_integrity'],
        database_bytes_unchanged=result['archive_audit']['database_bytes_unchanged'],
        error_review_settled=sum(g['n'] for g in groups),
        native_input_profiles=sum(c['input_profile_status']=='FROZEN_INPUTS_VERIFIED' for g in groups for c in g['cases']),
        top_total_errors=[dict(model_digest=g['cohort']['model_digest'],fixture_id=c['fixture_id'],
            provider_fixture_ids=c['provider_fixture_ids'],signed_error=c['signed_total_error']) for g in groups for c in g['cases'][:3]],
        actual_telegram_delivery_verified=False, production_changed=False)))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps(dict(status='BLOCKED', error_type=type(exc).__name__,
                              reason='QUALITY_REPORT_INCOMPLETE_NO_FORECASTS_CHANGED')))
        raise SystemExit(2)

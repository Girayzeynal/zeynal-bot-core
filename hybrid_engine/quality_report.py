"""UserLAnd/local read-only quality report; existing forecasts are never re-created."""
import argparse
import json

from core.team_identity import digest
from hybrid_engine.archive_audit import audit_ledger
from hybrid_engine.boxes import publish_json
from hybrid_engine.data import local_path
from hybrid_engine.quality_monitor import monitor


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
    return dict(format='PHASE92_READ_ONLY_QUALITY_REPORT_V1', archive_audit=audit,
        calibration_review=review(audit,plan=plan),
        current_quality=quality, prediction_time_evidence=cards,
        real_telegram_e2e='BLOCKED_NOT_TESTED_BY_THIS_OFFLINE_REPORT',
        calibration_fit=False, predictions_recomputed=False, production_changed=False)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ledger', required=True)
    p.add_argument('--assets-directory')
    p.add_argument('--calibration-plan-directory',help='Optional new/existing isolated forward plan; never backdated')
    p.add_argument('--output-directory', required=True)
    a = p.parse_args()
    plan=None
    if a.calibration_plan_directory:
        from hybrid_engine.calibration_guard import read_or_register_plan
        plan=read_or_register_plan(a.calibration_plan_directory)
    result = report(a.ledger, assets_directory=a.assets_directory,plan=plan)
    root = local_path(a.output_directory)
    root.mkdir(parents=True, exist_ok=True)
    path = root / ('quality-'+digest(result)+'.json')
    publish_json(path, dict(payload=result, sha256=digest(result)))
    print(json.dumps(dict(path=str(path), snapshots=result['archive_audit']['snapshots_examined'],
        sqlite_integrity=result['archive_audit']['sqlite_integrity'],
        database_bytes_unchanged=result['archive_audit']['database_bytes_unchanged'],
        actual_telegram_delivery_verified=False, production_changed=False)))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps(dict(status='BLOCKED', error_type=type(exc).__name__,
                              reason='QUALITY_REPORT_INCOMPLETE_NO_FORECASTS_CHANGED')))
        raise SystemExit(2)

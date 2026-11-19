"""Connect authenticated live archive evidence to the existing sealed guard.

An exact fitted model and season form a separate review. Registering a plan now
cannot turn old observations into confirmatory future OOS calibration results.
"""
from collections import Counter, defaultdict

from hybrid_engine.calibration_guard import PLAN_DEFAULTS, review_checkpoints, shadow_walk_forward
from hybrid_engine.quality_monitor import identity, monitor


def review(audit, *, plan=None):
    rejected = Counter()
    records = defaultdict(list)
    report = audit.get('performance') or {}
    native = {(r['fixture_id'],r['model_digest']):r for r in audit['rows']}
    asof = audit['observed_at_utc']
    for r in report.get('forecasts', []):
        evidence = native.get((r['fixture_id'],r['model_digest']), {})
        if (evidence.get('findings') or not evidence.get('calibration_inputs') or
                evidence.get('source_audit',{}).get('status') != 'VERIFIED_WITH_LIMITATIONS' or
                evidence.get('source_audit',{}).get('snapshot_sha256') != r['snapshot_sha256']):
            rejected['FULL_NATIVE_INPUT_AND_MODEL_AUDIT_REQUIRED'] += 1
            continue
        checked = monitor([r], asof_utc=asof)
        if not checked['groups'] or checked['groups'][0]['settled'] != 1:
            rejected['NO_ELIGIBLE_PUBLISHED_PREMATCH_AND_AVAILABLE_FINAL'] += 1
            continue
        if r.get('winner') is None:
            rejected['NO_ORIGINAL_THREE_CLASS_PROBABILITY'] += 1
            continue
        trace = evidence['calibration_inputs']
        actual = r['actual']
        records[identity(r)].append(dict(fixture_id=r['fixture_id'],league=r['league'],
            model_version=r['model_version'],model_digest=r['model_digest'],season=r['season'],
            snapshot_sha256=r['snapshot_sha256'],probabilities=list(r['winner']),
            outcome=0 if actual[0]>actual[1] else 1 if actual[0]==actual[1] else 2,
            prediction_utc=r['prediction_generated_at_utc'],tipoff_utc=r['fixture_start_utc'],
            label_available_utc=r['label_available_utc'],data_class='REAL_CAPTURED_PREMATCH',
            period='FULL_GAME',market='WINNER',settlement_scope='REGULATION_ONLY',line=0.,
            **{k:trace[k] for k in ('inputs_available_max_utc','model_fit_cutoff_utc','model_training_ids')}))
    out = []
    for key, rows in sorted(records.items()):
        # Keep immutable fit digest / season isolation before invoking the
        # original guard, whose legacy cohort key is coarser.
        item = dict(zip(('league','season','model_version','model_digest'),key), raw_records=len(rows))
        if plan is not None:
            item['checkpoints'] = review_checkpoints(rows,asof_utc=asof,plan=plan)
            item['shadow'] = shadow_walk_forward(rows,plan,asof_utc=asof)
        else:
            item['status'] = 'BLOCKED_NO_REGISTERED_FORWARD_CALIBRATION_PLAN'
        out.append(item)
    return dict(format='PHASE92_NATIVE_CALIBRATION_REVIEW_V1',groups=out,exclusions=dict(rejected),
        plan_sha256=None if plan is None else plan.sha256,
        minimum_past_fit=PLAN_DEFAULTS['minimum_past_fit'],
        minimum_future_audit=PLAN_DEFAULTS['minimum_oos_audit'],
        minimum_day_clusters=PLAN_DEFAULTS['minimum_day_clusters'],
        status='INSUFFICIENT_NATIVE_SETTLED_COHORTS' if not out else 'SHADOW_REVIEW_ONLY',
        calibration_applied_to_forecasts=False,confidence_index=None,production_enabled=False)

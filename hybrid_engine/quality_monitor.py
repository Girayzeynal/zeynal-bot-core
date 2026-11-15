"""Read-only, point-in-time quality monitoring of native-verified ledger rows.

Callers must use LedgerReports to authenticate snapshots, commit receipts and
native results. This module does not turn arbitrary JSON into verified evidence.
No training, calibration, source downloads or forecast mutation occurs here.
"""
from collections import Counter, defaultdict

from hybrid_engine.live_metrics import metrics

VERSION = 'PHASE92_POINT_IN_TIME_QUALITY_V1'
MIN_WINDOW = 100
MIN_DAYS = 8
BRIER_DRIFT_DELTA = .05


def identity(row):
    return tuple(row.get(k) for k in ('league', 'season', 'model_version', 'model_digest'))


def clock(value):
    return type(value) is int and value > 0


def monitor(rows, *, asof_utc):
    if not clock(asof_utc):
        raise ValueError('QUALITY_ASOF_UTC_REQUIRED')
    if len(rows) > 1000:
        raise ValueError('QUALITY_ROW_BUDGET')
    rejected = Counter()
    first = {}
    conflicts = set()
    for row in rows:
        stamps = [row.get(k) for k in ('prediction_generated_at_utc', 'created_utc',
                  'first_archived_at_utc', 'fixture_start_utc')]
        if not all(clock(t) for t in stamps):
            rejected['MISSING_OR_INVALID_PREMATCH_CLOCK'] += 1
            continue
        generated, created, archived, tip = stamps
        if not generated <= created <= archived < tip:
            rejected['INVALID_PREMATCH_ORDER'] += 1
            continue
        if archived > asof_utc:
            rejected['NOT_YET_ARCHIVED_AT_ASOF'] += 1
            continue
        if not all(isinstance(v, str) and v for v in identity(row)):
            rejected['INCOMPLETE_FITTED_MODEL_IDENTITY'] += 1
            continue
        if not isinstance(row.get('fixture_id'), str) or not row['fixture_id']:
            rejected['MISSING_FIXTURE_ID'] += 1
            continue
        pin = row.get('snapshot_sha256')
        if not isinstance(pin, str) or len(pin) != 64 or any(c not in '0123456789abcdef' for c in pin):
            rejected['MISSING_SNAPSHOT_PIN'] += 1
            continue
        key = (*identity(row), row['fixture_id'])
        old = first.get(key)
        if old is None or archived < old['first_archived_at_utc']:
            first[key] = row
            conflicts.discard(key)
        elif archived == old['first_archived_at_utc'] and pin != old['snapshot_sha256']:
            conflicts.add(key)
    groups = defaultdict(list)
    for key, row in first.items():
        if key in conflicts:
            rejected['CONFLICTING_FIRST_PUBLICATION'] += 1
            continue
        r = dict(row)
        if r.get('actual') is not None:
            available = r.get('label_available_utc')
            if not clock(available) or available <= r['fixture_start_utc']:
                rejected['INVALID_RESULT_AVAILABILITY'] += 1
                r['actual'] = None
            elif available > asof_utc:
                # A later result may exist in today's DB. It was unavailable then.
                r['actual'] = None
        groups[identity(r)].append(r)
    output = []
    for key, values in sorted(groups.items()):
        settled = sorted((r for r in values if r['actual'] is not None),
                         key=lambda r: (r['prediction_generated_at_utc'], r['fixture_id']))
        detail = metrics(settled)
        drift = dict(status='INSUFFICIENT_DATA', alerts=[], calibration_fit=False)
        probabilistic = [r for r in settled if r.get('winner') is not None]
        if len(probabilistic) >= 2 * MIN_WINDOW:
            current = probabilistic[-MIN_WINDOW:]
            cut = min(r['prediction_generated_at_utc'] for r in current)
            reference = [r for r in probabilistic[:-MIN_WINDOW] if r['label_available_utc'] < cut][-MIN_WINDOW:]
            days = lambda rs: len({(r['fixture_start_utc'] + 10800) // 86400 for r in rs})
            if len(reference) >= MIN_WINDOW and min(days(reference), days(current)) >= MIN_DAYS:
                baseline, recent = metrics(reference), metrics(current)
                delta = recent['winner']['brier'] - baseline['winner']['brier']
                drift = dict(status='HEURISTIC_REVIEW_ONLY', reference_n=len(reference), current_n=len(current),
                    reference_available_max_utc=max(r['label_available_utc'] for r in reference),
                    current_prediction_min_utc=cut, brier_change=delta,
                    alerts=['BRIER_DEGRADATION_REVIEW'] if delta > BRIER_DRIFT_DELTA else [],
                    statistically_confirmed_change=False, calibration_fit=False)
            else:
                drift['status'] = 'INSUFFICIENT_DISJOINT_PRIOR_LABELS_OR_DAY_CLUSTERS'
        output.append(dict(zip(('league', 'season', 'model_version', 'model_digest'), key),
            forecasts=len(values), pending=len(values)-len(settled), settled=len(settled), metrics=detail,
            drift=drift, calibration_status='NOT_CALIBRATED', confidence_index=None))
    return dict(format=VERSION, asof_utc=asof_utc, groups=output, exclusions=dict(rejected),
        input_provenance_required='LEDGER_REPORTS_NATIVE_VERIFIED_READ_ONLY',
        unit='FIRST_ARCHIVED_FIXTURE_PER_EXACT_FITTED_MODEL',
        policy=dict(minimum_reference=MIN_WINDOW, minimum_recent=MIN_WINDOW,
                    minimum_days_each=MIN_DAYS, heuristic_brier_change=BRIER_DRIFT_DELTA),
        calibration_fit=False, automatic_promotion=False, production_changed=False)


def render_monitor(report):
    lines = ['🛡 TAHMİN SAĞLIĞI | SALT OKUNUR',
             'NOT_CALIBRATED · Güven endeksi: hesaplanmadı',
             'Lig / sezon / model sürümü / fit SHA ayrı değerlendirilir.']
    if not report['groups']:
        lines.append('Uygun, ilk arşiv zamanı kanıtlı kayıt bulunamadı.')
    for g in report['groups'][:10]:
        lines.extend(['', f"{g['league']} · {g['season']} · {g['model_version'][:80]}",
                      f"Fit SHA: {g['model_digest'][:12]}",
                      f"Kayıt {g['forecasts']} · Sonuç {g['settled']} · Bekleyen {g['pending']}"])
        m = g['metrics']
        if m.get('total'):
            lines.append(f"Toplam MAE {m['total']['mae']:.2f} · RMSE {m['total']['rmse']:.2f}")
        if m.get('winner'):
            lines.append(f"Brier {m['winner']['brier']:.4f} · Log loss {m['winner']['log_loss']:.4f}")
        lines.append('Kalite takibi: ' + g['drift']['status'])
        lines.extend(g['drift']['alerts'])
    if len(report['groups']) > 10:
        lines.append('İlk 10 model kohortu gösterildi; tüm kohortlar salt okunur quality_report CLI çıktısındadır.')
    if report['exclusions']:
        lines.append('Dışlanan / sonucu bekletilen: ' + ', '.join(f'{k}={v}' for k,v in sorted(report['exclusions'].items())))
    lines.append('Bu rapor yeniden eğitim, kalibrasyon veya model üstünlüğü iddiası değildir.')
    return '\n'.join(lines)

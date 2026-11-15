"""Evidence-bound presentation policy. Never assigns an unvalidated confidence %."""
import html
import math

from core.team_identity import digest
from hybrid_engine.quality_monitor import identity, clock

VERSION = 'PHASE92_FORECAST_HEALTH_CARD_V1'
MAX_FIXTURE_AGE_SECONDS = 300


def build(snapshot, audit, *, prior_quality=None):
    reasons = []
    blockers = []
    generated = snapshot.get('prediction_generated_at_utc')
    source = snapshot.get('source_data_time_utc')
    tip = snapshot.get('fixture_start_utc')
    if (not audit or audit.get('status') != 'VERIFIED_WITH_LIMITATIONS' or
            audit.get('snapshot_sha256') != digest(snapshot) or
            audit.get('model_version') != snapshot.get('model_version')):
        blockers.append('SOURCE_TIME_MODEL_INTEGRITY_NOT_VERIFIED')
    if not all(clock(t) for t in (generated, source, tip)) or not source <= generated < tip:
        blockers.append('INVALID_PREMATCH_SOURCE_CLOCKS')
    # The maximum history receipt timestamp is not the fixture's freshness.
    # Only native fixture sources authenticated by audit_snapshot are accepted.
    urls = set((audit or {}).get('verified_fixture_sources', []))
    target_clocks = [c.get('ingested_at_utc') for c in snapshot.get('input_clocks', [])
                     if c.get('source_url') in urls and c.get('status') == 'DOCUMENT_RECEIVED'
                     and c.get('http_status') == 200]
    age = None
    if target_clocks and clock(generated) and all(clock(t) and t <= generated for t in target_clocks):
        age = generated - max(target_clocks)
        if age > MAX_FIXTURE_AGE_SECONDS:
            blockers.append('STALE_PREMATCH_FIXTURE_SOURCE')
    else:
        blockers.append('FIXTURE_FRESHNESS_NOT_VERIFIED')
    missing = sorted(set(snapshot.get('missing_data') or []))
    reasons.extend('MISSING_' + str(m).upper() for m in missing)
    reasons.append('NO_DISJOINT_VERIFIED_CALIBRATION')
    if not (audit or {}).get('measured_possession_pace_used'):
        reasons.append('POSSESSION_PACE_NOT_OBSERVED')
    if not (audit or {}).get('verified_rotation_or_player_impact_used'):
        reasons.append('PLAYER_ROTATION_EFFECT_NOT_VERIFIED')
    corr = (audit or {}).get('mean_off_diagonal_quarter_correlation')
    if type(corr) in (int, float) and math.isfinite(corr) and corr > .95:
        reasons.append('QUARTER_UNCERTAINTY_ALLOCATION_LIMITATION')
    prior = None
    if prior_quality is not None:
        if not clock(generated) or prior_quality.get('asof_utc') != generated:
            blockers.append('PRIOR_QUALITY_POINT_IN_TIME_MISMATCH')
        else:
            matches = [g for g in prior_quality.get('groups', []) if identity(g) == identity(snapshot)]
            if len(matches) == 1:
                prior = matches[0]
                if prior.get('drift', {}).get('alerts'):
                    blockers.append('PRIOR_MODEL_DRIFT_REVIEW_REQUIRED')
    if prior is None:
        reasons.append('NO_VERIFIED_PRIOR_EXACT_MODEL_RESULTS')
    return dict(format=VERSION, snapshot_sha256=digest(snapshot),
        status='ABSTAIN' if blockers else 'LIMITED_RESEARCH',
        publication_allowed=not blockers, confidence_index=None, calibration_status='NOT_CALIBRATED',
        reasons=sorted(set(reasons)), blockers=sorted(set(blockers)), missing_data=missing,
        fixture_source_age_at_generation_seconds=age,
        freshness_policy_seconds=MAX_FIXTURE_AGE_SECONDS,
        prior_validated_results=None if prior is None else prior['settled'],
        prior_metrics=None if prior is None else prior['metrics'],
        prior_quality_asof_utc=None if prior_quality is None else prior_quality.get('asof_utc'),
        probability_meaning='RAW_EVENT_PROBABILITY_NOT_CONFIDENCE',
        interval_meaning='NOMINAL_MODEL_QUANTILES_NOT_EMPIRICAL_COVERAGE',
        predictions_changed=False, production_enabled=False)


def render(card):
    n = card['prior_validated_results']
    age = card['fixture_source_age_at_generation_seconds']
    lines = ['🛡 <b>TAHMİN SAĞLIK KARTI</b>',
             'Durum: ' + card['status'],
             'NOT_CALIBRATED · Güven endeksi: yok',
             'Maç kaynağı yaşı (üretim anında): ' + ('bilinmiyor' if age is None else str(age)+' sn'),
             'Aynı fit SHA için önceki doğrulanmış sonuç: ' + ('bilinmiyor' if n is None else str(n))]
    m = card['prior_metrics'] or {}
    if m.get('total'):
        lines.append(f"Geçmiş toplam MAE: {m['total']['mae']:.2f} (betimsel)")
    if card['missing_data']:
        lines.append('Eksik: ' + html.escape(', '.join(str(x)[:40] for x in card['missing_data'][:8])))
    if 'QUARTER_UNCERTAINTY_ALLOCATION_LIMITATION' in card['reasons']:
        lines.append('Periyot bantları: yüksek ortak hareket; ayrı periyot kalibrasyonu gerekli.')
    if card['blockers']:
        lines.append('Durdurma nedeni: ' + html.escape(', '.join(card['blockers'])))
    lines.append('Olay olasılığı, aralık kapsamı ve model güveni farklı kavramlardır.')
    return '\n'.join(lines)

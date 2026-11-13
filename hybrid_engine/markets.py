"""Per-line probabilities and fail-closed calibration evidence for research replies."""
from dataclasses import dataclass
import html
import math
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np

from core.team_identity import digest
from hybrid_engine.data import STRICT, Abstain

MARKETS = ('1Q', '2Q', '3Q', '4Q', '1H', '2H', 'TOTAL', 'HOME', 'AWAY', 'MARGIN', 'HOME_HANDICAP')


def wilson(successes, count, z=1.959963984540054):
    if not count: return [0., 1.]
    p = successes/count; denom = 1+z*z/count
    center = (p+z*z/(2*count))/denom
    radius = z*math.sqrt(p*(1-p)/count+z*z/(4*count*count))/denom
    return [max(0., center-radius), min(1., center+radius)]


@dataclass(frozen=True)
class MarketCalibration:
    payload: dict
    sha256: str

    @classmethod
    def fit(cls, fit_records, audit_records, *, model_digest, market, line, cutoff_utc, minimum=100):
        """Fit reliability bins, then verify on a later disjoint OOS audit segment.

        A model/market/EXACT-line profile is deliberately not transferable to another line.
        The conservative confidence index is an audited frequency lower bound, not raw p.
        """
        if market not in MARKETS or not math.isfinite(float(line)): raise ValueError('SUPPORTED_FINITE_MARKET_REQUIRED')
        if type(cutoff_utc) is not int or not 0 < cutoff_utc <= int(time.time()): raise ValueError('PAST_CALIBRATION_CUTOFF_REQUIRED')
        if type(minimum) is not int or minimum < 30: raise ValueError('MINIMUM_CALIBRATION_POLICY')
        if len(fit_records) < minimum or len(audit_records) < minimum: raise Abstain('INSUFFICIENT_INDEPENDENT_CALIBRATION_AND_AUDIT')
        combined = fit_records+audit_records
        if len({r['fixture_id'] for r in combined}) != len(combined): raise ValueError('CALIBRATION_AUDIT_OVERLAP')
        if any(r['model_digest'] != model_digest or r['market'] != market or r['line'] != line or
            r['evidence_class'] != STRICT or r['data_class'] != 'REAL_HISTORICAL' or
            not r['prediction_utc'] < r['fixture_start_utc'] < r['label_available_utc'] <= cutoff_utc or
            r['inputs_available_max'] > r['prediction_utc'] or r['model_fit_cutoff'] > r['prediction_utc'] or
            r['fixture_id'] in r['model_training_ids'] for r in combined):
            raise ValueError('CALIBRATION_REQUIRES_STRICT_REAL_OOS_TRACE')
        if any(r['role'] != 'CALIBRATION' for r in fit_records) or any(r['role'] != 'CALIBRATION_AUDIT' for r in audit_records):
            raise ValueError('CALIBRATION_ROLE_CONFLICT')
        if max(r['label_available_utc'] for r in fit_records) > min(r['prediction_utc'] for r in audit_records):
            raise ValueError('CALIBRATION_FIT_AFTER_AUDIT_PREDICTION')
        bins = {}
        def cell(r):
            p = np.array(r['probabilities'])
            if p.shape != (3,) or not np.isfinite(p).all() or np.any(p < 0) or not np.isclose(p.sum(), 1):
                raise ValueError('CALIBRATION_PROBABILITY_SIMPLEX_REQUIRED')
            if type(r['outcome']) is not int or r['outcome'] not in (0, 1, 2): raise ValueError('CALIBRATION_OUTCOME_REQUIRED')
            choice = int(np.argmax(p)); return (choice, min(9, int(p[choice]*10)))
        for record in fit_records:
            key = cell(record); bins.setdefault(key, []).append(record)
        estimates = {key: (np.bincount([r['outcome'] for r in rows], minlength=3)+1)/(len(rows)+3) for key, rows in bins.items()}
        audits = {}; raw_losses = []; calibrated_losses = []
        for record in audit_records:
            key = cell(record)
            if key not in estimates or len(bins[key]) < 30: continue
            audits.setdefault(key, []).append(record)
            truth = np.eye(3)[record['outcome']]
            raw_losses.append(np.sum((np.array(record['probabilities'])-truth)**2))
            calibrated_losses.append(np.sum((estimates[key]-truth)**2))
        cells = {}
        for key, rows in audits.items():
            if len(rows) < 30: continue
            p = estimates[key]; choice = int(np.argmax(p)); interval = wilson(sum(r['outcome'] == choice for r in rows), len(rows))
            # Entire audited frequency interval must lie within 10 percentage points of p.
            if max(abs(interval[0]-p[choice]), abs(interval[1]-p[choice])) > .10: continue
            cells[str(key[0])+':'+str(key[1])] = dict(probabilities=p.tolist(), selected_class=choice,
                audited_count=len(rows), frequency_interval_95=interval,
                confidence_index=100*interval[0])
        if not cells or not raw_losses or np.mean(calibrated_losses) > np.mean(raw_losses):
            raise Abstain('CALIBRATION_NOT_INDEPENDENTLY_VERIFIED')
        payload = dict(format='EXACT_MARKET_CALIBRATION_V1', model_digest=model_digest,
            market=market, line=float(line), cutoff_utc=cutoff_utc, evidence_class=STRICT,
            fit_ids=sorted(r['fixture_id'] for r in fit_records), audit_ids=sorted(r['fixture_id'] for r in audit_records),
            cells=cells, audit_brier_raw=float(np.mean(raw_losses)), audit_brier_calibrated=float(np.mean(calibrated_losses)),
            record_digest=digest(combined), status='VERIFIED_ON_PAST_DISJOINT_AUDIT')
        return cls(payload, digest(payload))

    def apply(self, probabilities, *, model_digest, market, line, prediction_utc):
        p = self.payload
        values = np.asarray(probabilities, dtype=float)
        if values.shape != (3,) or not np.isfinite(values).all() or np.any(values < 0) or not np.isclose(values.sum(), 1):
            raise ValueError('CALIBRATION_PROBABILITY_SIMPLEX_REQUIRED')
        if digest(p) != self.sha256 or model_digest != p['model_digest'] or market != p['market'] or line != p['line'] or prediction_utc < p['cutoff_utc']:
            raise Abstain('CALIBRATION_SCOPE_DIGEST_OR_CLOCK_CONFLICT')
        choice = int(np.argmax(probabilities)); key = str(choice)+':'+str(min(9, int(max(probabilities)*10)))
        if key not in p['cells']: raise Abstain('NO_VERIFIED_CALIBRATION_FOR_PROBABILITY_BIN')
        return dict(p['cells'][key], calibration_digest=self.sha256)


def market_grid(forecast, lines, *, model_digest, prediction_utc, profiles=None,
                roster_verified=False, data_complete=True, model_disagreement=None):
    profiles = profiles or {}; output = []
    for market, thresholds in lines.items():
        if market not in MARKETS: raise ValueError('UNSUPPORTED_MARKET')
        if len(thresholds) > 32: raise ValueError('MARKET_LINE_BUDGET')
        if len(set(thresholds)) != len(thresholds): raise ValueError('DUPLICATE_MARKET_LINE')
        for threshold in thresholds:
            line = float(threshold)
            if not math.isfinite(line): raise ValueError('FINITE_MARKET_LINE_REQUIRED')
            item = dict(market=market, line=line, model_digest=model_digest, prediction_utc=prediction_utc,
                status='ABSTAIN', confidence_index=None, calibrated_probabilities=None, raw_probabilities=None, reasons=[])
            try: item['raw_probabilities'] = forecast.market('MARGIN' if market == 'HOME_HANDICAP' else market, -line if market == 'HOME_HANDICAP' else line)
            except Abstain as exc: item['reasons'].append(str(exc))
            if not roster_verified: item['reasons'].append('PREMATCH_ROSTER_UNVERIFIED')
            if not data_complete: item['reasons'].append('MISSING_VERIFIED_INPUTS')
            if model_disagreement is None: item['reasons'].append('MODEL_AGREEMENT_UNVERIFIED')
            elif not math.isfinite(model_disagreement) or model_disagreement > .15:
                item['reasons'].append('MODEL_PROBABILITY_DISAGREEMENT')
            profile = profiles.get((market, line))
            if profile is None: item['reasons'].append('NO_VERIFIED_PAST_CALIBRATION')
            elif not item['reasons']:
                raw = item['raw_probabilities']
                try: verified = profile.apply([raw[k] for k in ('under', 'push', 'over')],
                    model_digest=model_digest, market=market, line=line, prediction_utc=prediction_utc)
                except Abstain as exc: item['reasons'].append(str(exc))
                else:
                    item.update(status='CALIBRATED', confidence_index=verified['confidence_index'],
                        calibrated_probabilities=verified['probabilities'], calibration_digest=verified['calibration_digest'])
            output.append(item)
    return output


def render_research(markets, trace):
    """Experimental renderer only. Main's V1 registration/routing is never changed."""
    lines = ['<b>HİBRİT ARAŞTIRMA — ÜRETİM V1 DEĞİL</b>']
    labels = {'1Q': 'İlk çeyrek toplamı', '1H': 'İlk yarı toplamı', 'TOTAL': 'Maç toplamı',
        'HOME': 'Ev sahibi toplamı', 'AWAY': 'Deplasman toplamı', 'MARGIN': 'Ev sahibi farkı', 'HOME_HANDICAP': 'Ev sahibi handikabı'}
    for item in markets:
        prefix = labels[item['market']]+' | Barem '+str(item['line'])
        if item['status'] != 'CALIBRATED':
            lines.append(prefix+' | Tahmin yok: doğrulanmış güven koşulları sağlanmadı.')
        else:
            under, push, over = item['calibrated_probabilities']
            lines.append(prefix+f' | ALT %{100*under:.1f} | İADE %{100*push:.1f} | ÜST %{100*over:.1f} | Güven endeksi {item["confidence_index"]:.1f}')
    def stamp(value): return datetime.fromtimestamp(value, ZoneInfo('Europe/Istanbul')).strftime('%d.%m.%Y %H:%M:%S TSİ')
    lines += ['Model: '+html.escape(trace['model_version']),
        'Veri zamanı: '+stamp(trace['data_time_utc']), 'Tahmin zamanı: '+stamp(trace['prediction_utc']),
        'Kaynak: '+html.escape(trace['source']), 'Kaynak SHA: '+html.escape(trace['inputs_digest'][:12])]
    text = '\n'.join(lines)
    if len(text) > 4000: raise Abstain('TELEGRAM_RESEARCH_MESSAGE_BUDGET')
    return text

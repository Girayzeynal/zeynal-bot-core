"""Separate frozen score distributions from source-neutral observed market lines.

Conditional regulation mass is visible even when contract settlement is unknown.
It is not a ticket win probability, calibrated confidence or recommendation.
"""
import html
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

import numpy as np

from core.team_identity import digest
from hybrid_engine.decision_layer import DecisionDistribution, evaluate_quote, POLICY
from hybrid_engine.market_observations import validate, fixture_identity, stamp


def replay_nba(snapshot,service):
    """Recover identical archived QMC samples; no fit, source fetch or ledger write."""
    from hybrid_engine.data import Cut
    from hybrid_engine.prediction_audit import Assets
    from hybrid_engine.decision_audit import trace_for
    from hybrid_engine.intervals import prediction_intervals
    if service.prepared.digest!=snapshot['model_digest']:
        raise ValueError('MARKET_REPLAY_REQUIRES_ORIGINAL_PREPARED_MODEL')
    cut=Assets(service.assets).read(snapshot['input_asset'])
    forecast=service.prepared.model.predict(Cut(**cut),method='RQMC_HALTON',bounded_workspace=True)
    if prediction_intervals(forecast)['sample_sha256']!=snapshot['intervals']['sample_sha256']:
        raise ValueError('MARKET_REPLAY_SAMPLE_SHA_MISMATCH')
    summary=forecast.summary()
    for k in ('home','away','total','margin','quarters','halves','winner'):
        if not np.allclose(summary[k],snapshot['prediction'][k],atol=1e-8,rtol=0):
            raise ValueError('MARKET_REPLAY_PROJECTION_MISMATCH')
    return DecisionDistribution(forecast,trace_for(snapshot))


def assess(observation,distribution,*,asof_utc,native_quote=None,rule=None):
    p=validate(observation['payload']);stamp(asof_utc)
    if digest(p)!=observation['sha256']:
        raise ValueError('MARKET_VIEW_OBSERVATION_PIN')
    if asof_utc>int(time.time()):
        raise ValueError('ACTUAL_MARKET_VIEW_CLOCK_REQUIRED')
    trace=distribution.trace
    expected=fixture_identity({k:trace[k] for k in ('league','season','fixture_id','home_team_id','away_team_id','tipoff_utc')})
    if p['fixture']!=expected:
        raise ValueError('MARKET_VIEW_FIXTURE_SCOPE_CONFLICT')
    if asof_utc<trace['prediction_utc']:
        raise ValueError('MARKET_VIEW_BEFORE_FORECAST')
    source=p['source'];captured=source['captured_at_utc'];manual=source['method']=='MANUAL_SCREENSHOT'
    reasons=[]
    if p['available_at_utc']>asof_utc:
        return dict(status='NOT_YET_AVAILABLE',observation_sha256=observation['sha256'],rows=[],
                    reasons=['SOURCE_NOT_AVAILABLE_AT_DECISION'],prediction_utc=trace['prediction_utc'],evaluated_at_utc=asof_utc)
    if manual:reasons.append('MANUAL_TRANSCRIPTION_NOT_INDEPENDENTLY_VERIFIED')
    if captured is None:reasons.append('SOURCE_CAPTURE_TIME_UNKNOWN')
    elif asof_utc-captured>POLICY['quote_max_age_seconds']:reasons.append('STALE_AT_DECISION_TIME')
    published=source['published_at_utc']
    published_fresh=(published is None or 0<=asof_utc-published<=POLICY['quote_max_age_seconds'])
    if not published_fresh:reasons.append('STALE_PUBLISHER_PRICE_AT_DECISION_TIME')
    if p['available_at_utc']>trace['prediction_utc']:
        reasons.append('SOURCE_AVAILABLE_AFTER_ORIGINAL_FORECAST')
    if asof_utc>=trace['tipoff_utc']:reasons.append('POST_TIPOFF_ARCHIVE_REVIEW_ONLY')
    rows=[]
    for q in p['quotes']:
        values=distribution.values(q['period'],q['market'])
        threshold=-q['line'] if q['market']=='HOME_HANDICAP' else q['line']
        raw=dict(under=float(np.mean(values<threshold)),push=float(np.mean(values==threshold)),over=float(np.mean(values>threshold)))
        tilt='BALANCED' if abs(raw['under']-raw['over'])<1e-12 else 'under' if raw['under']>raw['over'] else 'over'
        r=dict(q,conditional_regulation_probabilities=raw,conditional_direction=tilt,
            conditional_probability_is_contract_settlement=False,
            calibrated_probabilities=None,confidence_index=None,recommended_direction=None,
            expected_value=None,price_benchmarks=None,decision_status='SETTLEMENT_RULE_UNVERIFIED',reasons=list(reasons))
        eligible=(not manual and published_fresh and captured is not None and asof_utc-captured<=POLICY['quote_max_age_seconds'] and
                  asof_utc<trace['tipoff_utc'] and p['available_at_utc']<=trace['prediction_utc'])
        if native_quote is not None:
            native=native_quote.payload
            if (digest(native)!=native_quote.sha256 or native.get('native_quote_sha256')!=source.get('native_quote_sha256') or
                    any(native[k]!=q[k] for k in ('period','market','line','prices')) or
                    native['bookmaker_id']!=p['bookmaker']['id'] or
                    fixture_identity({k:native[k] for k in expected})!=expected):
                raise ValueError('MARKET_VIEW_NATIVE_PRICE_BINDING')
        if eligible and native_quote is not None and rule is not None:
            decision=evaluate_quote(distribution,native_quote,rule,asof_utc=asof_utc)
            r.update(decision_status=decision['status'],expected_value=decision['expected_value'],
                price_benchmarks=decision['price_benchmarks'],reasons=[*reasons,*decision['reasons']],
                contract_raw_probabilities=decision['raw_probabilities'],
                break_even_unconditional_win_probability=decision.get('break_even_unconditional_win_probability'),
                contract_scope=decision.get('settlement'))
        else:
            r['reasons'].append('SETTLEMENT_RULE_OR_FRESH_NATIVE_PRICE_NOT_VERIFIED')
        rows.append(r)
    return dict(status='RESEARCH_OBSERVATION_ONLY',observation_sha256=observation['sha256'],
        source=source,bookmaker=p['bookmaker'],prediction_utc=trace['prediction_utc'],
        evaluated_at_utc=asof_utc,available_at_utc=p['available_at_utc'],
        model_digest=trace['model_digest'],sample_count=len(distribution.paths),rows=rows,
        reasons=reasons,calibration_status='NOT_CALIBRATED',confidence_index=None,
        selection_enabled=False,forecast_changed=False)


def render(view):
    from telegram_delivery import tsi
    esc=html.escape
    if not view['rows']:
        return '<b>PİYASA GÖZLEMİ</b>\n'+esc(view['status'])+'\n'+esc(', '.join(view['reasons']))
    source=view['source'];manual=source['method']=='MANUAL_SCREENSHOT'
    label='MANUEL EKRAN AKTARIMI · ALANLAR BAĞIMSIZ DOĞRULANMADI' if manual else 'ARŞİVDEKİ NATIVE KAYNAK GÖZLEMİ'
    lines=['📈 <b>PİYASA GÖZLEMİ | HAM MODEL</b>',esc(view['bookmaker']['name'])+' · '+esc(source['provider_name']),
        label,'Yakalama (UTC): '+('bilinmiyor' if source['captured_at_utc'] is None else datetime.fromtimestamp(source['captured_at_utc'],timezone.utc).isoformat()),
        'Tahmin: '+tsi(view['prediction_utc'])+' · Karar/gösterim: '+tsi(view['evaluated_at_utc']),
        'Gözlemin erişilebilir olması: '+tsi(view['available_at_utc']),
        'Gözlem SHA: '+view['observation_sha256'][:16],
        'Ham normal süre olasılıkları; piyasa ödeme olasılığı ve güven yüzdesi değildir.']
    if source['url']:lines.append('Kaynak alan adı: '+esc(urlsplit(source['url']).hostname or ''))
    if source.get('event_clock_binding'):
        from hybrid_engine.provider_identity import clock_text
        lines.append('Kaynak saat bağı (aynı başlangıç saati iddiası değil): '+esc(clock_text(source['event_clock_binding'])))
    for row in view['rows']:
        kind=row['market'];p=row['conditional_regulation_probabilities']
        under,over=('DEP KARŞILAR','EV KARŞILAR') if kind=='HOME_HANDICAP' else ('DEP','EV') if kind=='WINNER' else ('ALT','ÜST')
        middle='NORMAL SÜRE EŞİTLİĞİ' if kind=='WINNER' else 'EŞİT SKOR KÜTLESİ'
        line=f"{row['line']:+g}" if kind=='HOME_HANDICAP' else f"{row['line']:g}"
        lines.extend(['',f"<b>{esc(row['period'])} · {esc(kind)} · {line}</b>",
            f"Ham normal süre: {under} %{100*p['under']:.1f} · {middle} %{100*p['push']:.1f} · {over} %{100*p['over']:.1f}",
            'Model eğilimi (öneri değil): '+('DENGELİ' if row['conditional_direction']=='BALANCED' else under if row['conditional_direction']=='under' else over)])
        if row['prices']:
            lines.append('Kaynakta görülen ondalık oranlar: '+', '.join((under if side=='under' else over)+f' {price:g}' for side,price in row['prices'].items()))
        else:lines.append('Oran: doğrulanamadı / sağlanmadı')
        if row['expected_value'] is not None:
            lines.append('Ham model EV (birim tutar, kalibre değil): '+esc(str(row['expected_value'])))
            if row.get('price_benchmarks'):
                thresholds=row['price_benchmarks']['break_even_conditional_on_no_push']
                lines.append('İade dışı koşullu başa baş: '+', '.join((under if side=='under' else over)+f" %{100*value:.1f}" for side,value in thresholds.items()))
            contract=row.get('contract_raw_probabilities')
            if contract:
                lines.append(f"Kuralı eşleşmiş ham piyasa: {under} %{100*contract['under']:.1f} · İADE %{100*contract['push']:.1f} · {over} %{100*contract['over']:.1f}")
        else:lines.append('EV / karşılaştırılabilir avantaj: hesaplanamadı')
        lines.append('Durum: '+esc(row['decision_status']))
        if row['reasons']:lines.append(esc(', '.join(row['reasons'])))
    lines.append(f"Örnek: {view['sample_count']} · NOT_CALIBRATED · Güven endeksi: yok · Seçim yapılmadı")
    lines.append('Yüzdeler ham örnek frekansıdır; örneklerde 0/100 gözlenmesi kesinlik anlamına gelmez.')
    return '\n'.join(lines)

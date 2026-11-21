"""Compact Turkish current-price research views; brands retain their identities."""
import html
from datetime import datetime,timezone
from urllib.parse import urlsplit

from hybrid_engine.market_turkish import period,market,message
from telegram_delivery import tsi


def render_batch(batch):
    p=batch['payload'];lines=['📈 <b>GÜNCEL PİYASA DEĞERLENDİRMESİ</b>',
        'İlk tahmin: '+tsi(p['prediction_utc']),
        'Bu değerlendirme: '+tsi(p['decision_utc']),
        'Kararın ilk kaydı: '+tsi(p['recorded_at_utc']),
        'Karar SHA: '+batch['sha256'][:16],
        'Kayıtlı tahmin korunuyor; güncel fiyatlar ayrı değerlendiriliyor.',
        'Ham normal süre olasılıkları, ödeme olasılığı ve güven endeksi farklıdır.']
    if p['record_class']=='POST_TIPOFF_REVIEW_ONLY':
        lines.append('Karar kaydı maç başlangıcından sonra tamamlandı; yeni maç öncesi karar sayılmaz.')
    groups={}
    for review in p['reviews']:
        key=(review['bookmaker']['id'],review['bookmaker']['name'],review['source']['provider_name'])
        groups.setdefault(key,[]).append(review)
    for (_,brand,provider),reviews in groups.items():
        first=reviews[0];lines.extend(['', '<b>Bahis platformu: '+html.escape(brand)+'</b>',
            'Oran sağlayıcısı: '+html.escape(provider),
            'Kaynak alan adı: '+html.escape(urlsplit(first['source']['url'] or '').hostname or 'doğrulanmadı'),
            'Yakalama (UTC): '+('bilinmiyor' if first['source']['captured_at_utc'] is None else
                datetime.fromtimestamp(first['source']['captured_at_utc'],timezone.utc).isoformat()),
            'Fiyatlara erişim: '+tsi(first['available_at_utc']),
            'Tahminin yaşı: '+str(first['forecast_age_seconds']//60)+' dk'])
        clock=first['source'].get('event_clock_binding')
        if clock:
            from hybrid_engine.provider_identity import clock_text
            lines.append(html.escape(clock_text(clock)))
        for review in reviews:
            for row in review['rows']:
                kind=row['market'];raw=row['conditional_regulation_probabilities']
                under,over=('DEP KARŞILAR','EV KARŞILAR') if kind=='HOME_HANDICAP' else ('DEP','EV') if kind=='WINNER' else ('ALT','ÜST')
                equal='Normal süre eşitliği' if kind=='WINNER' else 'Eşit skor'
                line=f"{row['line']:+g}" if kind=='HOME_HANDICAP' else f"{row['line']:g}"
                title=period(row['period'])+' · '+market(kind)+(' · '+line if kind!='WINNER' else '')
                lines.extend(['','<b>'+html.escape(title)+'</b>',
                    f"Ham normal süre: {under} %{100*raw['under']:.1f} · {equal} %{100*raw['push']:.1f} · {over} %{100*raw['over']:.1f}",
                    'Model eğilimi (öneri değil): '+('DENGELİ' if abs(raw['under']-raw['over'])<1e-12 else under if raw['under']>raw['over'] else over),
                    'Oranlar: '+(', '.join((under if s=='under' else over)+f' {v:g}' for s,v in row['prices'].items()) or 'doğrulanmadı')])
                bench=row['price_benchmarks']
                if bench:
                    lines.append('İade dışı koşullu başa baş: '+', '.join((under if s=='under' else over)+f' %{100*v:.1f}'
                        for s,v in bench['break_even_conditional_on_no_push'].items()))
                    if not bench['settlement_scope_verified']:lines.append('Başa baş yalnız oran matematiğidir; ödeme kuralı doğrulanmadı.')
                if row['expected_value'] is None:
                    lines.append('Beklenen getiri ve karşılaştırılabilir avantaj: hesaplanamadı')
                else:
                    mass=row['raw_contract_probabilities']
                    lines.append(f"Kuralı eşleşmiş ham ödeme: {under} %{100*mass['under']:.1f} · İADE %{100*mass['push']:.1f} · {over} %{100*mass['over']:.1f}")
                    lines.append('Ham model beklenen getirisi (1 birim tutar): '+', '.join(
                        (under if s=='under' else over)+f' {v:+.3f}' for s,v in row['expected_value'].items()))
                lines.append('Durum: '+html.escape(message(row['status'],technical=row['status']=='NO_EDGE')))
                reasons=[r for r in row['reasons'] if r not in ('NO_APPROVED_DISJOINT_CALIBRATION',row['status'])]
                for reason in reasons:lines.append(html.escape(message(reason)))
                lines.append('Gözlem SHA: '+review['observation_sha256'][:12])
    if any('LATER_PRICE_CURRENT_REVIEW' in r['information'] for review in p['reviews'] for r in review['rows']):
        lines.extend(['',message('LATER_PRICE_CURRENT_REVIEW')+'.'])
    samples={r['sample_count'] for r in p['reviews']}
    lines.extend(['','Örnek sayısı: '+', '.join(str(n) for n in sorted(samples)),
                  'Kalibrasyon doğrulanmadı (NOT_CALIBRATED) · Güven endeksi: yok',
                  'Yüzdeler ham örnek frekansıdır; 0/100 gözlenmesi kesinlik değildir.',
                  'Bahis seçimi veya önerisi yapılmadı. Bu kayıt ilk tahminin başarı hesabına katılmaz.'])
    return '\n'.join(lines)

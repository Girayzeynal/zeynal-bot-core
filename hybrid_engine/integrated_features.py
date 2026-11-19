"""Operational features and existing model publications, independent of promotion.

Only read loaded services / authenticated archives. Never fit, capture, settle,
query providers or treat a model acceptance gate as a functional on/off switch.
"""
import math
import time
from pathlib import Path

from core.team_identity import digest
from telegram_delivery import tsi

RELEASE='INTEGRATED_TEST_20261119'


def features(state):
    def loaded(key):return 'YÜKLÜ' if state.get(key) is not None else 'YAPILANDIRILMADI'
    lines=['ZEYNAL | ETKİN ÖZELLİKLER',RELEASE,
        'Bu liste model üstünlüğü kararından bağımsızdır.',
        'Ana analiz yönlendiricisi: '+loaded('verified_analysis_service'),
        'Avrupa analiz servisleri: '+(', '.join(sorted(state.get('europe_services',{}))) or 'YAPILANDIRILMADI'),
        'Tahmin listeleme: '+loaded('predictions_command'),
        'NBA otomatik PREMATCH: '+loaded('nba_overnight_scheduler'),
        'Avrupa otomatik PREMATCH: '+loaded('europe_prematch_scheduler'),
        'V2 güncel takım / box tempo adayları: '+loaded('adaptive_v2_worker'),
        'V3 rakip / form / korelasyonlu periyot adayı: '+loaded('issue90_research'),
        'Güncel değerlendirme / tam ortak yollar / ana analiz görünümü: '+loaded('current_assessments'),
        'Üç lig sonuç ve performans: /results all · /accuracy all',
        'Modellerin ayrı çıktıları: /models NBA MAÇ_KİMLİĞİ',
        'Kadro ve piyasa panelleri: doğrulanmış veri varsa kullanılır.',
        'Resmî kulüp kaynakları: isteğe bağlı pilot; oyuncu etkisi otomatik uygulanmaz.']
    review=state.get('europe_data_review')
    packet_store=state.get('verified_roster_packets')
    lines.extend([
        'Avrupa kadro kanıtı okuyucusu: '+('BAĞLI' if review is not None else 'BAĞLI DEĞİL'),
        'Maça ve ilk tahmin saatine doğrulanmış oyuncu paketi: otomatik sağlayıcı veri akışı henüz yok',
        'Maç bazlı sakatlık etkisi / sayısal dakika modeli: CANLI ANALİZE BAĞLI DEĞİL.',
        'Yerel oyuncu paket adayı sayısı: '+str(len(packet_store) if isinstance(packet_store,dict) else 0)+
        ' (sayı doğrulanmış oyuncu/maç kanıtı değildir).',
        'Kadro veri yokluğu hiçbir oyuncunun sağlıklı veya oynayabilir olduğunu kanıtlamaz.'])
    last=state.get('last_result_poll') or {}
    if last:
        lines.append('Son sonuç kontrolü: '+' · '.join(k+': '+v.get('status','BİLİNMİYOR') for k,v in last.items()))
    else:lines.append('Sonuç kolektörü: bu süreçte tamamlanmış kontrol henüz görülmedi.')
    worker=state.get('adaptive_v2_worker')
    if worker:
        last=getattr(worker,'last_report',None) or {}
        lines.append('Son V2 kontrolü: '+last.get('status','HENÜZ_ÇALIŞMADI'))
    study=state.get('issue90_research')
    if study:
        last=getattr(study,'last_report',None) or {}
        lines.append('Son V3 kontrolü: '+last.get('status','HENÜZ_ÇALIŞMADI'))
    lines.extend(['Model terfisi: ayrı ileriye dönük karşılaştırma bekler; yukarıdaki işlevleri kapatmaz.',
        'YÜKLÜ, verinin elde edildiği veya her maçta aday üretildiği anlamına gelmez.',
        'Çalışan sürüm/model: /test runtime · Gerçek saha performansı: /accuracy all'])
    return '\n'.join(lines)


def score(prediction):
    h=prediction['home'];a=prediction['away'];total=prediction['total']
    if any(type(v) not in (int,float) or not math.isfinite(v) or v<0 for v in (h,a,total)) or abs(h+a-total)>1e-8:
        raise ValueError('VISIBLE_MODEL_SCORE_ARITHMETIC')
    return f'{h:.2f} – {a:.2f} · Toplam {total:.2f}'


def models(state,league,fixture):
    if league not in ('NBA','EUROLEAGUE','EUROCUP') or not fixture or len(fixture)>128 or any(c.isspace() for c in fixture):
        raise ValueError('MODEL_VIEW_FIXTURE_REQUIRED')
    from hybrid_engine.unified_results_view import unwrap
    reader=state.get('ledger_reports')
    report=None if reader is None else unwrap(reader.read(league,fixture))
    rows=[] if report is None else report['forecasts']
    if report is not None and report.get('status')!='VERIFIED_LIVE_REPORT':
        raise ValueError('VISIBLE_VERIFIED_REPORT_REQUIRED')
    lines=['ZEYNAL | AYNI MAÇTA AYRI MODEL ÇIKTILARI',league+' · '+fixture,
        'Yeni tahmin veya eğitim çalıştırılmadı.']
    originals={}
    for r in rows:
        originals[r['fixture_id']]=r
        h,a=r['prediction']
        lines.append('Kayıtlı '+r['model_version']+': '+score(dict(home=h,away=a,total=h+a)))
    worker=state.get('adaptive_v2_worker')
    if worker:lines.append(worker.render(league,fixture))
    else:lines.append('V2: bu süreçte yapılandırılmadı.')
    study=state.get('issue90_research')
    if league=='NBA' and study and worker:
        from hybrid_engine.adaptive_research import read_wrapper
        from hybrid_engine.issue90_research import POLICY,pins
        plan_path=Path(study.root)/'plan.json'
        if not plan_path.is_file():lines.append('V3: ilk arka plan kontrolü / kayıtlı plan bekleniyor.')
        else:
            plan=read_wrapper(plan_path);p=plan['payload']
            if p['policy']!=POLICY or p['source_pins']!=pins() or not 0<p['registered_at_utc']<=int(time.time()):
                raise ValueError('VISIBLE_V3_CURRENT_PLAN_REQUIRED')
            # Reuse the existing version/admission/publication validator;
            # no plan(), tick(), fit(), capture() or source calls in this view.
            study.performance(worker.labels(),plan)
            found=False
            for entry in study.registry.records():
                q=entry['payload'];g=q['fixture'];original=originals.get(g['canonical_id'])
                if original is None:continue
                if q['original_snapshot_sha256']!=original['snapshot_sha256'] or q['original_model_digest']!=original['model_digest']:
                    raise ValueError('VISIBLE_V3_ORIGINAL_SNAPSHOT_CONFLICT')
                found=True
                lines.extend(['V3 ayrı PREMATCH: '+score(q['candidate']),
                    'V3 üretim: '+tsi(q['prediction_generated_at_utc']),
                    'V3 kayıt SHA: '+digest(q),
                    'Box-score tempo / rakip / güncel form / korelasyonlu periyot; kalibre edilmedi.'])
                if q.get('schedule_candidate'):lines.append('Ayrı takvim adayı: '+score(q['schedule_candidate']))
            if not found:
                last=getattr(study,'last_report',None) or {}
                lines.append('V3: bu maç için doğrulanmış ayrı yayın yok. Son kontrol: '+last.get('status','HENÜZ_ÇALIŞMADI'))
                lines.append('Eksik veri nedeni ve hazırlık: /test research')
    lines.append('Model karşılaştırması sürerken kayıtlı adaylar görüntülenebilir; güven yüzdesi veya otomatik terfi yapılmaz.')
    assessments=state.get('current_assessments')
    if assessments:
        current=assessments.render_rows(rows)
        if current:lines.append(current)
    return '\n'.join(lines)

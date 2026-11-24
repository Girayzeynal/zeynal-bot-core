"""Read-only two-clock presentation for an immutable first NBA forecast.

This module never trains, fetches a source, promotes a candidate, or edits the
original prediction. A later research candidate appears only with its native
publication clock; player and bookmaker inputs are NOT represented as applied.
"""
import asyncio
import html
import time
import logging

# A price-provider timeout must not consume the Telegram command's remaining
# wall-clock budget on a full authenticated V3 archive scan.
CURRENT_READ_DEADLINE_SECONDS=2.0

from telegram_delivery import tsi
from hybrid_engine.current_assessment import POLICY
from hybrid_engine.time_policy import MODEL_AGE_WARNING_SECONDS


def two_clock_text(context,assessments,*,now=None):
    when=int(time.time()) if now is None else now
    if type(when) is not int or not isinstance(context,dict):
        raise ValueError("DUAL_CLOCK_CONTEXT_REQUIRED")
    original=context.get("prediction")
    initial_time=context.get("prediction_generated_at_utc")
    base=['🔒 İLK TAHMİN — SADECE ARŞİV']
    if (isinstance(original,dict) and
            all(type(original.get(k)) in (int,float) for k in ("home","away","total")) and
            type(initial_time) is int):
        base.append(f"İlk skor: {original['home']:.2f} – {original['away']:.2f} · Toplam {original['total']:.2f}")
        base.append('İlk tahmin üretimi: '+tsi(initial_time))
    latest=assessments.latest(context)
    if latest is None:
        return '\n'.join([
            '⚠️ GÜNCEL MODEL SKORU HENÜZ YAYIMLANMADI',
            'Ana skor güncellenmedi; ilk tahmin canlı tahmin olarak kullanılamaz.',
            'Oyuncu ve piyasa gözlemleri tek başlarına güncel skor hesaplandığı anlamına gelmez.',
            '']+base)
    candidate=latest['candidate']
    age=when-latest['prediction_generated_at_utc']
    fresh=(0<=age<=POLICY['candidate_freshness_seconds'] and when<context['fixture_start_utc'] and
           0<=when-latest['parameter_fit_cutoff_utc']<=POLICY['maximum_model_age_seconds'])
    if not fresh:
        return '\n'.join([
            '⚠️ SON ARAŞTIRMA SKORU GÜNCEL DEĞİL (ARŞİV)',
            'Son değerlendirme üretimi: '+tsi(latest['prediction_generated_at_utc']),
            'Yeni saatli değerlendirme doğrulanmadan eski skor güncel olarak sunulmaz.',
            'Oyuncu ve piyasa gözlemleri ilk tahminin matematiğine uygulanmış sayılmaz.',
            '']+base)
    lines=['🧪 GÜNCEL AYRI ARAŞTIRMA SKORU — NORMAL SÜRE (ÖNCEKİ V3 KAYDINDAN)',
        f"Ev {candidate['home']:.2f} · Dep {candidate['away']:.2f} · Toplam {candidate['total']:.2f}",
        'V3 skorunun kaydedilmiş hesap zamanı: '+tsi(latest['prediction_generated_at_utc']),
        'Kayıttaki en geç kaynak kabul zamanı: '+tsi(latest['source_available_max_utc']),
        'Model eğitim kesiti: '+tsi(latest['parameter_fit_cutoff_utc']),
        'Bu /analyze komutunda yeni V3 skor hesaplanmadı; önceden kaydedilmiş aday okundu.',
        'Kaynak kabul zamanı, bütün kadro/haber/piyasa bilgilerinin canlı olarak yenilendiği anlamına gelmez.']
    if isinstance(original,dict) and type(original.get('total')) in (int,float):
        lines.append(f"İlk tahmine göre toplam fark: {candidate['total']-original['total']:+.2f} sayı")
    if when-latest['parameter_fit_cutoff_utc']>=MODEL_AGE_WARNING_SECONDS:
        lines.append('⚠️ Model eğitim kesiti 6 saatten eski; yeni kaynak yenilemesi/fit doğrulanmalı.')
    lines.extend([
        'Güncel tempo/verimlilik hesabıdır; doğrulanmış OUT/oyuncu dakikaları,',
        'takım haberleri ve piyasa fiyat hareketleri skor katsayısına DAHİL EDİLMEDİ.',
        'NOT_CALIBRATED · Gerçek zamanlı otomatik oyuncu etkisi henüz aktif değil.',
        '🔒 İlk V1 arşiv kaydı maç kimliği ve karşılaştırma için okundu; değiştirilmedi.'])
    return '\n'.join(lines+['']+base)



def current_panels(context, assessment, *, now):
    """Display one verified, time-scoped candidate across all numeric panels.

    The immutable original remains in Model / Kaynak; never splice its quarter
    paths or quantiles into a newer assessment. No network calls or fitting.
    """
    import math

    def unavailable(reason):
        warning=('⛔ <b>GÜNCEL ARAŞTIRMA PROJEKSİYONU YOK</b>\n'+
                 html.escape(reason)+'\nİlk V1 tahmininin sayıları ayrı 🗃 V1 İlk Tahmin — Arşiv düğmesindedir.')
        return dict(period=warning, ranges=warning, fresh=False, valid_until=None)

    if not isinstance(assessment, dict):
        return unavailable('CURRENT_ASSESSMENT_NOT_PUBLISHED')
    stamp=assessment.get('prediction_generated_at_utc')
    cutoff=assessment.get('parameter_fit_cutoff_utc')
    tip=context.get('fixture_start_utc')
    if any(type(v) is not int for v in (stamp, cutoff, tip)):
        return unavailable('CURRENT_ASSESSMENT_CLOCK_UNVERIFIED')
    if not (0 <= now-stamp <= POLICY['candidate_freshness_seconds'] and 0 <= now-cutoff <= POLICY['maximum_model_age_seconds'] and now < tip):
        return unavailable('CURRENT_ASSESSMENT_STALE_OR_STARTED')
    candidate=assessment.get('candidate') or {}
    quarters=candidate.get('quarters')
    halves=candidate.get('halves')
    def pair_valid(value):
        return (isinstance(value,(list,tuple)) and len(value)==2 and
                all(type(x) in (int,float) and math.isfinite(x) and x>=0 for x in value))
    if (not isinstance(quarters,(list,tuple)) or len(quarters)!=4 or
            not isinstance(halves,(list,tuple)) or len(halves)!=2 or
            not all(pair_valid(p) for p in [*quarters,*halves])):
        return unavailable('CURRENT_PERIOD_PATHS_NOT_VERIFIED')
    if (not all(type(candidate.get(k)) in (int,float) and math.isfinite(candidate[k])
                for k in ('home','away','total')) or
            any(abs(sum(quarters[i][side] for i in range(4))-candidate[name])>1e-4
                for side,name in ((0,'home'),(1,'away'))) or
            abs(candidate['home']+candidate['away']-candidate['total'])>1e-4 or
            any(abs(sum(quarters[i][side] for i in indices)-halves[j][side])>1e-4
                for j,indices in enumerate(((0,1),(2,3))) for side in (0,1))):
        return unavailable('CURRENT_PERIOD_SCORE_CONSERVATION_FAILED')
    intervals=assessment.get('intervals')
    if not isinstance(intervals,dict) or intervals.get('status')=='UNSUPPORTED':
        return unavailable('CURRENT_INTERVALS_NOT_VERIFIED')
    bands=intervals.get('markets',{})
    quantiles=('p05','p10','p25','p50','p75','p90','p95')
    required=('TOTAL','HOME','AWAY','MARGIN','1Q','2Q','3Q','4Q','1H','2H')
    if (not isinstance(bands,dict) or
            any(not isinstance(bands.get(k),dict) for k in required) or
            any(not all(type(bands[k].get(key)) in (int,float) and math.isfinite(bands[k][key])
                        for key in quantiles) or
                    any(bands[k][quantiles[i]]>bands[k][quantiles[i+1]]
                        for i in range(len(quantiles)-1)) for k in required)):
        return unavailable('CURRENT_DISTRIBUTION_NOT_VERIFIED')
    validity=min(stamp+POLICY['candidate_freshness_seconds'],cutoff+POLICY['maximum_model_age_seconds'],tip)
    source=('Hesap: '+tsi(stamp)+' · Model: '+html.escape(str(candidate.get('model','DOĞRULANMADI')))+
            '\nÖnceden kaydedilmiş V3 adayının tekrar gösterimi; bu komutta yeni hesap yok.'+
             '\nOyuncu etkisi uygulanmadı · NOT_CALIBRATED'+
             ('\n⚠️ Model eğitim kesiti 6 saatten eski; yeni kaynak/fit kontrol edilmeli.'
              if now-cutoff>=MODEL_AGE_WARNING_SECONDS else ''))
    lines=['📊 <b>GÜNCEL ADAY | PERİYOT VE SAYILAR</b>',source,'Ev – Deplasman · Normal süre']
    for label,values in [('1Q',quarters[0]),('2Q',quarters[1]),('1H',halves[0]),
                         ('3Q',quarters[2]),('4Q',quarters[3]),('2H',halves[1])]:
        h,a=values
        lines.extend(['',f'<b>{label}</b> {h:.2f} – {a:.2f} | Toplam {h+a:.2f}'])
        b=bands.get(label)
        if isinstance(b,dict) and all(type(b.get(k)) in (int,float) and math.isfinite(b[k])
                                       for k in ('p25','p75','p05','p95')):
            lines.append(f"P25–P75 {b['p25']:.1f}–{b['p75']:.1f} · P05–P95 {b['p05']:.1f}–{b['p95']:.1f}")
    lines.extend(['','<b>Maç toplamı:</b> '+f"{candidate['total']:.2f}",
                  'Rakamlar tek V3 aday kaydındandır; V1 periyotları kullanılmadı, bu istekte yeniden hesaplanmadı.'])
    labels=[('TOTAL','Maç toplamı'),('HOME','Ev toplamı'),('AWAY','Deplasman toplamı'),
            ('MARGIN','Ev farkı'),('1Q','1. çeyrek'),('2Q','2. çeyrek'),
            ('3Q','3. çeyrek'),('4Q','4. çeyrek'),('1H','İlk yarı'),('2H','İkinci yarı')]
    rng=['🎯 <b>GÜNCEL ADAY | SAYI ARALIKLARI</b>',source]
    for key,label in labels:
        b=bands.get(key)
        if not isinstance(b,dict) or not all(type(b.get(k)) in (int,float) and math.isfinite(b[k])
                                             for k in quantiles):
            continue
        rng.extend(['','<b>'+label+'</b>',
                    f"P50 {b['p50']:.1f} · P25–P75 {b['p25']:.1f}–{b['p75']:.1f}",
                    f"P10–P90 {b['p10']:.1f}–{b['p90']:.1f} · P05–P95 {b['p05']:.1f}–{b['p95']:.1f}"])
    rng.extend(['','Nominal simülasyon bantlarıdır; kalibre edilmiş güven olasılığı değildir.',
                'İlk tahminin aralıkları Model / Kaynak arşivindedir.'])
    return dict(period='\n'.join(lines),ranges='\n'.join(rng),
                fresh=True,valid_until=validity)



def bound_current_market_cards(context, assessment, entry, *, now):
    """Only previously evaluated, native, not-yet-expired prices for this exact candidate.

    Does not recalculate odds or invent prices; source evaluation and original
    forecast are independent. Any missing binding fails closed.
    """
    import math
    from core.team_identity import digest

    if not isinstance(assessment,dict) or not isinstance(entry,dict):
        return []
    snap=entry.get('research_market_snapshot')
    cards=entry.get('research_market_cards')
    if not isinstance(snap,dict) or not isinstance(cards,list):
        return []
    if (snap.get('current_assessment_sha256')!=digest(assessment) or
            snap.get('linked_original_snapshot_sha256')!=digest(context) or
            snap.get('fixture_id')!=context.get('fixture_id') or
            snap.get('fixture_start_utc')!=context.get('fixture_start_utc') or
            snap.get('prediction_generated_at_utc')!=assessment.get('prediction_generated_at_utc') or
            type(snap.get('model_digest')) is not str or not snap['model_digest']):
        return []
    q=assessment.get('candidate') or {}
    quarters=q.get('quarters')
    if not isinstance(quarters,(list,tuple)) or len(quarters)!=4:
        return []
    def expected(part,kind):
        if part=='FULL':pairs=quarters
        elif part=='1H':pairs=quarters[:2]
        elif part=='2H':pairs=quarters[2:]
        elif part in ('1Q','2Q','3Q','4Q'):pairs=[quarters[int(part[0])-1]]
        else:return None
        h=sum(p[0] for p in pairs)
        a=sum(p[1] for p in pairs)
        return {'TOTAL':h+a,'HOME':h,'AWAY':a,
                'HOME_HANDICAP':h-a,'WINNER':h-a}.get(kind)
    chosen=[]
    for card in cards[:128]:
        if not isinstance(card,dict):continue
        mean=card.get('mean');expect=expected(card.get('period'),card.get('market'))
        if (card.get('current') is not True or
            type(card.get('valid_until_utc')) is not int or
            now>=card['valid_until_utc'] or
            type(card.get('asof_utc')) is not int or card['asof_utc']>now or
            type(card.get('available_at_utc')) is not int or
            card['available_at_utc']>card['asof_utc'] or
            card.get('fixture_id')!=context.get('fixture_id') or
            card.get('tipoff_utc')!=context.get('fixture_start_utc') or
            card.get('model_digest')!=snap['model_digest'] or
            card.get('prediction_utc')!=assessment['prediction_generated_at_utc'] or
            type(mean) not in (int,float) or not math.isfinite(mean) or
            expect is None or abs(mean-expect)>1e-8 or
            not isinstance(card.get('prices'),dict) or not card['prices']):
            continue
        chosen.append(card)
    return chosen




def missing_current_market_card(assessment,entry,panels):
    """Price-free, verified V3 reference on an empty native quote binding.

    Model output is not a bookmaker line, a market quote, an estimated win
    probability, or a price-derived edge. Never display stale V3 numbers.
    """
    import math
    statuses={
        'PROVIDER_NOT_CONFIGURED':'Piyasa sağlayıcı adaptörü bu testte bağlı değil.',
        'KEY_NOT_AVAILABLE_IN_TEST_PROCESS':'The Odds API anahtarı bu test sürecinde yok.',
        'PROVIDER_REVIEW_PENDING':'Sağlayıcı denetimi henüz sonuçlanmadı.',
        'PROVIDER_REVIEW_UNAVAILABLE':'Sağlayıcı denetimi zamanında tamamlanamadı.',
        'PROVIDER_STATUS_UNAVAILABLE':'Sağlayıcı durum raporu alınamadı.',
        'LOCAL_DAILY_REQUEST_BUDGET':'Yerel günlük sağlayıcı istek bütçesi doldu.',
        'PROVIDER_QUOTA_EXHAUSTED':'Sağlayıcının istek kotası doldu.',
        'RATE_LIMITED':'Sağlayıcı istekleri hız sınırına takıldı.',
        'EXACT_FIXTURE_MATCH_REQUIRED':'Sağlayıcı maçı yerel fikstürle eşleştiremedi.',
        'LEAGUE_NOT_AVAILABLE_FROM_PROVIDER':'Sağlayıcı bu ligi etkin sunmuyor.',
        'NO_FRESH_SUPPORTED_PRICES':'Kaynakta geçerli desteklenen barem bulunamadı.',
        'OBSERVED_RULES_AND_CALIBRATION_PENDING':'Kaynak gözlemi var ama aynı V3 adayıyla fiyat ve ödeme kuralı birlikte doğrulanmadı.',
        'PROVIDER_REVIEW_ALREADY_RUNNING':'Başka bir sağlayıcı denetimi çalışıyor.',
        'LOCAL_EVIDENCE_STORAGE_FULL':'Yerel sağlayıcı kanıt alanı dolmuş.',
        'POST_TIPOFF_NO_CURRENT_API_BACKFILL':'Maç başladı; maç öncesi fiyat sorgulanamaz.',
    }
    source=entry.get('research_market_source_status')
    if not isinstance(source,str) or len(source)>100 or not source.replace('_','').isalnum():
        source='PROVIDER_STATUS_UNAVAILABLE'
    lines=[
        '⛔ <b>GÜNCEL ADAYLA EŞLEŞMİŞ PİYASA HESABI YOK</b>',
        'Doğrulanmış ve süresi dolmamış bahis şirketi baremi/oranı mevcut V3 adayıyla eşleştirilmedi.',
        '<b>Sağlayıcı denetimi:</b> '+html.escape(source),
        html.escape(statuses.get(source,'Sağlayıcı verisi uygunluk koşullarını karşılamadı; ayrıntı Model / Kaynak panelinde.')),
    ]
    if panels.get('fresh') is True and isinstance(assessment,dict):
        q=assessment.get('candidate') or {}
        quarters=q.get('quarters')
        values=(q.get('home'),q.get('away'),q.get('total'))
        if (type(quarters) in (list,tuple) and len(quarters)==4 and
                all(type(v) in (int,float) and math.isfinite(v) for v in values) and
                all(type(p) in (list,tuple) and len(p)==2 and
                    all(type(v) in (int,float) and math.isfinite(v) for v in p) for p in quarters)):
            home,away,total=values
            h1=sum(float(p[0])+float(p[1]) for p in quarters[:2])
            h2=sum(float(p[0])+float(p[1]) for p in quarters[2:])
            lines.extend([
                '',
                '📊 <b>V3 MODEL REFERANSI — BAHİS BAREMİ DEĞİLDİR</b>',
                f'Model maç toplamı: {total:.2f} sayı',
                f'Model takım toplamları: Ev {home:.2f} · Deplasman {away:.2f}',
                f'Model ev farkı: {home-away:+.2f} sayı',
                f'Model 1H / 2H toplamı: {h1:.2f} / {h2:.2f} sayı',
                'Bu değerler kaydedilmiş V3 simülasyonunun ortalamalarıdır; oran, bahis çizgisi, üst/alt önerisi veya beklenen getiri değildir.',
            ])
    else:
        lines.extend(['','Güncel doğrulanmış V3 sayı paketi yok; eski V1/V3 skorları piyasa referansı olarak kullanılmadı.'])
    lines.extend(['','İlk V1 piyasa kayıtları ayrı V1 İlk Tahmin — Arşiv düğmesindedir.',
                  'NOT_CALIBRATED · Kaynak oranı ve ödeme kapsamı doğrulanmadan bahis avantajı/güven yüzdesi hesaplanmaz.'])
    return '\n'.join(lines)



def bound_audit_provenance(audit, assessment, panels):
    """Label original-model evidence separately from a later research candidate.

    Read-only UI annotation: no prediction/ledger/source rewrite and no claim
    of independent candidate calibration, player model, or verified bookmaker edge.
    """
    from core.team_identity import digest

    if not isinstance(audit,str):
        audit=''
    first_card='🛡 <b>TAHMİN SAĞLIK KARTI</b>'
    first_model='<b>MODEL DENETİMİ</b>'
    if first_card in audit:
        audit=audit.replace(first_card, first_card+
            '\n<i>KAPSAM: İLK KAYITLI V1 TAHMİNİ. '
            'Aşağıdaki geçmiş sonuç sayısı, MAE, simülasyon ve kaynak değerleri '
            'ayrı güncel araştırma adayının performansı değildir.</i>',1)
    if first_model in audit:
        audit=audit.replace(first_model,first_model+
            '\n<i>İLK KAYITLI TAHMİNİN kaynak/model denetimi (V1); '
            'güncel adayla karıştırılmamalıdır.</i>',1)
    if panels.get('fresh') and isinstance(assessment,dict):
        candidate=assessment.get('candidate') or {}
        stamp=assessment.get('prediction_generated_at_utc')
        cutoff=assessment.get('parameter_fit_cutoff_utc')
        source=assessment.get('source_available_max_utc')
        status=('🧪 <b>AYRI GÜNCEL ARAŞTIRMA ADAYI — '
                'MODEL/KAYNAK AYRIMI</b>\n'+
                'Aday model: '+html.escape(str(candidate.get('model','KİMLİK_YOK')))+'\n'+
                'Aday kayıt SHA: '+digest(assessment)[:16]+'\n'+
                'Skor üretimi: '+(tsi(stamp) if type(stamp) is int else 'BİLİNMİYOR')+'\n'+
                'Veri üst zamanı: '+(tsi(source) if type(source) is int else 'BİLİNMİYOR')+'\n'+
                'Model eğitim kesiti: '+(tsi(cutoff) if type(cutoff) is int else 'BİLİNMİYOR')+'\n'+
                'NOT_CALIBRATED · Güncel aday için bağımsız doğrulanmış '
                'güven/MAE veya oyuncu etkisi kanıtı yok.\n'
                'İlk V1 sağlık kartı bu adaya taşınmadı.\n'
                'KÖKEN: V3 tahmini kendi doğrulanmış aday arşivinden okundu. '
                'V1 kaydı maç kimliği/orijinal SHA bağı ve karşılaştırma içindir; '
                'V1 skor ve periyot değerleri V3 skoru olarak kopyalanmadı.\n'
                'Bu Telegram isteğinde V3 skoru yeniden hesaplanmadı.')
    else:
        status=('⛔ <b>GÜNCEL ARAŞTIRMA ADAYI DENETİMİ YOK</b>\n'
                'İlk V1 sağlık kartı güncel adayın hesabı veya güveni değildir.')
    if first_model in audit:
        audit=audit.replace(first_model,status+'\n\n'+first_model,1)
    else:
        audit+='\n\n'+status
    return audit



def install_dual_clock_display(state,assessments):
    """Supersede the original display wrapper without changing model source pins."""
    base=state['verified_analysis_service']
    class Display:
        ledger=getattr(base,'ledger',None)
        def __init__(self):self.base=base
        async def analyze(self,league,*args):
            response=await base.analyze(league,*args)
            if response.get('status')!='ANALYSIS_OK':return response
            context=response.get('snapshot');entry=None
            keyboard=response.get('reply_markup')
            if keyboard:
                try:
                    token=keyboard.inline_keyboard[0][0].callback_data.split(':')[1]
                    entry=state.get('premium_reports',{}).get(token)
                    if context is None and entry:context=entry.get('europe_context')
                except (AttributeError,IndexError,TypeError,KeyError):
                    pass
            if context is None:return response
            # /analyze must not run slow model fits. The serial research
            # cycle publishes its own verified candidates independently.
            # A failed/missing read is a visible blocker, never a fallback V1
            # score represented as current.
            selected=None
            update_issue=None
            try:
                # Use the same authenticated SHA+receipt+asset checks, but
                # only inspect this fixture's two recent hourly publication
                # slots. Existing test doubles keep the historical interface.
                read_recent=getattr(assessments,'latest_display',None)
                lookup=read_recent if callable(read_recent) else assessments.latest
                selected=await asyncio.wait_for(
                    asyncio.to_thread(lookup,context),
                    timeout=CURRENT_READ_DEADLINE_SECONDS)
                from types import SimpleNamespace
                content=two_clock_text(context,SimpleNamespace(latest=lambda _:selected),
                                       now=int(time.time()))
            # Before Python 3.11 asyncio.TimeoutError is NOT the built-in
            # TimeoutError. UserLAnd can run Python 3.10; catch both explicitly.
            except (ValueError,KeyError,TypeError,OSError,asyncio.TimeoutError,TimeoutError) as exc:
                logging.getLogger(__name__).warning(
                    'Current V3 read unavailable after bounded lookup: %s',
                    type(exc).__name__)
                update_issue=('CURRENT_READ_TIMEOUT' if isinstance(exc,(asyncio.TimeoutError,TimeoutError)) else
                              'CURRENT_RESEARCH_RECORD_UNAVAILABLE')
                content=('⚠️ GÜNCEL TAHMİN DOĞRULANAMADI. '
                         'Eski kayıt arşivde korundu; güncel skor yayımlanmıyor.')
            if selected is None and context.get('league')=='NBA':
                update_issue=update_issue or 'CURRENT_RESEARCH_BACKGROUND_PENDING'
            if update_issue:
                content='Güncel model hesap engeli: '+update_issue+'\n'+content
            # Publish a headline only when the full score/period/interval set
            # is from one fresh candidate, rather than mixed first-record rows.
            panels=None
            if entry and context.get('league')=='NBA':
                panels=current_panels(context,selected,now=int(time.time()))
                if not panels['fresh']:
                    # Queue this fixture for the next serial background cycle.
                    # No fit/source fetch or unbounded wait inside /analyze.
                    cycle=state.get('research_cycle')
                    request=getattr(cycle,'request_fixture',None)
                    if callable(request):
                        try:request(context)
                        except (ValueError,KeyError,TypeError,RuntimeError):pass
                content=content.partition('\n🔒 İLK TAHMİN — SADECE ARŞİV')[0]
                if not panels['fresh'] and 'GÜNCEL AYRI ARAŞTIRMA SKORU' in content:
                    content=('⚠️ GÜNCEL MODEL SAYISAL PAKETİ DOĞRULANMADI. '
                             'Özet, periyotlar ve aralıklar aynı kayıtla doğrulanmadan '
                             'güncel skor yayımlanmıyor.\n'+panels['period'])
            prefix=html.escape(content)+'\n\n'
            result=dict(response);parts=list(response.get('html_parts') or [response['html']])
            if entry and context.get('league')=='NBA':
                # The entire first-score card moves to Model / Kaynak, not
                # the main headline. Never present replayed V1 as latest.
                old=entry.get('summary','')
                from hybrid_engine.elite_render import split_blocks
                is_current='GÜNCEL AYRI ARAŞTIRMA SKORU' in content
                heading=('🏀 ZEYNAL | GÜNCEL NBA TAHMİNİ — KAYITLI V3, YENİ HESAP DEĞİL' if is_current else
                         '🏀 ZEYNAL | GÜNCEL TAHMİN BEKLENİYOR')
                headline=('<b>'+heading+'</b>\n'+
                    html.escape(str(context['home']['official_name']))+' 🆚 '+
                    html.escape(str(context['away']['official_name']))+'\n\n'+
                    prefix)
                original_period=entry['sections'].get('period','')
                original_ranges=entry['sections'].get('ranges','')
                original_market=entry['sections'].get('market','')
                entry['summary']=headline
                audit=bound_audit_provenance(entry['sections'].get('audit',''),selected,panels)
                # Model / Kaynak holds model provenance and V1 health evidence,
                # not all V1 numeric pages. The numerical first forecast is
                # explicitly navigable under its own archive button.
                entry['sections']['audit']=(audit+
                    '\n\n🗃 <b>İLK V1 SKORU, PERİYOTLARI VE ARALIKLARI</b>\n'
                    'Ayrı V1 İlk Tahmin — Arşiv düğmesindedir. '
                    'Bu V1 değerleri güncel V3 skoru değildir.')
                entry['section_pages']['audit']=split_blocks(entry['sections']['audit'].splitlines(),limit=3200)
                archive_blocks=[
                    '<b>V1 İLK TAHMİN — DEĞİŞMEZ ARŞİV | SKOR</b>\n'+old,
                    '<b>V1 İLK TAHMİN — DEĞİŞMEZ ARŞİV | PERİYOTLAR</b>\n'+original_period,
                    '<b>V1 İLK TAHMİN — DEĞİŞMEZ ARŞİV | ARALIKLAR</b>\n'+original_ranges,
                    '<b>V1 İLK TAHMİN — DEĞİŞMEZ ARŞİV | PİYASA</b>\n'+original_market]
                entry['sections']['archive']='\n\n'.join(archive_blocks)
                entry['section_pages']['archive']=[
                    page for block in archive_blocks
                    for page in split_blocks(block.splitlines(),limit=3200)]
                for section in ('period','ranges'):
                    body=panels[section]
                    if not panels['fresh']:
                        # Keep V3 absence explicit, but restore the readable
                        # first-record figures as a clearly labelled V1 ARCHIVE.
                        # This is NOT a fresh V3 score or an inferred update.
                        original={'period':original_period,'ranges':original_ranges}[section]
                        if isinstance(original,str) and original.strip():
                            body+=('\n\n🗃 <b>İLK V1 TAHMİNİ — ARŞİV, GÜNCEL DEĞİL</b>\n'
                                   'Aşağıdaki ilk tahmin rakamları yalnız geçmiş kayıt içindir. '
                                   'Güncel V3 skoru, oyuncu katkısı veya yeni bahis değerlendirmesi değildir.\n\n'
                                   +original)
                    entry['sections'][section]=body
                    entry['section_pages'][section]=split_blocks(body.splitlines(),limit=3200)
                # The first-model quotes belong in audit. Show separate
                # research-model reviews ONLY if their verified model+clock
                # identity matches this candidate and the native quote is live.
                matching=(bound_current_market_cards(context,selected,entry,now=int(time.time()))
                          if panels['fresh'] else [])
                if matching:
                    from hybrid_engine.market_direction_ui import render as market_render,order as market_order
                    ranked=market_order(matching)[:32]
                    header=('📈 <b>V3 ARAŞTIRMA ADAYI | ZAMAN DAMGALI FİYAT GÖZLEMİ</b>\n'
                            'Aday SHA/model ve yerel piyasa erişim zamanı eşleşti; '
                            'skor bu fiyatlarla yeniden hesaplanmadı.\n'
                            'Ham NORMAL SÜRE simülasyonu · NOT_CALIBRATED · Güven endeksi yok.\n'
                            'Bahis şirketinin uzatma ve ödeme kuralları doğrulanmadı; '
                            'ham yüzde bahis kazanma olasılığı veya bahis avantajı değildir.\n'
                            'Sağlayıcı maç başlangıç saati farklıysa saat uyuşmazlığı ayrıca denetlenmelidir.\n'
                            'İlk V1 piyasa kayıtları ayrı V1 İlk Tahmin — Arşiv düğmesindedir.')
                    market_pages=[header+'\n\n'+market_render(card) for card in ranked]
                    entry['section_pages']['market']=market_pages
                    entry['sections']['market']='\n\n'.join(market_pages)
                    entry['quote_valid_until_utc']=min(card['valid_until_utc'] for card in ranked)
                else:
                    entry['sections']['market']=missing_current_market_card(selected,entry,panels)
                    entry['section_pages']['market']=[entry['sections']['market']]
                    entry['quote_valid_until_utc']=None  # Old quote is archive-only.
                entry['current_assessment_valid_until_utc']=panels['valid_until']
                entry['current_assessment_panels']=panels['fresh']
                # Persist the FINAL bound render, not the earlier first-model
                # page cached by the inner presenter. This is render-only data.
                try:
                    from hybrid_engine.telegram_premium_ui import cache_report
                    cache_report(state.get('premium_reports',{}),token,entry)
                except (OSError,ValueError,TypeError):
                    pass  # Telegram must still deliver its in-memory report.
                from hybrid_engine.telegram_premium_ui import keyboard as premium_keyboard
                result['reply_markup']=premium_keyboard(token,include_archive=True)
                parts=[headline]
            elif len((prefix+parts[0]).encode('utf-16-le'))//2<=3500:
                parts[0]=prefix+parts[0]
            else:parts.insert(0,prefix)
            result['html_parts']=parts;result['html']=parts[0]
            return result
    state['verified_analysis_service']=Display()

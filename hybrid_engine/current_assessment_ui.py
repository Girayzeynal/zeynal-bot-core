"""Read-only two-clock presentation for an immutable first NBA forecast.

This module never trains, fetches a source, promotes a candidate, or edits the
original prediction. A later research candidate appears only with its native
publication clock; player and bookmaker inputs are NOT represented as applied.
"""
import asyncio
import html
import time

from telegram_delivery import tsi


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
    fresh=(0<=age<=3600 and when<context['fixture_start_utc'] and
           0<=when-latest['parameter_fit_cutoff_utc']<=21600)
    if not fresh:
        return '\n'.join([
            '⚠️ SON ARAŞTIRMA SKORU GÜNCEL DEĞİL (ARŞİV)',
            'Son değerlendirme üretimi: '+tsi(latest['prediction_generated_at_utc']),
            'Yeni saatli değerlendirme doğrulanmadan eski skor güncel olarak sunulmaz.',
            'Oyuncu ve piyasa gözlemleri ilk tahminin matematiğine uygulanmış sayılmaz.',
            '']+base)
    lines=['🧪 GÜNCEL AYRI ARAŞTIRMA SKORU — NORMAL SÜRE',
        f"Ev {candidate['home']:.2f} · Dep {candidate['away']:.2f} · Toplam {candidate['total']:.2f}",
        'Yeni hesaplama: '+tsi(latest['prediction_generated_at_utc']),
        'Kullanılan veri üst zamanı: '+tsi(latest['source_available_max_utc']),
        'Model eğitim kesiti: '+tsi(latest['parameter_fit_cutoff_utc'])]
    if isinstance(original,dict) and type(original.get('total')) in (int,float):
        lines.append(f"İlk tahmine göre toplam fark: {candidate['total']-original['total']:+.2f} sayı")
    lines.extend([
        'Güncel tempo/verimlilik hesabıdır; doğrulanmış OUT/oyuncu dakikaları,',
        'takım haberleri ve piyasa fiyat hareketleri skor katsayısına DAHİL EDİLMEDİ.',
        'NOT_CALIBRATED · Gerçek zamanlı otomatik oyuncu etkisi henüz aktif değil.',
        '🔒 İlk tahmin arşivi değiştirilmedi.'])
    return '\n'.join(lines+['']+base)



def current_panels(context, assessment, *, now):
    """Display one verified, time-scoped candidate across all numeric panels.

    The immutable original remains in Model / Kaynak; never splice its quarter
    paths or quantiles into a newer assessment. No network calls or fitting.
    """
    import math

    def unavailable(reason):
        warning=('⛔ <b>GÜNCEL ARAŞTIRMA PROJEKSİYONU YOK</b>\n'+
                 html.escape(reason)+'\nİlk kaydın değerleri Model / Kaynak arşivindedir.')
        return dict(period=warning, ranges=warning, fresh=False, valid_until=None)

    if not isinstance(assessment, dict):
        return unavailable('CURRENT_ASSESSMENT_NOT_PUBLISHED')
    stamp=assessment.get('prediction_generated_at_utc')
    cutoff=assessment.get('parameter_fit_cutoff_utc')
    tip=context.get('fixture_start_utc')
    if any(type(v) is not int for v in (stamp, cutoff, tip)):
        return unavailable('CURRENT_ASSESSMENT_CLOCK_UNVERIFIED')
    if not (0 <= now-stamp <= 3600 and 0 <= now-cutoff <= 21600 and now < tip):
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
    validity=min(stamp+3600,cutoff+21600,tip)
    source=('Hesap: '+tsi(stamp)+' · Model: '+html.escape(str(candidate.get('model','DOĞRULANMADI')))+
            '\nGüncel araştırma adayı · Oyuncu etkisi uygulanmadı · NOT_CALIBRATED')
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
                  'Rakamlar tek bir güncel aday kaydındandır; ilk tahminin periyotları değildir.'])
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
            # The background cycle is not the user's /analyze freshness
            # guarantee. Calculate for this exact fixture if no fresh candidate
            # is available; this does not retrain the immutable first model.
            update_issue=None
            if context.get('league')=='NBA' and callable(getattr(assessments,'refresh_fixture',None)):
                try:
                    await asyncio.wait_for(
                        asyncio.to_thread(assessments.refresh_fixture,context),timeout=32)
                except (ValueError,KeyError,TypeError,OSError,RuntimeError,TimeoutError) as exc:
                    import logging
                    from hybrid_engine.data import Abstain
                    logging.getLogger(__name__).warning('Current fixture update unavailable: %s',type(exc).__name__)
                    reason=str(exc)
                    if (isinstance(exc,Abstain) and reason.startswith('CURRENT_') and
                            reason.replace('_','').isalnum() and len(reason)<=100):
                        update_issue=reason
                    elif isinstance(exc,TimeoutError):
                        update_issue='CURRENT_UPDATE_TIMEOUT'
                    else:
                        update_issue='CURRENT_UPDATE_OR_SOURCE_UNAVAILABLE'
            selected=None
            try:
                selected=await asyncio.wait_for(
                    asyncio.to_thread(assessments.latest,context),timeout=10)
                from types import SimpleNamespace
                content=two_clock_text(context,SimpleNamespace(latest=lambda _:selected),
                                       now=int(time.time()))
            except (ValueError,KeyError,TypeError,OSError,TimeoutError):
                content=('⚠️ GÜNCEL TAHMİN DOĞRULANAMADI. İlk kayıt arşivde korundu; '
                         'oyuncu ve piyasa etkileri uygulanmış sayılmaz.')
            if update_issue and 'GÜNCEL AYRI ARAŞTIRMA SKORU' not in content:
                content='Güncel model hesap engeli: '+update_issue+'\n'+content
            # Publish a headline only when the full score/period/interval set
            # is from one fresh candidate, rather than mixed first-record rows.
            panels=None
            if entry and context.get('league')=='NBA':
                panels=current_panels(context,selected,now=int(time.time()))
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
                heading=('🏀 ZEYNAL | GÜNCEL NBA TAHMİNİ' if is_current else
                         '🏀 ZEYNAL | GÜNCEL TAHMİN BEKLENİYOR')
                headline=('<b>'+heading+'</b>\n'+
                    html.escape(str(context['home']['official_name']))+' 🆚 '+
                    html.escape(str(context['away']['official_name']))+'\n\n'+
                    prefix)
                original_period=entry['sections'].get('period','')
                original_ranges=entry['sections'].get('ranges','')
                original_market=entry['sections'].get('market','')
                entry['summary']=headline
                audit=entry['sections'].get('audit','')
                entry['sections']['audit']=('<b>İLK TAHMİN — DEĞİŞMEZ ARŞİV</b>\n'+
                    old+'\n\n<b>İLK TAHMİN PERİYOTLARI — ARŞİV</b>\n'+original_period+
                    '\n\n<b>İLK TAHMİN ARALIKLARI — ARŞİV</b>\n'+original_ranges+
                    '\n\n<b>ÖNCEKİ PİYASA GÖRÜNÜMÜ — ARŞİV</b>\n'+original_market+
                    '\n\n'+audit)
                entry['section_pages']['audit']=split_blocks(entry['sections']['audit'].splitlines(),limit=3200)
                for section in ('period','ranges'):
                    entry['sections'][section]=panels[section]
                    entry['section_pages'][section]=split_blocks(panels[section].splitlines(),limit=3200)
                # Existing market odds were assessed against the first model.
                # A later candidate must not inherit those prices or its edge.
                entry['sections']['market']=(
                    '⛔ <b>GÜNCEL ADAYLA EŞLEŞMİŞ PİYASA HESABI YOK</b>\n'
                    'İlk tahminin piyasa değerlendirmesi Model / Kaynak arşivine taşındı.\n'
                    'Yeni adayın dağılımına bağlı güncel fiyat ve edge doğrulanmadı.')
                entry['section_pages']['market']=[entry['sections']['market']]
                entry['quote_valid_until_utc']=None  # Old quote is archive-only.
                entry['current_assessment_valid_until_utc']=panels['valid_until']
                entry['current_assessment_panels']=panels['fresh']
                parts=[headline]
            elif len((prefix+parts[0]).encode('utf-16-le'))//2<=3500:
                parts[0]=prefix+parts[0]
            else:parts.insert(0,prefix)
            result['html_parts']=parts;result['html']=parts[0]
            return result
    state['verified_analysis_service']=Display()

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
            if context.get('league')=='NBA' and callable(getattr(assessments,'refresh_fixture',None)):
                try:
                    await asyncio.wait_for(
                        asyncio.to_thread(assessments.refresh_fixture,context),timeout=32)
                except (ValueError,KeyError,TypeError,OSError,RuntimeError,TimeoutError) as exc:
                    import logging
                    logging.getLogger(__name__).warning('Current fixture update unavailable: %s',type(exc).__name__)
            try:
                content=await asyncio.wait_for(
                    asyncio.to_thread(two_clock_text,context,assessments),timeout=10)
            except (ValueError,KeyError,TypeError,OSError,TimeoutError):
                content=('⚠️ GÜNCEL TAHMİN DOĞRULANAMADI. İlk kayıt arşivde korundu; '
                         'oyuncu ve piyasa etkileri uygulanmış sayılmaz.')
            prefix=html.escape(content)+'\n\n'
            result=dict(response);parts=list(response.get('html_parts') or [response['html']])
            if entry and context.get('league')=='NBA':
                # The entire first-score card moves to Model / Kaynak, not
                # the main headline. Never present replayed V1 as latest.
                old=entry.get('summary','')
                from hybrid_engine.elite_render import split_blocks
                headline=('<b>🏀 ZEYNAL | GÜNCEL NBA TAHMİNİ</b>\n'+
                    html.escape(str(context['home']['official_name']))+' 🆚 '+
                    html.escape(str(context['away']['official_name']))+'\n\n'+
                    prefix)
                entry['summary']=headline
                audit=entry['sections'].get('audit','')
                entry['sections']['audit']=('<b>İLK TAHMİN — DEĞİŞMEZ ARŞİV</b>\n'+
                    old+'\n\n'+audit)
                entry['section_pages']['audit']=split_blocks(entry['sections']['audit'].splitlines(),limit=3200)
                parts=[headline]
            elif len((prefix+parts[0]).encode('utf-16-le'))//2<=3500:
                parts[0]=prefix+parts[0]
            else:parts.insert(0,prefix)
            result['html_parts']=parts;result['html']=parts[0]
            return result
    state['verified_analysis_service']=Display()

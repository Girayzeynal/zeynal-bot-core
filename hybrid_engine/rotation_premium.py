"""Opt-in presentation of the verified NBA rotation receipt, not model promotion."""
import asyncio
import html
import logging
import re
from pathlib import Path
import time

from core.team_identity import digest
from hybrid_engine.rotation_report import records
from hybrid_engine.time_policy import PREMATCH_MINIMUM_LEAD_SECONDS
from hybrid_engine.elite_render import split_blocks
from hybrid_engine.isolated_execution import optional_source_thread
from hybrid_engine.telegram_premium_ui import cache_report
from telegram_delivery import tsi

LABELS=(('1Q','1. çeyrek'),('2Q','2. çeyrek'),('3Q','3. çeyrek'),('4Q','4. çeyrek'),
        ('1H','İlk yarı'),('2H','İkinci yarı'),('FULL','Maç'))
READ_TIMEOUT_SECONDS=15

def lookup(root,ledger,snapshot,now):
    entries,_,_=records(root,ledger,now=now,selector=snapshot['fixture_id'])
    bound=[e for e in entries if e[4]['fixture_id']==snapshot['fixture_id']
        and e[4]['snapshot_sha256']==digest(snapshot)
        and e[3]['original_snapshot_sha256']==digest(snapshot)
        and e[3]['fixture_start_utc']==snapshot['fixture_start_utc']]
    return bound[0] if len(bound)==1 else None

def lookup_refresh(root,ledger,snapshot,raw,now):
    # Refresh replay needs every earlier settled raw receipt, not just the
    # requested fixture. Only consider an existing separately published file.
    if not any(Path(root).glob('refresh-score-*.json')):return None
    from hybrid_engine.rotation_refresh import review
    entries,_,_=records(root,ledger,now=now)
    result=review(root,entries,now)
    choices=[e for seq in result['entries'].values() for e in seq
        if e[4][2]==raw[2] and e[4][4]['fixture_id']==snapshot['fixture_id']
        and e[3]['original_snapshot_sha256']==digest(snapshot)]
    return max(choices,key=lambda e:e[:3]) if choices else None

def number(v):
    return f'{v:.2f}'.replace('.',',')

def panels(snapshot,receipt,now):
    g,_,pin,p,row=receipt
    tip=snapshot['fixture_start_utc']
    if (row['fixture_id']!=snapshot['fixture_id'] or row['snapshot_sha256']!=digest(snapshot)
        or p['fixture_id']!=snapshot['fixture_id'] or p['original_snapshot_sha256']!=digest(snapshot)
        or p['fixture_start_utc']!=tip or p['generated_at_utc']!=g or not g<=now<tip-PREMATCH_MINIMUM_LEAD_SECONDS
        or p['production_enabled'] or p['forecast_changed'] or p['calibrated']):
        raise ValueError('ROTATION_UI_IDENTITY_OR_CLOCK')
    sim=p['simulation'];markets=sim['markets'];full=markets['FULL']
    home=html.escape(snapshot['home']['official_name']);away=html.escape(snapshot['away']['official_name'])
    stamp='Kayıtlı rotasyon araştırması · '+tsi(g)+'\nYeni canlı hesap değil · Kalibre edilmedi.'
    def band(v):
        return f"Nominal %80 {v['p10']:.0f}–{v['p90']:.0f} · %90 {v['p05']:.0f}–{v['p95']:.0f}"
    summary='\n'.join([f'🏀 <b>{home} – {away}</b>','NBA · '+tsi(tip)+' · Normal süre','',
        f"Ev {number(full['home']['mean'])}   ·   Deplasman {number(full['away']['mean'])}",
        f"<b>Beklenen toplam  {number(full['total']['mean'])}</b>",band(full['total']),'',stamp,
        'Geçmiş oyuncu rotasyonu ve tempo/verimlilik etkisi dahil.',
        'Güncel sakatlık ve kesin ilk beş teyitli değil.',
        'Piyasa · Bu rotasyonla eşleşmiş doğrulanmış karar yok.',
        'Yön öncelikli öğrenme · ortak sayı düzeltmesi kapalı.',
        'Önceki modelin piyasa gözlemleri ayrı Piyasa düğmesinde.'])
    period=['📊 <b>Periyot tahminleri</b>','Ev – Deplasman · Toplam sayı','Normal süre','']
    ranges=[]
    for key,label in LABELS:
        m=markets[key]
        period.append(f"{label}   {number(m['home']['mean'])} – {number(m['away']['mean'])}   ·   {number(m['total']['mean'])}")
        if key in ('4Q','2H'):period.append('')
        lines=[f'🎯 <b>Sayı aralıkları · {label}</b>','Normal süre · Ham simülasyon','']
        for kind,name in (('total','Toplam'),('home','Ev sahibi'),('away','Deplasman'),('margin','Ev farkı')):
            v=m[kind]
            lines.extend([f"<b>{name}</b> · Ortalama {number(v['mean'])}",band(v),''])
        ranges.append('\n'.join(lines+[stamp,'Gerçek kapsama doğrulanmadı.']))
    period.extend(['',stamp])
    market='\n'.join(['📈 <b>ROTASYON MODELİ / PİYASA</b>',
        'Bu araştırma kaydıyla eşleştirilmiş doğrulanmış barem/oran yok; Alt/Üst veya avantaj hesabı yapılmadı.',
        f"Maç toplamı {number(full['total']['mean'])} · Ev {number(full['home']['mean'])} · Dep {number(full['away']['mean'])}",
        f"Model ev farkı {number(full['margin']['mean'])} · İlk yarı {number(markets['1H']['total']['mean'])}",
        'Model referansı bahis baremi değildir. Oyuncu özel tahmini üretilmedi.'])
    audit='\n'.join(['🛡 <b>ROTASYON ARAŞTIRMASI — MODEL / KAYNAK</b>',stamp,
        f"{sim['scenarios']} senaryo · {p['residual_games']} geçmiş hata kaydı",
        'Geçmiş oyuncu dakika dağılımı vekili; gerçek maç kadrosu veya çeyrek dakikaları değildir.',
        'Eski modelin merkezlenmiş hata dağılımı aktarıldı; bağımsız olasılık kalibrasyonu kanıtlanmadı.',
        'İlk tahmin ve önceki V3 raporları ayrı arşiv/kaynak sayfalarında korunur.',
        'Kayıt SHA: '+html.escape(pin)])
    return dict(summary=summary,period='\n'.join(period),ranges=ranges,market=market,audit=audit)

def refresh_view(snapshot,raw,refresh,now):
    g,mtime,pin,p,t=refresh
    if (t[2]!=raw[2] or p['raw_receipt_sha256']!=raw[2]
        or p['original_snapshot_sha256']!=digest(snapshot)
        or p['fixture_id']!=snapshot['fixture_id']
        or p['fixture_start_utc']!=snapshot['fixture_start_utc']
        or p['generated_at_utc']!=g or not raw[0]<=g<=mtime<=now
        or now>=snapshot['fixture_start_utc']-PREMATCH_MINIMUM_LEAD_SECONDS
        or p['calibrated'] or p['production_enabled'] or p['forecast_changed']):
        raise ValueError('ROTATION_UI_REFRESH_BINDING')
    m=p['simulation']['markets'];b=raw[3]['simulation']['markets'];f=m['FULL']
    screen=p['screen']['status']
    status={'INSUFFICIENT_CHRONOLOGICAL_EVIDENCE':'İleriye dönük başarı henüz kanıtlanmadı',
        'REJECT_REGRESSION':'Regresyon denetimi reddetti',
        'REJECT_NO_TOTAL_IMPROVEMENT':'Toplam hata iyileşmesi kanıtlanmadı',
        'RESEARCH_SCREEN_PASS':'Araştırma elemesi geçti; üretim onayı değil'}.get(screen,'Araştırma denetimi doğrulanmadı')
    stamp='Gölge aday · '+tsi(g)+f" · {p['prior_n']} doğrulanmış sonuç"
    headline='\n'.join(['🧪 <b>SONUÇ SONRASI GÖLGE ADAY</b>',
        f"Ev {number(f['home']['mean'])} · Dep {number(f['away']['mean'])}",
        f"<b>Toplam {number(f['total']['mean'])}</b> · İlk rotasyon {number(b['FULL']['total']['mean'])}",
        stamp,status+'. Kalibre edilmedi. İlk tahmin korunuyor.'])
    period=['🧪 <b>Öğrenme sonrası karşılaştırma</b>',stamp,
        'İlk rotasyon → Gölge aday · Ev – Dep. | Toplam']
    ranges=[]
    for k,label in LABELS:
        v=m[k];r=b[k]
        period.extend([f'<b>{label}</b>',
            f"{number(r['home']['mean'])} – {number(r['away']['mean'])} | {number(r['total']['mean'])}",
            f"→ {number(v['home']['mean'])} – {number(v['away']['mean'])} | {number(v['total']['mean'])}"])
        lines=[f'🎯 <b>Gölge aday · {label}</b>',stamp,'Normal süre · Kalibre edilmedi']
        for side,name in (('total','Toplam'),('home','Ev sahibi'),('away','Deplasman'),('margin','Ev farkı')):
            q=v[side]
            lines.extend([f"<b>{name}</b> · {number(q['mean'])}",
                f"Nominal %80 {q['p10']:.0f}–{q['p90']:.0f} · %90 {q['p05']:.0f}–{q['p95']:.0f}"])
        ranges.append('\n'.join(lines+['Aktarılan hata dağılımı; kapsama kanıtı yok.']))
    market='\n'.join(['🧪 <b>Gölge aday — model referansı</b>',
        f"Maç {number(f['total']['mean'])} · İlk yarı {number(m['1H']['total']['mean'])}",
        'Yeni adayla eşleşmiş ödeme kapsamı ve fiyat hesabı yok. Eski V3 olasılıkları bu adayın olasılığı değildir.'])
    audit='\n'.join(['🧪 <b>Sonuç sonrası aday kanıtı</b>',stamp,status,
        f"Senaryo: {p['simulation']['scenarios']} · Kalibre edilmedi · Üretim değişmedi",
        'Aday SHA: '+html.escape(pin),'Ham rotasyon SHA: '+html.escape(raw[2])])
    return dict(summary=headline,period='\n'.join(period),ranges=ranges,market=market,audit=audit)

def unique_market_pages(pages):
    # Keep the first occurrence of each observation/decision pair; the
    # original source pages still exist in the immutable archive and audit.
    seen=set();out=[]
    for page in pages:
        observations=re.findall(r'Gözlem SHA:\s*([0-9a-f]{8,64})',page)
        decisions=re.findall(r'Karar SHA:\s*([0-9a-f]{8,64})',page)
        keys={(o,tuple(decisions)) for o in observations}
        key=' '.join(page.split())
        if key in seen or (keys and keys<=seen):continue
        seen.add(key);seen.update(keys)
        out.append(page)
    return out

def present(response,cache,receipt,now,refresh=None):
    snapshot=response['snapshot']
    keyboard=response['reply_markup']
    token=keyboard.inline_keyboard[0][0].callback_data.split(':')[1]
    old=cache[token]
    if 'archive' not in old['sections']:raise ValueError('ROTATION_UI_ORIGINAL_ARCHIVE_REQUIRED')
    view=panels(snapshot,receipt,now)
    entry=dict(old,sections=dict(old['sections']),section_pages=dict(old['section_pages']))
    # Retired numerical candidates are visible only in /rotation refresh.
    shadow=None
    if shadow:view['summary']+='\n\n'+shadow['summary']
    entry['summary']=view['summary']
    def set_pages(key,pages):
        entry['sections'][key]='\n\n'.join(pages)
        entry['section_pages'][key]=pages
    def previous(key):
        value=old['section_pages'].get(key) or split_blocks(old['sections'].get(key,'').splitlines(),limit=3000)
        label='<b>BAĞIMSIZ ÖNCEKİ MODEL RAPORU — ROTASYONLA EŞLEŞMEDİ</b>\n'
        return [page for v in value for page in split_blocks((label+v).splitlines(),limit=3200)]
    set_pages('period',[shadow['period'],view['period']] if shadow else [view['period']])
    set_pages('ranges',shadow['ranges']+view['ranges'] if shadow else view['ranges'])
    market_pages=unique_market_pages(previous('market'))
    set_pages('market',[view['market']+('\n\n'+shadow['market'] if shadow else ''),*market_pages])
    prior=['<b>ÖNCEKİ MODEL ÖZETİ — ROTASYON DEĞİL</b>\n'+old['summary']]
    prior.extend(previous('period'));prior.extend(previous('ranges'))
    set_pages('audit',[view['audit']+('\n\n'+shadow['audit'] if shadow else ''),*previous('audit'),*[
        page for v in prior for page in split_blocks(v.splitlines(),limit=3200)]])
    # Preserve original archive and independent roster context/pages exactly.
    # Existing market and roster source callbacks remain original-model views.
    entry['current_assessment_panels']=True
    entry['current_assessment_valid_until_utc']=snapshot['fixture_start_utc']-PREMATCH_MINIMUM_LEAD_SECONDS
    entry['rotation_research_receipt_sha256']=receipt[2]
    if shadow:entry['rotation_refresh_receipt_sha256']=refresh[2]
    # The old Iddaa model reference must not be attributed to rotation.
    entry['iddaa_first_half_total']=None
    result=dict(response,html=view['summary'],html_parts=[view['summary']],compact_candidate_summary=True)
    cache_report(cache,token,entry)
    return result

def install(state,root,ledger):
    base=state['verified_analysis_service']
    class Display:
        ledger=getattr(base,'ledger',None)
        async def analyze(self,league,*args):
            result=await base.analyze(league,*args)
            if league.upper()!='NBA' or result.get('status')!='ANALYSIS_OK':return result
            snapshot=result.get('snapshot')
            if not isinstance(snapshot,dict) or not result.get('reply_markup'):return result
            now=int(time.time())
            if now>=snapshot['fixture_start_utc']-PREMATCH_MINIMUM_LEAD_SECONDS:return result
            try:
                receipt=await asyncio.wait_for(optional_source_thread(lookup,root,ledger,snapshot,now),timeout=READ_TIMEOUT_SECONDS)
                if receipt is None:return result
                return present(result,state['premium_reports'],receipt,int(time.time()))
            except Exception as exc:
                logging.getLogger(__name__).warning('Rotation premium view unavailable: %s',type(exc).__name__)
                return result
    state['verified_analysis_service']=Display()

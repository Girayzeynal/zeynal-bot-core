"""Opt-in presentation of the verified NBA rotation receipt, not model promotion."""
import asyncio
import html
import logging
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
        'Piyasa · Doğrulanmış maç toplamı baremi yok.',
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

def present(response,cache,receipt,now):
    snapshot=response['snapshot']
    keyboard=response['reply_markup']
    token=keyboard.inline_keyboard[0][0].callback_data.split(':')[1]
    old=cache[token]
    if 'archive' not in old['sections']:raise ValueError('ROTATION_UI_ORIGINAL_ARCHIVE_REQUIRED')
    view=panels(snapshot,receipt,now)
    entry=dict(old,sections=dict(old['sections']),section_pages=dict(old['section_pages']))
    entry['summary']=view['summary']
    def set_pages(key,pages):
        entry['sections'][key]='\n\n'.join(pages)
        entry['section_pages'][key]=pages
    def previous(key):
        value=old['section_pages'].get(key) or split_blocks(old['sections'].get(key,'').splitlines(),limit=3000)
        label='<b>BAĞIMSIZ ÖNCEKİ MODEL RAPORU — ROTASYONLA EŞLEŞMEDİ</b>\n'
        return [page for v in value for page in split_blocks((label+v).splitlines(),limit=3200)]
    set_pages('period',[view['period']])
    set_pages('ranges',view['ranges'])
    set_pages('market',[view['market'],*previous('market')])
    prior=['<b>ÖNCEKİ MODEL ÖZETİ — ROTASYON DEĞİL</b>\n'+old['summary']]
    prior.extend(previous('period'));prior.extend(previous('ranges'))
    set_pages('audit',[view['audit'],*previous('audit'),*[
        page for v in prior for page in split_blocks(v.splitlines(),limit=3200)]])
    # Preserve original archive and independent roster context/pages exactly.
    # Existing market and roster source callbacks remain original-model views.
    entry['current_assessment_panels']=True
    entry['current_assessment_valid_until_utc']=snapshot['fixture_start_utc']-PREMATCH_MINIMUM_LEAD_SECONDS
    entry['rotation_research_receipt_sha256']=receipt[2]
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

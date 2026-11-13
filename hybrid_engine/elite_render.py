"""Telegram HTML blocks for the isolated research bot; bounded UTF-16 messages."""
import html
from telegram_delivery import tsi


def units(text):return len(text.encode('utf-16-le'))//2


def split_blocks(blocks,limit=3200):
    parts=[];current=''
    for block in blocks:
        if units(block)>limit:raise ValueError('ELITE_BLOCK_LENGTH_BUDGET')
        candidate=current+'\n\n'+block if current else block
        if units(candidate)>limit:
            parts.append(current);current=block
        else:current=candidate
    if current:parts.append(current)
    return parts


def render_elite(record,forecast,bands,confidence,*,live=False,prediction=None):
    g=record['fixture'];p=prediction or forecast.summary();esc=lambda s:html.escape(str(s)[:220])
    pair=lambda v:f'{v[0]:.2f} – {v[1]:.2f}'
    label='İzole araştırma | Gerçek maç öncesi tahmin' if live else 'Dondurulmuş tahminin tekrarı'
    probability='\nKazanma olasılıkları: kalibrasyon doğrulanmadı; gösterilmiyor.'
    if live and p.get('winner') is not None:
        probability='\nHam model olasılığı (kalibre edilmedi): Ev %{:.1f} | Eşitlik %{:.1f} | Dep %{:.1f}'.format(*(100*x for x in p['winner']))
        probability+='\nBu olay olasılıkları güven endeksi değildir.'
    blocks=['<b>ZEYNAL BOT CORE | ELITE HYBRID PRO</b>\n🏀 '+esc(record.get('league','EuroLeague'))+'\n'+esc(g['home_name'])+' – '+esc(g['away_name'])+'\n'+tsi(g['start_ts_utc'])+
        '\n<b>'+label+'</b> | Normal süre; uzatma hariç',
        '<b>SKOR PROJEKSİYONU</b>\nEv / deplasman: '+pair([p['home'],p['away']])+f"\nToplam: {p['total']:.2f}\nFark (ev): {p['margin']:+.2f}"+
        probability]
    if bands['status']!='UNSUPPORTED':
        q=bands['markets']['TOTAL'];text='<b>TAHMİN ARALIKLARI</b>'
        for label,market in [('Maç toplamı','TOTAL'),('Ev toplamı','HOME'),('Deplasman toplamı','AWAY'),('Maç farkı','MARGIN'),('Model ev handikabı','HOME_HANDICAP')]:
            v=bands['markets'][market]
            text+=f"\n{label}: P50 {v['p50']:.1f}\nDar P25–P75: {v['p25']:.1f}–{v['p75']:.1f} | Risk P05–P95: {v['p05']:.1f}–{v['p95']:.1f}"
        text+=f"\nDetay P10–P90 (maç toplamı): {q['p10']:.1f}–{q['p90']:.1f}"
        text+='\nAralıklar ham model dağılımındandır; gerçekleşen kapsama veya güven garantisi değildir.';blocks.append(text)
    else:blocks.append('<b>TAHMİN ARALIKLARI</b>\nGerçek örnek yolu yok; aralık üretilmedi.')
    period='<b>PERİYOT ANALİZİ</b>'
    for label,score in [(str(i+1)+'Q',q) for i,q in enumerate(p['quarters'])]+[(str(i+1)+'H',h) for i,h in enumerate(p['halves'])]:
        period+=f'\n{label}: '+pair(score)+f' | Toplam {sum(score):.2f}'
        b=bands.get('markets',{}).get(label)
        if b:period+=f"\nP25–P75 {b['p25']:.1f}–{b['p75']:.1f} | P05–P95 {b['p05']:.1f}–{b['p95']:.1f}"
    blocks.append(period)
    blocks.append('<b>PİYASA KARŞILAŞTIRMASI</b>\nPiyasa verisi doğrulanamadı.\nToplam, takım toplamı ve handikap için çizgi/edge/alt–üst yönü üretilmedi.')
    audit='<b>MODEL DENETİMİ</b>\nGüven endeksi: '+('hesaplanamadı' if confidence['value'] is None else str(confidence['value'])+' / 100')
    audit+='\nKalibrasyon: doğrulanmadı.\nKadro, sakatlık, rotasyon ve gerçek tempo doğrulanmadı.'
    audit+=f"\nYöntem: {esc(forecast.metadata['method'])} | Gerçek örnek: {bands['scenarios']:,}\nSeed: {forecast.metadata['seed']}\nModel: {esc(forecast.model)}"
    audit+='\nSHA: '+record['models']['BAYES_QMC']['model_digest'][:12]+'\nKaynak: '+esc(record['official_source'])
    audit+='\nVeri zamanı: '+tsi(record['source_data_time_utc'])+'\nİlk snapshot: '+tsi(record['created_at_utc'])
    if live:audit+='\nTahmin üretimi: '+tsi(record['prediction_generated_at_utc'])+'\nParametre eğitimi istek sırasında çalıştırılmadı.'
    else:
        audit+='\nAyrı üretim/arşiv bitiş saatleri eski kayıtta yok; geriye dönük doldurulmadı.'
        audit+='\nPREMATCH tahmini değildir: yeni üretim değil, kayıt/girdi tekrarıdır.'
    audit+='\nEnsemble doğrulanmadı; gösterilen bileşen Bayesian/QMC.'
    blocks.append(audit)
    return split_blocks(blocks)

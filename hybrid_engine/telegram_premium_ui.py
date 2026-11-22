"""Compact, source-preserving Telegram presentation for the isolated test bot."""
import html
import json
import re
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
from telegram_delivery import tsi

def direction_card_matches_snapshot(snapshot,card):
    """A newer research market assessment cannot be attributed to first forecast.

    This guards presentation only. Cards may be examined separately with their
    own model/clock pins, but never attached as a current original-model call.
    """
    if not isinstance(snapshot,dict) or not isinstance(card,dict) or card.get('current') is not True:
        return False
    try:
        p=snapshot['prediction']
        mean=card['mean']
        return (card['fixture_id']==snapshot['fixture_id'] and
            card['model_digest']==snapshot['model_digest'] and
            card['prediction_utc']==snapshot['prediction_generated_at_utc'] and
            card['tipoff_utc']==snapshot['fixture_start_utc'] and
            card['period']=='FULL' and card['market']=='TOTAL' and
            type(mean) in (int,float) and type(p['total']) in (int,float) and
            abs(mean-p['total'])<=1e-8)
    except (KeyError,TypeError,ValueError,OverflowError):
        return False


def compact_summary(snapshot,evidence,*,replayed,health=None,market_note=None,direction_card=None,league='NBA'):
    if league not in ('NBA','EUROLEAGUE','EUROCUP'):raise ValueError('SUMMARY_LEAGUE_REQUIRED')
    minutes=48 if league=='NBA' else 40
    p=snapshot['prediction'];esc=html.escape
    start=datetime.fromtimestamp(snapshot['fixture_start_utc'],ZoneInfo('Europe/Istanbul')).strftime('%d.%m.%Y %H:%M')
    lines=[f'🏀 <b>ZEYNAL | {league} ANALİZ</b>',
        '<b>'+esc(str(snapshot['home']['official_name']))+'</b> 🆚 <b>'+esc(str(snapshot['away']['official_name']))+'</b>',
        start+f' TSİ · Normal süre ({minutes} dk)','',
        '📊 <b>İLK KAYITLI SKOR PROJEKSİYONU</b>',
        f'Ev <b>{p["home"]:.1f}</b> · Dep <b>{p["away"]:.1f}</b>',
        f'Toplam <b>{p["total"]:.1f}</b> · Ev farkı {p["margin"]:+.1f}','']
    if direction_card is not None and direction_card.get('current'):
        c=direction_card
        if (c['fixture_id']!=snapshot.get('fixture_id') or c['model_digest']!=snapshot.get('model_digest') or
            c['prediction_utc']!=snapshot.get('prediction_generated_at_utc') or
            c['tipoff_utc']!=snapshot['fixture_start_utc'] or c['period']!='FULL' or
            c['market']!='TOTAL' or abs(c['mean']-p['total'])>1e-8):
            raise ValueError('SUMMARY_DIRECTION_FIXTURE_OR_MODEL_CONFLICT')
        from hybrid_engine.market_direction_ui import brief
        lines.extend([brief(c),'Gösterilen barem: '+esc(c['bookmaker']['name'])+' · diğerleri Piyasa düğmesinde',
                      'Fiyata erişim: '+tsi(c['available_at_utc'])])
    else:lines.append('📈 Güncel doğrulanmış barem yok; piyasa ayrıntıları butonda.')
    q=snapshot.get('intervals',{}).get('markets',{}).get('TOTAL')
    if q:
        lines.extend(['','📊 <b>TOPLAM SAYI ARALIKLARI</b>',
            f"P25–P75 {q['p25']:.1f}–{q['p75']:.1f}",
            f"P05–P95 {q['p05']:.1f}–{q['p95']:.1f}",
            'Ham model aralıkları; geçmiş kapsama doğrulanmadı.'])
    lines.extend(['','NOT_CALIBRATED · Güven endeksi: yok',
        '🔒 '+('Kayıtlı tahmin tekrar gösterildi.' if replayed else 'Yeni tahmin arşivlendi.'),
        'Üretim: '+tsi(snapshot.get('prediction_generated_at_utc')),
        '<i>İzole araştırma · Üretim değil</i>'])
    return '\n'.join(lines)

def keyboard(token,*,section=None,page=0,pages=1):
    from telegram import InlineKeyboardButton,InlineKeyboardMarkup
    rows=[
        [InlineKeyboardButton('📊 Periyotlar',callback_data='zui:'+token+':period'),
         InlineKeyboardButton('🎯 Aralıklar',callback_data='zui:'+token+':ranges')],
        [InlineKeyboardButton('📈 Piyasa',callback_data='zui:'+token+':market'),
         InlineKeyboardButton('🛡 Model / Kaynak',callback_data='zui:'+token+':audit')],
        [InlineKeyboardButton('🏥 Kadro / Sakatlık',callback_data='zui:'+token+':roster')],
        [InlineKeyboardButton('🏠 Özet',callback_data='zui:'+token+':summary')]]
    if pages>1 and section is not None:
        nav=[]
        if page>0:nav.append(InlineKeyboardButton('‹ Önceki',callback_data=f'zui:{token}:{section}:{page-1}'))
        nav.append(InlineKeyboardButton(f'{page+1}/{pages}',callback_data=f'zui:{token}:{section}:{page}'))
        if page+1<pages:nav.append(InlineKeyboardButton('Sonraki ›',callback_data=f'zui:{token}:{section}:{page+1}'))
        rows.insert(0,nav)
    return InlineKeyboardMarkup(rows)

def cache_report(cache,token,entry,*,max_bytes=8*1024*1024,max_count=64):
    def size(e):
        return (len(e['summary'].encode())+sum(len(s.encode()) for s in e.get('sections',{}).values())+
            sum(len(p.encode()) for values in e.get('section_pages',{}).values() for p in values)+
            (len(json.dumps(e['roster_context']).encode()) if e.get('roster_context') is not None else 0)+
            len(e.get('original_roster_html','').encode()))
    needed=size(entry)
    if needed>max_bytes:raise ValueError('PREMIUM_REPORT_CACHE_BUDGET')
    while cache and (len(cache)>=max_count or sum(size(e) for e in cache.values())+needed>max_bytes):
        cache.pop(next(iter(cache)))
    cache[token]=entry

def page_view(entry,section,page,*,now):
    from hybrid_engine.elite_render import split_blocks
    body=entry['summary'] if section=='summary' else entry['sections'][section]
    values=([body] if section=='summary' else entry.get('section_pages',{}).get(section)) or split_blocks(body.splitlines(),limit=3200)
    if type(page) is not int or not 0<=page<len(values):raise ValueError('PREMIUM_PAGE_NOT_FOUND')
    text=values[page]
    if section=='roster' and entry.get('roster_review_at_utc') is not None:
        if entry.get('tipoff_utc') is not None and now>=entry['tipoff_utc']:
            text='Maç başladı; aşağıdaki kadro bilgisi arşiv gözlemidir.\n\n'+text
        elif now>=entry.get('roster_valid_until_utc',entry['roster_review_at_utc']+300):
            text='Kadro gözlemi eskidi; güncel sayılmaz. Kadro / Sakatlık düğmesiyle kontrol edin.\n\n'+text
    if section in ('summary','market'):
        if entry.get('tipoff_utc') is not None and now>=entry['tipoff_utc']:
            text='Maç başladı; yalnız arşiv görünümü.\n\n'+text
        elif entry.get('quote_valid_until_utc') is not None and now>entry['quote_valid_until_utc']:
            text='Arşiv görünümü; piyasa fiyatları yeniden sorgulanmadı.\n\n'+text
    return text,len(values)

def period_table(section_html):
    """Telegram-friendly rows; all numbers originate in the frozen model output."""
    raw=html.unescape(re.sub(r'<[^>]+>', '', section_html))
    rows={}
    pattern=r'^(1Q|2Q|3Q|4Q|1H|2H):\s*([0-9.]+)\s*[–-]\s*([0-9.]+)\s*\|\s*Toplam\s*([0-9.]+)'
    current=None
    for line in raw.splitlines():
        match=re.match(pattern,line.strip())
        if match:
            current=match.group(1)
            rows[current]={'home':float(match.group(2)), 'away':float(match.group(3)),
                           'total':float(match.group(4)), 'band':None}
        elif current and line.strip().startswith('P25'):
            rows[current]['band']=line.strip()
    if not all(k in rows for k in ('1Q','2Q','3Q','4Q','1H','2H')):
        return section_html
    qtotals=[rows[f'{i}Q']['total'] for i in range(1,5)]
    mean=sum(qtotals)/4
    def tempo(total):
        # Relative projected scoring only, NOT measured possessions or pace.
        if total>mean*1.05:return 'Görece yüksek'
        if total<mean*0.95:return 'Görece düşük'
        return 'Orta'
    lines=['📊 <b>PERİYOT | SKOR PROJEKSİYONU</b>',
           '<i>Skor sırası: Ev – Deplasman · Normal süre</i>',
           '<i>Etiketler tahmini sayı toplamlarını karşılaştırır; ölçülmüş oyun temposu değildir.</i>','']
    labels=[('1Q','1. Çeyrek'),('2Q','2. Çeyrek'),('1H','İlk Yarı'),
            ('3Q','3. Çeyrek'),('4Q','4. Çeyrek'),('2H','İkinci Yarı')]
    for key,label in labels:
        row=rows[key]
        score=f"{row['home']:.1f} – {row['away']:.1f}"
        lines.append(f'<b>{label}</b>  |  {score}')
        lines.append(f"Toplam: {row['total']:.1f}"+
                     (f' · {tempo(row["total"])}' if key.endswith('Q') else ''))
        if row['band']:lines.append(html.escape(row['band']))
        lines.append('')
    home=sum(rows[f'{i}Q']['home'] for i in range(1,5))
    away=sum(rows[f'{i}Q']['away'] for i in range(1,5))
    lines.append(f'<b>MAÇ SONU PROJEKSİYONU</b>  |  {home:.1f} – {away:.1f}')
    lines.append(f'Toplam: {home+away:.1f} · Fark (ev): {home-away:+.1f}')
    # Quantitative commentary is derived only from the already-rendered frozen rows.
    # Never turn this into a player/roster or market assertion without source evidence.
    first_half=rows['1H']['total']
    second_half=rows['2H']['total']
    leader='Ev' if home>away else 'Deplasman' if away>home else 'Eşit'
    lines.extend(['', '📝 <b>MODEL NOTLARI</b>',
                  f'• Skor projeksiyonunda önde: {leader} (fark: {abs(home-away):.1f} sayı).',
                  f'• İlk yarı: {first_half:.1f} · İkinci yarı: {second_half:.1f}.',
                  ('• İkinci yarı toplamı ilk yarıdan yüksek öngörülüyor.'
                   if second_half>first_half else
                   '• İkinci yarı toplamı ilk yarıdan düşük öngörülüyor.'
                   if second_half<first_half else
                   '• İki yarının sayı toplamı eşit öngörülüyor.'),
                  '• Oyuncu, sakatlık, gerçek pozisyon temposu ve piyasa üstünlüğü: doğrulanmadı.',
                  '⚠️ En güçlü barem ve güven yüzdesi doğrulanmadı; eklenmedi.'])
    return '\n'.join(lines)

def roster_section(evidence=None):
    """Display only fixture-scoped, timestamp-gated availability evidence."""
    lines=['🏥 <b>KADRO / SAKATLIK | KAYNAK DENETİMİ</b>']
    if evidence is None or not evidence.get('records'):
        lines.append('Maça ve tahmin saatine bağlanmış doğrulanabilir oyuncu durum kaydı yok.')
    else:
        for record in evidence['records'][:20]:
            lines.append('• '+html.escape(str(record['team_id']))+' / '+
                         html.escape(str(record['player_id']))+': <b>'+
                         html.escape(str(record['status']))+'</b>')
            lines.append('  Kaynak: '+html.escape(str(record['source_url'])))
            lines.append('  Yayın (UTC): '+datetime.fromtimestamp(record['published_at_utc'], timezone.utc).strftime('%Y-%m-%d %H:%M'))
        lines.append('Bu durumlar ilk beş veya dakika tahmini değildir.')
    lines.append('⚠️ İlk beş, rotasyon ve oyuncu etkisi doğrulanmadı; modele uygulanmadı.')
    return '\n'.join(lines)

def detail_sections(parts, market_html, roster_evidence=None):
    # Existing renderer is the canonical source for detailed data.
    full='\n\n'.join(parts)
    def section(title, next_title):
        start=full.find('<b>'+title+'</b>')
        if start<0:return '<b>Veri bulunamadı</b>'
        end=full.find('<b>'+next_title+'</b>',start+len(title)+7)
        return full[start:end].strip() if end>=0 else full[start:].strip()
    return {
        'period':period_table(section('PERİYOT ANALİZİ','PİYASA KARŞILAŞTIRMASI')),
        'ranges':section('TAHMİN ARALIKLARI','PERİYOT ANALİZİ'),
        'market':market_html,
        'roster':roster_section(roster_evidence),
        'audit':section('MODEL DENETİMİ','__END__'),
    }

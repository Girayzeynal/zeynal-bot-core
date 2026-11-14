"""Compact Telegram presentation for isolated research forecasts.

Presentation only: no mutation of frozen snapshots, market observations or model.
"""
import html
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

def compact_summary(snapshot, evidence, *, replayed):
    p=snapshot['prediction']
    fixture={'home_name':snapshot['home']['official_name'], 'away_name':snapshot['away']['official_name']}
    esc=html.escape
    start=datetime.fromtimestamp(snapshot['fixture_start_utc'],timezone.utc).astimezone(
        ZoneInfo('Europe/Istanbul')).strftime('%d.%m.%Y %H:%M')
    home=esc(str(fixture['home_name']))
    away=esc(str(fixture['away_name']))
    lines=['🏀 <b>ZEYNAL | NBA ANALİZ</b>',
           f'<b>{home}</b>  🆚  <b>{away}</b>',
           f'🗓 {start} TSİ  ·  Normal süre (48 dk)',
           '',
           '📊 <b>SKOR PROJEKSİYONU</b>',
           f'🏠 Ev: <b>{p["home"]:.1f}</b>   ✈️ Dep: <b>{p["away"]:.1f}</b>',
           f'🎯 Toplam: <b>{p["total"]:.1f}</b>  ·  Fark (ev): {p["margin"]:+.1f}',
           '',
           '📈 <b>PİYASA | ARŞİV GÖZLEMİ</b>']
    if evidence:
        for quote in evidence[:6]:
            line=quote['line']
            sign=f'{line:+g}' if 'HANDICAP' in quote['market'] or 'SPREAD' in quote['market'] else f'{line:g}'
            label={'TOTAL':'Toplam','HOME_HANDICAP':'Ev handikapı'}.get(quote['market'],quote['market'])
            lines.append(f'• {esc(quote["bookmaker"])} · {esc(label)}: <b>{sign}</b>')
        lines.append('⚠️ Piyasa uzatma kapsamı doğrulanmadı; Alt/Üst ve edge yok.')
    else:
        lines.append('Doğrulanmış maç öncesi piyasa gözlemi bulunamadı.')
    lines.extend(['','🛡 <b>MODEL DURUMU</b>',
                  'Kalibrasyon: doğrulanmadı  ·  Güven endeksi: yok',
                  'Kadro / sakatlık / tempo: doğrulanmadı',
                  '🔒 '+('Kayıtlı tahmin tekrar gösterildi.' if replayed else 'Yeni tahmin arşivlendi.'),
                  '','<i>İzole araştırma · Üretim değil · Bahis önerisi değil</i>'])
    return '\n'.join(lines)

def keyboard(token):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('📊 Periyotlar',callback_data='zui:'+token+':period'),
         InlineKeyboardButton('📈 Piyasa',callback_data='zui:'+token+':market')],
        [InlineKeyboardButton('🎯 Aralıklar',callback_data='zui:'+token+':ranges'),
         InlineKeyboardButton('🛡 Model / Kaynak',callback_data='zui:'+token+':audit')],
        [InlineKeyboardButton('🏥 Kadro / Sakatlık',callback_data='zui:'+token+':roster')],
        [InlineKeyboardButton('🏠 Özet',callback_data='zui:'+token+':summary')]])

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
           '<i>Tempo etiketi, yalnızca tahmini periyot sayı toplamlarının göreli karşılaştırmasıdır.</i>','']
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
    return '\\n'.join(lines)

def detail_sections(parts, market_html):
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
        'roster':roster_section(),
        'audit':section('MODEL DENETİMİ','__END__'),
    }

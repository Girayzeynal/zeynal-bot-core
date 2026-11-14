"""Compact Telegram presentation for isolated research forecasts.

Presentation only: no mutation of frozen snapshots, market observations or model.
"""
import html
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
        [InlineKeyboardButton('🏠 Özet',callback_data='zui:'+token+':summary')]])

def detail_sections(parts, market_html):
    # Existing renderer is the canonical source for detailed data.
    full='\n\n'.join(parts)
    def section(title, next_title):
        start=full.find('<b>'+title+'</b>')
        if start<0:return '<b>Veri bulunamadı</b>'
        end=full.find('<b>'+next_title+'</b>',start+len(title)+7)
        return full[start:end].strip() if end>=0 else full[start:].strip()
    return {
        'period':section('PERİYOT ANALİZİ','PİYASA KARŞILAŞTIRMASI'),
        'ranges':section('TAHMİN ARALIKLARI','PERİYOT ANALİZİ'),
        'market':market_html,
        'audit':section('MODEL DENETİMİ','__END__'),
    }

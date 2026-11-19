"""Human-readable upcoming fixture commands for the isolated bot only."""
import html
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from hybrid_engine.elite_render import split_blocks
from hybrid_engine.forward_validation import verified_catalog
from hybrid_engine.live_euroleague import names
from hybrid_engine.prospective_results import OFFICIAL


def nba_blocks(games,day):
    blocks=['<b>NBA | '+html.escape(day)+' | Türkiye saati</b>\nKaynak: ESPN | Fikstür (tahmin değil)']
    for g in games:
        b=html.escape(f"{g['start']:%H:%M} | {g['home']} – {g['away']} | {g['status']} | ESPN {g['id']}")
        if g['status']=='Başlamadı' and g['start'].timestamp()>time.time():
            b+='\n<code>'+html.escape(f"/analyze NBA {g['start']:%Y-%m-%d} {g['home']} vs {g['away']}")+'</code>'
        blocks.append(b)
    if not games:blocks.append('Bu Türkiye takvim gününde doğrulanmış maç yok.')
    return split_blocks(blocks)


def euroleague_blocks(receipt,day):
    catalog=verified_catalog(receipt);pair=names(receipt['document']);now=int(time.time())
    blocks=['<b>EUROLEAGUE | '+html.escape(day)+' | Türkiye saati</b>\nKaynak: resmî EuroLeague | Fikstür (tahmin değil)']
    for g in sorted(catalog['payload']['fixtures'],key=lambda v:v['start_ts_utc']):
        start=datetime.fromtimestamp(g['start_ts_utc'],ZoneInfo('Europe/Istanbul'))
        if start.date().isoformat()!=day:continue
        h,a=pair[g['provider_fixture_ids'][0]]
        status='Tamamlandı' if g['completed'] else 'Başlamadı' if g['start_ts_utc']>now else 'Başladı / final bekleniyor'
        b=html.escape(f'{start:%H:%M} | {h} – {a} | {status} | '+', '.join(g['provider_fixture_ids']))
        if not g['completed'] and now+1800<g['start_ts_utc']<now+86400:
            b+='\n<code>'+html.escape(f'/analyze EUROLEAGUE {start:%Y-%m-%d} {h} vs {a}')+'</code>'
        blocks.append(b)
    if len(blocks)==1:blocks.append('Bu Türkiye takvim gününde doğrulanmış maç yok.')
    return split_blocks(blocks)

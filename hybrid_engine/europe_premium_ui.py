"""Presentation-only European buttons using the existing authenticated NBA callback.

No inference, training, market synthesis, downloads or forecast writes here.
"""
import html
import re
import secrets
import time

from core.league_identity import resolve_league
from core.team_identity import digest
from projection_integrity import assert_projection
from telegram_delivery import tsi
from hybrid_engine.elite_render import split_blocks
from hybrid_engine.telegram_premium_ui import compact_summary,keyboard,cache_report,roster_section
from hybrid_engine.telegram_roster_bridge import read_fixture_roster_evidence

SUPPORTED=('EUROPE_HYBRID_OK','FORWARD_EUROLEAGUE_OK','FROZEN_REPLAY_OK')
VERSION='EUROPE_COMPACT_ARCHIVE_V2'


def publication(registry,pin):
    """Read and verify only the requested publication, never every forecast.

    Mirrors the immutable registry's publication/clock/asset checks. On small
    UserLAnd devices rescanning every season source for one button view can
    exhaust the presentation deadline. No new index or archive rewrite.
    """
    if type(pin) is not str or re.fullmatch('[0-9a-f]{64}',pin) is None:
        raise ValueError('EUROPE_UI_PUBLICATION_PIN')
    ref=dict(file='forecast-'+pin+'.json',sha256=pin)
    try:
        p=registry.read_asset(ref)
        key=digest(dict(fixture=p['fixture']['canonical_id'],version=p['version']))
        pub=registry.publication(registry.root/('first-'+key+'.json'))
        if pub['forecast']!=ref:raise ValueError('EUROPE_UI_PUBLICATION_PIN')
        clocks=[p['source_available_max_utc'],p['prediction_generated_at_utc'],p['snapshot_created_at_utc'],
                pub['first_archived_at_utc'],p['fixture']['start_ts_utc']]
        if (any(type(v) is not int for v in clocks) or p.get('actual') is not None or
                not 0<clocks[0]<=clocks[1]<=clocks[2]<=clocks[3]<=int(time.time()) or clocks[2]>=clocks[4] or
                type(pub['eligible_for_prospective_audit']) is not bool or
                pub['eligible_for_prospective_audit']!=(clocks[3]<clocks[4]) or
                pub['classification']!=('PREMATCH' if clocks[3]<clocks[4] else 'LATE_COMMIT_EXCLUDED')):
            raise ValueError('EUROPE_UI_PUBLICATION_CLOCK')
        for asset in p['assets']:registry.read_asset(asset)
    except (OSError,KeyError) as exc:
        raise ValueError('EUROPE_UI_PUBLICATION_PIN') from exc
    return dict(payload=p,publication=pub)


def projection(report,league,*,service=None,forward_service=None):
    if report['status']=='FROZEN_REPLAY_OK':
        p=report['record'];g=p['fixture'];pin=digest(p)
        if report['timeline']['snapshot_sha256']!=pin:raise ValueError('EUROPE_UI_FROZEN_PIN')
        q=p['models']['BAYES_QMC']['prediction'];bands=report['bands']
        pair=(g['home_name'],g['away_name']);generated=report['timeline'].get('prediction_generated_at_utc')
        archived=report['timeline'].get('first_archived_at_utc')
        source=p['official_source'];version=p['models']['BAYES_QMC']['model_digest']
    else:
        owner=service if report['status']=='EUROPE_HYBRID_OK' else forward_service
        if owner is None:raise ValueError('EUROPE_UI_REGISTRY_REQUIRED')
        item=publication(owner.registry,report['forecast_sha256'])
        p=item['payload'];g=p['fixture'];pin=digest(p)
        q=p['components']['BAYES_QMC']['prediction'];bands=p['components']['BAYES_QMC']['intervals']
        pair=owner.pair(p) if report['status']=='EUROPE_HYBRID_OK' else owner._pair(p)
        generated=p['prediction_generated_at_utc'];archived=item['publication']['first_archived_at_utc']
        from hybrid_engine.europe_models import season_url
        source=season_url(league,g['season_start_year']);version=p['version']
    if resolve_league(g['league']).code!=league:raise ValueError('EUROPE_UI_LEAGUE_BINDING')
    assert_projection(q)
    return dict(payload=p,fixture=g,prediction=q,bands=bands,pair=pair,generated=generated,archived=archived,
                source=source,version=version,forecast_sha256=pin)


def ranges(bands):
    labels={'TOTAL':'Maç toplamı','HOME':'Ev toplamı','AWAY':'Deplasman toplamı',
            'MARGIN':'Ev farkı','HOME_HANDICAP':'Model ev handikabı (piyasa çizgisi değil)',
            '1Q':'1. çeyrek','2Q':'2. çeyrek','3Q':'3. çeyrek','4Q':'4. çeyrek',
            '1H':'İlk yarı','2H':'İkinci yarı'}
    lines=['🎯 <b>HAM TAHMİN ARALIKLARI</b>',
           'Arşivdeki gerçek dağılım; yeni simülasyon çalıştırılmadı.']
    for key,label in labels.items():
        b=bands.get('markets',{}).get(key)
        if b is None:continue
        lines.extend(['','<b>'+label+'</b>',
            f"P50 {b['p50']:.1f} | P25–P75 {b['p25']:.1f}–{b['p75']:.1f}",
            f"P10–P90 {b['p10']:.1f}–{b['p90']:.1f} | P05–P95 {b['p05']:.1f}–{b['p95']:.1f}"])
    lines.extend(['','Nominal bantlar; gerçekleşen kapsama veya güven garantisi değildir.',
                  'NOT_CALIBRATED · Güven endeksi yok.'])
    return '\n'.join(lines)


def market_view(report):
    full='\n\n'.join(report.get('html_parts') or [report['html']])
    marker='<b>EUROLEAGUE | MANUEL PİYASA GÖZLEMİ</b>'
    if marker in full:
        return '📈 <b>PİYASA | ARŞİV GÖZLEMİ</b>\nYeniden sorgulanmadı; ilk tahmin değiştirilmedi.\n\n'+full[full.index(marker):]
    match=re.search(r'<b>PİYASA KARŞILAŞTIRMASI</b>(.*?)(?=<b>MODEL DENETİMİ</b>|$)',full,re.S)
    extra=match.group(1).strip() if match else ''
    return ('📈 <b>PİYASA | KAYNAK DENETİMİ</b>\n'+extra+
            '\nDoğrulanabilir piyasa baremi bu görünüm için bağlanmadı.\n'
            'Piyasa verisi doğrulanamadı; yön, oran veya edge üretilmedi.\n'
            'Eksik piyasa verisi NO EDGE anlamına gelmez.\n'
            'NOT_CALIBRATED · Güven endeksi yok.')


def present(report,league,cache,chat_id,*,service=None,forward_service=None,roster_store=None):
    if league not in ('EUROLEAGUE','EUROCUP') or report.get('status') not in SUPPORTED:return report
    v=projection(report,league,service=service,forward_service=forward_service)
    g=v['fixture'];q=v['prediction'];esc=html.escape
    snap=dict(fixture_id=g['canonical_id'],fixture_start_utc=g['start_ts_utc'],
              home=dict(official_name=v['pair'][0]),away=dict(official_name=v['pair'][1]),
              prediction=q,intervals=v['bands'],prediction_generated_at_utc=v['generated'])
    summary=compact_summary(snap,None,replayed=not report.get('new_record',False),league=league)
    period=['📊 <b>PERİYOT | SKOR PROJEKSİYONU</b>',
            'Ev – Deplasman · Normal süre, 40 dk']
    for label,pair in [(str(i+1)+'Q',a) for i,a in enumerate(q['quarters'])]+[(str(i+1)+'H',a) for i,a in enumerate(q['halves'])]:
        period.extend(['',f'<b>{label}</b>: {pair[0]:.2f} – {pair[1]:.2f} | Toplam {sum(pair):.2f}'])
        b=v['bands'].get('markets',{}).get(label)
        if b:period.append(f"P25–P75 {b['p25']:.1f}–{b['p75']:.1f} | P05–P95 {b['p05']:.1f}–{b['p95']:.1f}")
    period.extend(['','Bağımsız yuvarlama küçük gösterim farkları yaratabilir; ham toplamlar denetlendi.',
                   'Kadro etkisi ve ölçülmüş pozisyon temposu doğrulanmadı.'])
    evidence=None
    if v['generated'] is not None:
        evidence=read_fixture_roster_evidence(roster_store,fixture_id=g['canonical_id'],prediction_utc=v['generated'],
            fixture_start_utc=g['start_ts_utc'],home_team_id=str(g['home_team_id']),away_team_id=str(g['away_team_id']))
    roster=(roster_section(evidence)+'\n\n'+
            'Güncel resmî kaynak kontrolü bu düğmede ayrı gözlem olarak yapılır.\n'
            'Doğrulanmış ilk tahmin kanıtı varsa yukarıda gösterilir.\n'
            'Veri yokluğu, sakat veya cezalı oyuncu olmadığı anlamına gelmez.\n'
            'Oyuncu etkisi ve mevcut skor değiştirilmedi.')
    audit=['🛡 <b>MODEL / KAYNAK</b>','NOT_CALIBRATED · Güven endeksi yok.',
           'Lig: '+league,'Model: '+esc(q['model']),'Sürüm SHA: '+esc(v['version']),
           'Yöntem: '+esc(str(q.get('metadata',{}).get('method','Arşivde ayrı kaydedilmemiş'))),
           'Gerçek örnek sayısı: '+str(v['bands'].get('scenarios','ayrı kaydedilmemiş')),
           'Üretim: '+tsi(v['generated']),'İlk kalıcı arşiv: '+tsi(v['archived']),
           'Maç: '+tsi(g['start_ts_utc']),'Resmî maç kimliği: '+esc(', '.join(g['provider_fixture_ids'])),
           'Kaynak: '+esc(v['source']),'Tahmin SHA-256: '+v['forecast_sha256'],
           'Düğmeler yalnız kaydedilmiş raporu gösterir; model eğitimi veya yeni tahmin yok.',
           'Liglere ait kadro, tempo ve piyasa verisi ayrıca doğrulanmalıdır.']
    if q.get('winner') is not None:
        audit.extend(['Ham normal süre ev / eşitlik / deplasman: '+
                      ' / '.join(f'%{100*x:.1f}' for x in q['winner']),
                      'Ham olay olasılığı, aralık kapsaması ve güven endeksi farklı kavramlardır.'])
    sections=dict(period='\n'.join(period),ranges=ranges(v['bands']),market=market_view(report),
                  roster=roster,audit='\n'.join(audit))
    section_pages={k:split_blocks(text.splitlines(),limit=3200) for k,text in sections.items()}
    token=secrets.token_hex(6)
    entry=dict(summary=summary,sections=sections,section_pages=section_pages,chat_id=chat_id,
               tipoff_utc=g['start_ts_utc'],quote_valid_until_utc=None,roster_context=None,
               europe_forecast_sha256=v['forecast_sha256'],league=league)
    if len(summary.encode('utf-16-le'))//2>3500:raise ValueError('EUROPE_UI_SUMMARY_BUDGET')
    from hybrid_engine.europe_data import context
    entry['europe_context']=context(v,league)
    entry['iddaa_first_half_total']=sum(q['halves'][0])
    entry['europe_original_sections']={k:sections[k] for k in ('market','roster')}
    cache_report(cache,token,entry)
    return dict(report,html_parts=[summary],html=summary,reply_markup=keyboard(token),presentation_version=VERSION)

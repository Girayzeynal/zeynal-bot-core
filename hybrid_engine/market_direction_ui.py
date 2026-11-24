"""Presentation-only direction cards from verified, unchanged model samples."""
import html
import math
import numpy as np
from hybrid_engine.market_turkish import period,market
from hybrid_engine.decision_layer import POLICY
from telegram_delivery import tsi

MAX_CARDS=128

def number(value,places=1):
    if type(value) not in (int,float) or not math.isfinite(value):
        raise ValueError('UI_FINITE_NUMBER_REQUIRED')
    return f'{value:.{places}f}'.replace('.',',')

def line_number(value):
    if type(value) not in (int,float) or not math.isfinite(value):
        raise ValueError('UI_FINITE_LINE_REQUIRED')
    return f'{value:g}'.replace('.',',')

def projection_mean(forecast,part,kind):
    q=np.asarray(forecast.quarter_means,dtype=float)
    if q.shape!=(4,2) or not np.isfinite(q).all() or np.any(q<0):
        raise ValueError('UI_COHERENT_PROJECTION_REQUIRED')
    if part=='FULL':scores=q.sum(axis=0)
    elif part in ('1H','2H'):scores=q[:2].sum(axis=0) if part=='1H' else q[2:].sum(axis=0)
    elif part in ('1Q','2Q','3Q','4Q'):scores=q[int(part[0])-1]
    else:raise ValueError('UI_SUPPORTED_PERIOD_REQUIRED')
    if kind=='TOTAL':return float(scores.sum())
    if kind in ('HOME','AWAY'):return float(scores[0 if kind=='HOME' else 1])
    if kind in ('HOME_HANDICAP','WINNER'):return float(scores[0]-scores[1])
    raise ValueError('UI_SUPPORTED_MARKET_REQUIRED')

def cards(view,forecast,*,tipoff_utc,fixture_id,batch=None):
    if not view.get('rows'):return []
    source=view['source'];asof=view.get('decision_utc',view.get('evaluated_at_utc'))
    captured=source['captured_at_utc'];available=view['available_at_utc'];published=source['published_at_utc']
    clock=source.get('event_clock_binding')
    deadline=min(tipoff_utc,clock['payload']['prematch_deadline_utc']) if clock else tipoff_utc
    current=(source['method']=='NATIVE_RETRIEVAL' and type(captured) is int and
        captured<=available<=asof<deadline and 0<=asof-captured<=POLICY['quote_max_age_seconds'] and
        (published is None or 0<=asof-published<=POLICY['quote_max_age_seconds']) and
        (batch is None or batch['payload']['record_class']=='PREGAME_CURRENT_REVIEW'))
    if 'parameter_fit_age_seconds' in view:
        from hybrid_engine.time_policy import MAXIMUM_V3_MODEL_AGE_SECONDS
        age=view['parameter_fit_age_seconds']
        v3=(view.get('research_record_type')=='CURRENT_RESEARCH_ASSESSMENT_V1' and
            view.get('model_fit_age_limit_seconds')==MAXIMUM_V3_MODEL_AGE_SECONDS)
        ceiling=MAXIMUM_V3_MODEL_AGE_SECONDS if v3 else 21600
        current=current and type(age) is int and 0<=age<=ceiling
    # League comes from the admitted market fixture, not the model name.
    # Older presentation-only views may omit it: never guess 48 minutes.
    league=(view.get('fixture') or {}).get('league')
    if league is None and clock:
        league=clock['payload'].get('league')
    minutes={'NBA':48,'EUROLEAGUE':40,'EUROCUP':40}.get(str(league).upper())
    out=[]
    for row in view['rows']:
        p=row['conditional_regulation_probabilities']
        if (set(p)!={'under','push','over'} or any(type(x) not in (int,float) or not math.isfinite(x) or not 0<=x<=1 for x in p.values()) or abs(sum(p.values())-1)>1e-8):
            raise ValueError('UI_VALID_PROBABILITY_SIMPLEX_REQUIRED')
        line_number(row['line'])
        mean=projection_mean(forecast,row['period'],row['market'])
        side=None if abs(p['under']-p['over'])<1e-12 or p['push']>=max(p['under'],p['over']) else 'over' if p['over']>p['under'] else 'under'
        native=current and 'NATIVE_PRICE_EVIDENCE_REQUIRED' not in row.get('reasons',[])
        expiry=min(deadline,captured+POLICY['quote_max_age_seconds'],published+POLICY['quote_max_age_seconds'] if published is not None else deadline) if native else None
        out.append(dict(fixture_id=fixture_id,tipoff_utc=tipoff_utc,model_digest=view['model_digest'],
            league=league,regulation_minutes=minutes,
            period=row['period'],market=row['market'],line=row['line'],prices=dict(row['prices']),
            probabilities=dict(p),side=side,probability=None if side is None else p[side],mean=mean,
            bookmaker=dict(view['bookmaker']),provider=source['provider_name'],method=source['method'],
            current=native,valid_until_utc=expiry,post_tipoff=asof>=deadline,available_at_utc=available,asof_utc=asof,
            prediction_utc=view['prediction_utc'],observation_sha256=view['observation_sha256'],
            decision_sha256=None if batch is None else batch['sha256'],
            calibration_status='NOT_CALIBRATED',confidence_index=None,selection_enabled=False))
    return out

def labels(card):
    kind=card['market']
    return ('DEP KARŞILAR','EV KARŞILAR') if kind=='HOME_HANDICAP' else ('DEP','EV') if kind=='WINNER' else ('ALT','ÜST')

def direction(card):
    if card['side'] is None:return 'BELİRGİN YÖN YOK'
    label=labels(card)[card['side']=='over']
    return label+(' '+line_number(card['line']) if card['market'] in ('TOTAL','HOME','AWAY') else '')

def reason(card):
    mean=card['mean'];kind=card['market'];line=card['line'];side=card['side']
    threshold=-line if kind=='HOME_HANDICAP' else line
    delta=mean-threshold
    if side is None:return 'Dağılımda bir taraf belirginleşmiyor veya eşitlik kütlesi önde.'
    if kind in ('TOTAL','HOME','AWAY') and (delta>0)==(side=='over') and abs(delta)>1e-10:
        subject='toplamı' if kind=='TOTAL' else 'takım toplamını'
        return 'Model '+subject+' baremin '+number(abs(delta))+' sayı '+('üstünde' if delta>0 else 'altında')+' bekliyor.'
    return 'Simülasyon örneklerinde '+labels(card)[side=='over']+' tarafı daha sık görülüyor.'

def brief(card):
    esc=html.escape;under,over=labels(card);p=card['probabilities']
    lines=['🎯 <b>'+('MODEL YÖNÜ' if card['current'] else 'ARŞİV MODEL YÖNÜ')+': '+esc(direction(card))+'</b>']
    if card['probability'] is None:
        lines.append('Model olasılığı: '+under+' %'+number(100*p['under'])+' · '+over+' %'+number(100*p['over']))
    else:lines.append('Model olasılığı: <b>%'+number(100*card['probability'])+'</b>')
    lines.extend(['🛡 <b>Yönün güvenilirliği</b>: Henüz yeterince doğrulanmadı',
                  'Gerekçe: '+esc(reason(card))])
    return '\n'.join(lines)

def render(card):
    esc=html.escape;kind=card['market'];p=card['probabilities'];under,over=labels(card)
    title=period(card['period'])+' · '+market(kind)
    if kind!='WINNER':title+=' · '+line_number(card['line'])
    lines=[brief(card),'','<b>'+esc(title)+'</b>',
        'Platform: '+esc(card['bookmaker']['name'])+' · '+esc(card['provider'])]
    mean_label={'TOTAL':'Beklenen toplam','HOME':'Beklenen ev toplamı','AWAY':'Beklenen deplasman toplamı',
                'HOME_HANDICAP':'Beklenen ev farkı','WINNER':'Beklenen ev farkı'}[kind]
    lines.extend([mean_label+': '+number(card['mean']),
        f"Ham normal süre: {under} %{number(100*p['under'])} · {over} %{number(100*p['over'])}"])
    if p['push']>0:lines.append(('Normal süre eşitliği' if kind=='WINNER' else 'Baremle eşit skor')+': %'+number(100*p['push']))
    minutes=card.get('regulation_minutes')
    duration=(' ('+str(minutes)+' dk)') if minutes in (40,48) else ''
    lines.append('⚠️ SÖZLEŞME UYUMU DOĞRULANMADI: Model NORMAL SÜRE'+duration+' hesaplar; '
                 'bahis şirketinin uzatma dahil olma ve ödeme kuralları bu model yüzdelerine '
                 'eşlenmedi. Yüzde, doğrulanmış bahis kazanma olasılığı değildir.')
    if kind=='WINNER':
        lines.append('Maç sonucu: Normal süre beraberliği modelde ayrı tutulur; '
                     'iki yönlü bahis piyasasındaki uzatma sonucuna otomatik aktarılmaz.')
    if card['prices']:lines.append('Oranlar: '+', '.join((under if side=='under' else over)+' '+line_number(price) for side,price in card['prices'].items()))
    if card['method']=='MANUAL_SCREENSHOT':lines.append('MANUEL EKRAN AKTARIMI · Alanlar bağımsız doğrulanmadı')
    if card['post_tipoff']:lines.append('Maç başladı; yalnız arşiv incelemesi.')
    elif not card['current']:lines.append('Güncel fiyat olarak doğrulanmadı; arşiv gözlemi.')
    lines.extend(['Fiyata erişim: '+tsi(card['available_at_utc']),'Değerlendirme: '+tsi(card['asof_utc']),
        'Ham model · NOT_CALIBRATED · Güven endeksi: yok',
        'Ödeme kapsamı ve oran matematiği: Model / Kaynak düğmesi.',
        'Gözlem SHA: '+card['observation_sha256'][:12]])
    if card['decision_sha256']:lines.append('Karar SHA: '+card['decision_sha256'][:12])
    return '\n'.join(lines)

def order(values):
    periods={'FULL':0,'1H':1,'2H':2,'1Q':3,'2Q':4,'3Q':5,'4Q':6}
    markets={'TOTAL':0,'HOME':1,'AWAY':2,'HOME_HANDICAP':3,'WINNER':4}
    # Stable display priority, never highest probability/EV selection.
    providers={'The Odds API':0,'ESPN':1}
    return sorted(values,key=lambda c:(not c['current'],periods[c['period']],markets[c['market']],
        providers.get(c['provider'],2),c['bookmaker']['id'],c['line']))

def pages(values):
    ranked=order(values)
    output=[render(c) for c in ranked[:MAX_CARDS]]
    if len(ranked)>MAX_CARDS:
        output.append('Gösterim sınırı: '+str(MAX_CARDS)+' / '+str(len(ranked))+' piyasa satırı.\nKaynak kayıtları korunur; daha dar piyasa sorgusu gerekir.')
    return output

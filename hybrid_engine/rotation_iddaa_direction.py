"""Prospective first-half direction benchmark from locally archived Iddaa lines.

Not bookmaker settlement evidence: native publisher time and payment rules
are unknown. Never backfill decisions after tip, alter scores, or train.
"""
from collections import Counter
import json
import math
import time
from core.team_identity import digest
from hybrid_engine.boxes import publish_json
from hybrid_engine.data import local_path
from hybrid_engine.iddaa_comparison import read_event
from hybrid_engine.rotation_report import actual_periods
from hybrid_engine.time_policy import PREMATCH_MINIMUM_LEAD_SECONDS

PREFIX='iddaa-half-direction-'
VERSION='ROTATION_IDDAA_HALF_REFERENCE_V1'

def side(value,line):
    if not math.isfinite(value) or not math.isfinite(line):raise ValueError('HALF_NONFINITE')
    return 'OVER' if value>line else 'UNDER' if value<line else 'EQUAL'

def build(folder,raw,decision):
    g,mtime,pin,p,r=raw
    tip=r['fixture_start_utc']
    if (r['league']!='NBA' or type(decision) is not int or not g<=mtime<=decision<tip-PREMATCH_MINIMUM_LEAD_SECONDS
        or p['original_snapshot_sha256']!=r['snapshot_sha256'] or p['fixture_id']!=r['fixture_id']
        or p['fixture_start_utc']!=tip or p['forecast_changed'] or p['calibrated'] or p['production_enabled']):
        raise ValueError('HALF_RAW_CLOCK_OR_SCOPE')
    root=local_path(folder.parent/'iddaa-bulletin')
    paths=list((root/'first-half'/'NBA'/str(tip)).glob('*.json'))
    if len(paths)>64:raise ValueError('HALF_INDEX_BUDGET')
    matches=[]
    for path in paths:
        try:
            if path.stat().st_size>65536:continue
            w=json.loads(path.read_bytes());ix=w['payload'];source_pin=ix['observation_sha256']
            if len(source_pin)!=64 or any(c not in '0123456789abcdef' for c in source_pin):continue
            source=local_path(root/('bulletin-'+source_pin+'.json'))
            if source.stat().st_size>2*1024*1024 or not 0<ix['indexed_at_utc']<=decision:continue
            if source.stat().st_mtime>decision or path.stat().st_mtime>decision:continue
            docs={};line=read_event(root,path,r,docs)
            if line is None or type(line) not in (int,float) or not 0<line<1000 or not float(2*line).is_integer():continue
            doc=docs[source_pin]
            if not 0<doc['observed_at_utc']<=ix['indexed_at_utc']<=decision:continue
            matches.append((line,w['sha256'],source_pin,doc['observed_at_utc'],ix['id']))
        except (OSError,ValueError,KeyError,TypeError,AttributeError):continue
    if len(matches)!=1:raise ValueError('HALF_NO_UNIQUE_LOCAL_REFERENCE')
    line,index_pin,source_pin,observed,event_id=matches[0]
    mean=p['simulation']['markets']['1H']['total']['mean']
    return dict(format=VERSION,fixture_id=r['fixture_id'],raw_receipt_sha256=pin,
        original_snapshot_sha256=r['snapshot_sha256'],fixture_start_utc=tip,
        decision_utc=decision,source_observed_utc=observed,source_pin=source_pin,index_pin=index_pin,
        event_id=event_id,period='1H',line=line,mean=mean,direction=side(mean,line),
        payment_verified=False,parameter_change=False)

def capture_one(root,raw):
    folder=local_path(root/'player-shadow')
    if raw[4]['actual'] is not None:return 'HOLD_CLOSED'
    now=int(time.time())
    path=folder/(PREFIX+raw[2]+'.json')
    if path.exists():return 'ALREADY_RECORDED'
    if len(list(folder.glob(PREFIX+'*.json')))>=4096:return 'HOLD_STORAGE_BUDGET'
    try:p=build(folder,raw,now)
    except (ValueError,KeyError,TypeError,OSError):return 'HOLD_NO_LOCAL_REFERENCE'
    if int(time.time())>=p['fixture_start_utc']-PREMATCH_MINIMUM_LEAD_SECONDS:return 'HOLD_CLOSED'
    publish_json(path,dict(payload=p,sha256=digest(p)))
    return 'CAPTURED_HALF_REFERENCE'

def review(folder,entries,now):
    folder=local_path(folder);counts=Counter();rows=[];excluded=0
    for raw in entries:
        path=folder/(PREFIX+raw[2]+'.json')
        if not path.exists():continue
        try:
            if path.is_symlink() or path.stat().st_size>65536:raise ValueError('HALF_FILE_SCOPE')
            w=json.loads(path.read_bytes());p=w['payload']
            if (digest(p)!=w['sha256'] or not p['decision_utc']<=path.stat().st_mtime<raw[4]['fixture_start_utc']-PREMATCH_MINIMUM_LEAD_SECONDS
                or path.stat().st_mtime>now or build(folder,raw,p['decision_utc'])!=p):
                raise ValueError('HALF_REPLAY')
            actual=actual_periods(raw[4],now)
            a=None if actual is None else float(actual[:2].sum())
            outcome='PENDING' if a is None else 'NO_DIRECTION' if p['direction']=='EQUAL' else 'EQUAL' if side(a,p['line'])=='EQUAL' else 'CORRECT' if side(a,p['line'])==p['direction'] else 'INCORRECT'
            counts[outcome]+=1
            rows.append(dict(fixture_id=p['fixture_id'],home=raw[4]['home'],away=raw[4]['away'],line=p['line'],
                mean=p['mean'],actual=a,outcome=outcome,decision=p['decision_utc']))
        except (ValueError,KeyError,TypeError,OSError,AttributeError):excluded+=1
    return dict(counts=dict(counts),rows=rows,excluded=excluded)

def render(folder,entries,now):
    r=review(folder,entries,now);c=r['counts']
    lines=['İDDAA İLK YARI — AYRI İSTATİSTİKSEL YÖN REFERANSI',
        'İlk yerel gözlem ve ham rotasyon eşleşmesi; ödeme kuralı, açılış ve yayın saati doğrulanmadı.',
        f"Eşleşme: {len(r['rows'])} | Doğru yön: {c.get('CORRECT',0)} | Yanlış yön: {c.get('INCORRECT',0)} | Eşit: {c.get('EQUAL',0)} | Bekleyen: {c.get('PENDING',0)} | Dışlanan: {r['excluded']}",
        'Bu sayılar ödeme başarısı değildir; katsayı değişikliği veya otomatik öğrenme tetiklemez.']
    for v in r['rows'][:20]:
        actual='bekliyor' if v['actual'] is None else f"{v['actual']:.0f}"
        lines.append(f"{v['home']} – {v['away']} | model {v['mean']:.2f} | barem {v['line']:g} | gerçek {actual} | {v['outcome']}")
    return lines

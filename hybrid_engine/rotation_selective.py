"""Selective, guarded point-score challenger; research only.

Error severity prioritizes investigation, not arbitrary coefficient inflation.
All observations are retained, including previously accurate forecasts.
No market direction labels or causal explanations are invented.
"""
from collections import Counter,defaultdict
import time
import numpy as np
from core.team_identity import digest
from hybrid_engine.data import Abstain,local_path
from hybrid_engine.rotation_forward_calibration import raw_quarters
from hybrid_engine.rotation_periods import read
from hybrid_engine.rotation_joint import MARKETS
from hybrid_engine.time_policy import PREMATCH_MINIMUM_LEAD_SECONDS

VERSION='NBA_ROTATION_SELECTIVE_V1'
# Thresholds for total, half and quarter point errors; fixed research choices.
THRESHOLDS={'FULL':(3,6,10,15,20),'1H':(2,4,6,9,12),'2H':(2,4,6,9,12)}
for q in ('1Q','2Q','3Q','4Q'):THRESHOLDS[q]=(1,3,5,7,10)
NAMES=('EXCELLENT','GOOD','MODERATE','HIGH','SERIOUS','CRITICAL')
MAX_SHIFT=3.
SHRINKAGE=8

def severity(error,market):
    if not np.isfinite(error):raise ValueError('SELECTIVE_NONFINITE_ERROR')
    return NAMES[int(np.searchsorted(THRESHOLDS[market],abs(error),side='left'))]

def observations(entries,target):
    from hybrid_engine.rotation_report import actual_periods
    g,_,_,p,row=target
    out=[];seen=set()
    for h,_,pin,b,r in sorted(entries,key=lambda e:(e[0],e[4]['fixture_id'],e[2])):
        if (r['fixture_id']==row['fixture_id'] or r['season']!=row['season']
            or b['original_model_version']!=p['original_model_version'] or h>=g):continue
        label=r.get('label_available_utc')
        if type(label) is not int or label>=g:continue
        a=actual_periods(r,g)
        if a is None:continue
        if r['fixture_id'] in seen:raise ValueError('SELECTIVE_DUPLICATE_PRIOR')
        seen.add(r['fixture_id'])
        out.append(dict(fixture_id=r['fixture_id'],receipt=pin,decision=h,label=label,
            raw=raw_quarters(b).tolist(),actual=a.tolist()))
    return out

def proposal(prior):
    # Downweight extreme observations robustly. Focus on persistent directional
    # quarter/team misses while retaining every good observation as a control.
    e=np.asarray([np.asarray(r['actual'])-np.asarray(r['raw']) for r in prior],dtype=float)
    if e.ndim!=3 or e.shape[1:]!=(4,2) or not np.isfinite(e).all():
        raise ValueError('SELECTIVE_RESIDUAL_SCHEMA')
    n=len(e);shift=np.zeros((4,2))
    for q in range(4):
        for s in range(2):
            v=e[:,q,s];large=v[np.abs(v)>3]
            # At least two independent same-direction large residuals and
            # majority directional support; this is not a 100-game gate.
            if len(large)<2:continue
            sign=np.sign(np.median(v))
            if sign==0 or np.sum(large*sign>0)<2 or np.mean(v*sign>0)<=.5:continue
            weights=1+np.minimum(np.maximum(np.abs(v)-3,0)/7,1)
            center=float(np.sum(weights*np.clip(v,-12,12))/weights.sum())
            if center*sign<=0:continue
            shift[q,s]=np.clip(center*n/(n+SHRINKAGE),-MAX_SHIFT,MAX_SHIFT)
    return shift

def apply(raw,shift):
    return np.maximum(np.asarray(raw,dtype=float)+shift,0)

def axes(q):
    # Seven time markets times total, both team totals and score margin.
    result={}
    for k,idx in MARKETS.items():
        h,a=np.asarray(q)[idx].sum(axis=0)
        result.update({(k,'total'):h+a,(k,'home'):h,(k,'away'):a,(k,'margin'):h-a})
    return result

def guard(prior):
    # Chronological predictions of the adjustment, not a fit scored on its
    # own training examples. Both good and bad outcomes are counted.
    old=defaultdict(list);new=defaultdict(list);protected=Counter();regressions=Counter()
    tested=0
    for r in prior:
        past=[v for v in prior if v['decision']<r['decision'] and v['label']<r['decision']]
        if not past:continue
        shift=proposal(past)
        if not np.any(shift):continue
        tested+=1
        a=axes(r['actual']);b=axes(r['raw']);c=axes(apply(r['raw'],shift))
        for k in a:
            err=abs(b[k]-a[k]);adj=abs(c[k]-a[k])
            old[k].append(err);new[k].append(adj)
            threshold=THRESHOLDS[k[0]][1] if k[1]=='total' else THRESHOLDS[k[0]][1]/2
            if err<=threshold:
                protected[k]+=1
                if adj>threshold+1e-9:regressions[k]+=1
    summary=[]
    for k in sorted(old):
        before=float(np.mean(old[k]));after=float(np.mean(new[k]))
        summary.append(dict(market=k[0],axis=k[1],n=len(old[k]),raw_mae=before,
            candidate_mae=after,protected=protected[k],protected_regressions=regressions[k]))
    full=next((r for r in summary if r['market']=='FULL' and r['axis']=='total'),None)
    # Conservative research admission only. Insufficient evidence is not failure.
    if tested<2:status='INSUFFICIENT_CHRONOLOGICAL_EVIDENCE'
    elif any(r['protected_regressions'] or r['candidate_mae']>r['raw_mae']+1e-9 for r in summary):
        status='REJECT_REGRESSION'
    elif full is None or full['candidate_mae']>=full['raw_mae']-1e-9:status='REJECT_NO_TOTAL_IMPROVEMENT'
    else:status='RESEARCH_SCREEN_PASS'
    return dict(status=status,paired_cases=tested,axes=summary,production_promotion=False)

def candidate(entries,target,decision):
    g,_,pin,p,row=target
    if not g<=decision<row['fixture_start_utc']-PREMATCH_MINIMUM_LEAD_SECONDS:
        raise Abstain('SELECTIVE_PUBLICATION_WINDOW')
    prior=observations(entries,target)
    if not prior:raise Abstain('SELECTIVE_NO_SETTLED_PRIOR')
    shift=proposal(prior);screen=guard(prior)
    if not np.any(shift):raise Abstain('SELECTIVE_NO_PERSISTENT_ERROR')
    raw=raw_quarters(p);adj=apply(raw,shift)
    return dict(format=VERSION,status='SELECTIVE_SHADOW_RESEARCH',fixture_id=row['fixture_id'],
        season=row['season'],fixture_start_utc=row['fixture_start_utc'],generated_at_utc=decision,
        raw_decision_utc=g,raw_receipt_sha256=pin,original_snapshot_sha256=row['snapshot_sha256'],
        prior_n=len(prior),prior=prior,screen=screen,raw_quarters=raw.tolist(),
        candidate_quarters=adj.tolist(),candidate_total=float(adj.sum()),
        production_enabled=False,forecast_changed=False,calibrated=False,
        market_direction_status='NOT_EVALUATED_NO_BOUND_PREGAME_MARKET',
        cause_status='RESIDUAL_PATTERN_NOT_CAUSAL_ATTRIBUTION')

def capture_new(root,ledger,raw_pin):
    from hybrid_engine.rotation_direction_policy import blocked
    return blocked()

def review(folder,entries,now):
    from hybrid_engine.rotation_report import actual_periods
    folder=local_path(folder);by_pin={e[2]:e for e in entries}
    chosen=defaultdict(list);excluded=Counter()
    for path in sorted(folder.glob('selective-score-*.json')):
        try:
            pin=path.stem.removeprefix('selective-score-');p=read(folder,'selective-score-',pin)
            t=by_pin[p['raw_receipt_sha256']];g=p['generated_at_utc']
            if (type(g) is not int or g>now or g-t[0]>300
                or not g<=path.stat().st_mtime<t[4]['fixture_start_utc']-PREMATCH_MINIMUM_LEAD_SECONDS
                or digest(candidate(entries,t,g))!=pin):raise ValueError('SELECTIVE_REPLAY')
            chosen[(t[4]['season'],t[4]['fixture_id'])].append((g,pin,p,t[4]))
        except (ValueError,KeyError,TypeError,OSError,IndexError) as exc:
            reason=str(exc);excluded[reason if reason.isupper() and len(reason)<100 else type(exc).__name__]+=1
    groups=defaultdict(lambda:dict(pending=0,matched=0,rows=[],screen=Counter()))
    for (season,_),items in sorted(chosen.items()):
        _,_,p,row=min(items,key=lambda r:r[:2]);group=groups[season]
        group['screen'][p['screen']['status']]+=1
        a=actual_periods(row,now)
        if a is None:group['pending']+=1;continue
        group['matched']+=1
        group['rows'].append((axes(p['raw_quarters']),axes(p['candidate_quarters']),axes(a)))
    out=[]
    for season,g in sorted(groups.items()):
        metrics=[]
        for k in sorted(axes(np.zeros((4,2)))):
            before=[];after=[];protected=regress=0
            for b,c,a in g['rows']:
                x=abs(b[k]-a[k]);y=abs(c[k]-a[k]);before.append(x);after.append(y)
                threshold=THRESHOLDS[k[0]][1] if k[1]=='total' else THRESHOLDS[k[0]][1]/2
                if x<=threshold:protected+=1;regress+=int(y>threshold)
            if before:metrics.append(dict(market=k[0],axis=k[1],n=len(before),raw_mae=float(np.mean(before)),
                candidate_mae=float(np.mean(after)),protected=protected,regressions=regress))
        out.append(dict(season=season,matched=g['matched'],pending=g['pending'],screens=dict(g['screen']),metrics=metrics))
    return dict(groups=out,duplicates=sum(len(v)-1 for v in chosen.values()),exclusions=dict(excluded),
        production_promotion=False,calibrated=False)

def render(folder,entries,now):
    from hybrid_engine.rotation_report import actual_periods
    bins=defaultdict(Counter)
    for _,_,_,p,row in entries:
        a=actual_periods(row,now)
        if a is None:continue
        b=axes(raw_quarters(p));y=axes(a)
        for k in MARKETS:bins[(row['season'],k)][severity(y[(k,'total')]-b[(k,'total')],k)]+=1
    lines=['NBA SEÇİCİ ÖĞRENME — GÖLGE ARAŞTIRMA',
           'PASİF ESKİ SAYISAL ARAŞTIRMA — yeni düzeltme üretilmez. /rotation direction']
    for (season,k),counts in sorted(bins.items()):
        lines.append(season+' '+k+': '+' | '.join(f'{name} {counts[name]}' for name in NAMES))
    if not bins:lines.append('Hata sınıflandırması için doğrulanmış sonuç yok.')
    r=review(folder,entries,now)
    lines.append(f"Tekrarlı: {r['duplicates']} | Dışlanan: {sum(r['exclusions'].values())}")
    for g in r['groups']:
        lines.append(f"{g['season']}: {g['matched']} sonuç / {g['pending']} bekliyor")
        for k,n in sorted(g['screens'].items()):lines.append(f'{k}: {n}')
        for m in g['metrics']:
            if m['axis']=='total':lines.append(f"{m['market']}: MAE {m['raw_mae']:.2f} → {m['candidate_mae']:.2f} | korunan {m['protected']} | bozulan {m['regressions']}")
    if not r['groups']:lines.append('Henüz doğrulanmış seçici aday kaydı yok.')
    lines.append('Alt/Üst yönü: bağlı doğrulanmış maç öncesi barem yok; ölçülmedi. Kök neden: nedensel kanıt yok.')
    from hybrid_engine.elite_render import split_blocks
    return split_blocks(lines,limit=3200)

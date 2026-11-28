"""Independent, time-stamped post-result NBA research refresh.

Old joint and correction receipts remain immutable. A fresh receipt admits
only labels actually available before its own decision, not the raw clock.
The transferred residual law is unchanged, not a calibrated probability.
"""
from collections import defaultdict,Counter
import time
import numpy as np
from core.team_identity import digest
from hybrid_engine.data import Abstain,local_path
from hybrid_engine.rotation_report import records,actual_periods
from hybrid_engine.rotation_forward_calibration import raw_quarters
from hybrid_engine.rotation_selective import proposal,guard,axes
from hybrid_engine.rotation_joint import simulate,MARKETS
from hybrid_engine.rotation_periods import read
from hybrid_engine.time_policy import PREMATCH_MINIMUM_LEAD_SECONDS
from hybrid_engine.sqlite_read_guard import error_reason
from telegram_delivery import tsi

VERSION='NBA_ROTATION_POST_RESULT_REFRESH_V1'
PREFIX='refresh-score-'
MAX_RECEIPTS=4096
HORIZON=36*3600

def observations(entries,target,decision):
    _,_,_,p,row=target
    out=[];seen=set()
    for h,mtime,pin,b,r in sorted(entries,key=lambda e:(e[0],e[4]['fixture_id'],e[2])):
        if (r['fixture_id']==row['fixture_id'] or r['season']!=row['season']
            or b['original_model_version']!=p['original_model_version']
            or b.get('format')!=p.get('format') or h>=decision or mtime>=decision):continue
        label=r.get('label_available_utc')
        if type(label) is not int or label>=decision:continue
        a=actual_periods(r,decision)
        if a is None:continue
        if r['fixture_id'] in seen:raise ValueError('REFRESH_DUPLICATE_PRIOR')
        seen.add(r['fixture_id'])
        out.append(dict(fixture_id=r['fixture_id'],receipt=pin,decision=h,label=label,
            raw=raw_quarters(b).tolist(),actual=a.tolist()))
    return out

def candidate(folder,entries,target,decision,prior=None):
    g,mtime,pin,p,row=target
    tip=row['fixture_start_utc']
    if type(decision) is not int or not g<=mtime<decision<tip-PREMATCH_MINIMUM_LEAD_SECONDS:
        raise Abstain('REFRESH_PUBLICATION_WINDOW')
    label=row.get('label_available_utc')
    if type(label) is int and label<=decision:
        raise Abstain('REFRESH_TARGET_ALREADY_SETTLED')
    if row['actual'] is not None and type(label) is not int:
        raise Abstain('REFRESH_TARGET_LABEL_UNVERIFIED')
    prior=observations(entries,target,decision) if prior is None else prior
    if len(prior)<2:raise Abstain('REFRESH_INSUFFICIENT_PRIOR')
    # Keep the established robust selective rule and every accurate control.
    shift=proposal(prior)
    if not np.any(shift):raise Abstain('REFRESH_NO_PERSISTENT_ERROR')
    raw=raw_quarters(p)
    adj=np.maximum(raw+shift,0.)
    pool=read(folder,'joint-pool-',p['residual_pool_sha256'])
    sim=simulate(adj,pool)
    # This screen is retrospective and cannot promote a fresh model.
    screen=guard(prior)
    return dict(format=VERSION,status='POST_RESULT_SHADOW_RESEARCH',fixture_id=row['fixture_id'],
        season=row['season'],fixture_start_utc=tip,generated_at_utc=decision,
        raw_decision_utc=g,raw_receipt_sha256=pin,original_snapshot_sha256=row['snapshot_sha256'],
        original_model_version=p['original_model_version'],prior_n=len(prior),prior=prior,
        cohort_sha256=digest(prior),screen=screen,raw_quarters=raw.tolist(),
        proposed_quarters=adj.tolist(),shift=(adj-raw).tolist(),
        residual_pool_sha256=p['residual_pool_sha256'],simulation=sim,
        production_enabled=False,forecast_changed=False,calibrated=False,
        cause_status='RESIDUAL_PATTERN_NOT_CAUSAL_ATTRIBUTION',
        uncertainty_scope='SAME_TRANSFERRED_RESIDUAL_LAW_NOT_CALIBRATED')

def review(folder,entries,now):
    folder=local_path(folder);by_pin={e[2]:e for e in entries}
    chosen=defaultdict(list);excluded=Counter()
    paths=sorted(folder.glob(PREFIX+'*.json'))
    if len(paths)>MAX_RECEIPTS:raise ValueError('REFRESH_SCAN_BUDGET')
    for path in paths:
        try:
            pin=path.stem.removeprefix(PREFIX);p=read(folder,PREFIX,pin)
            g=p['generated_at_utc']
            if type(g) is int and g>now:continue
            t=by_pin[p['raw_receipt_sha256']]
            if (type(g) is not int or not g<=path.stat().st_mtime<t[4]['fixture_start_utc']-PREMATCH_MINIMUM_LEAD_SECONDS
                or digest(candidate(folder,entries,t,g))!=pin):
                raise ValueError('REFRESH_REPLAY')
            chosen[(t[4]['season'],t[4]['fixture_id'])].append((g,path.stat().st_mtime,pin,p,t))
        except (ValueError,KeyError,TypeError,OSError,IndexError,np.linalg.LinAlgError) as exc:
            excluded[error_reason(exc)]+=1
    return dict(entries={k:sorted(v,key=lambda e:e[:3]) for k,v in chosen.items()},excluded=dict(excluded))

def refresh_one(root,ledger):
    from hybrid_engine.rotation_direction_policy import blocked
    return blocked()

def comparison(reviewed,now):
    # Freeze FIRST refresh for paired performance; never pick the best after
    # results are known. Latest valid receipt is separately displayed.
    rows=[]
    for seq in reviewed['entries'].values():
        _,_,_,p,t=seq[0]
        a=actual_periods(t[4],now)
        if a is None:continue
        raw=axes(p['raw_quarters'])
        m=p['simulation']['markets']
        new={(k,s):m[k][s]['mean'] for k in MARKETS for s in ('total','home','away','margin')}
        rows.append((raw,new,axes(a),m))
    result={}
    for k in MARKETS:
        for s in ('total','home','away','margin'):
            key=(k,s)
            if rows:
                old=[r[key]-a[key] for r,n,a,m in rows];new=[n[key]-a[key] for r,n,a,m in rows]
                result[key]=dict(n=len(rows),raw_mae=float(np.mean(np.abs(old))),new_mae=float(np.mean(np.abs(new))),
                    raw_bias=float(np.mean(old)),new_bias=float(np.mean(new)),
                    coverage80=float(np.mean([m[k][s]['p10']<=a[key]<=m[k][s]['p90'] for r,n,a,m in rows])))
    return result

def render(folder,entries,now):
    from hybrid_engine.elite_render import split_blocks
    r=review(folder,entries,now)
    lines=['NBA SONUÇ SONRASI GÜNCELLEME — ESKİ GÖLGE ARŞİVİ',
        'PASİF — Yön öncelikli politika gereği eski sayısal adaylar kullanılmaz; yeni aday üretilmez.',
        'İlk kayıt değişmedi; yeni zamanlı aday ayrı arşivde. Kalibre edilmedi.',
        f"Benzersiz maç: {len(r['entries'])} | Dışlanan: {sum(r['excluded'].values())}"]
    for seq in r['entries'].values():
        g,_,pin,p,t=seq[-1];row=t[4]
        if row['actual'] is not None or now>=row['fixture_start_utc']-PREMATCH_MINIMUM_LEAD_SECONDS:continue
        m=p['simulation']['markets']
        lines.extend(['',row['home']+' – '+row['away'],
            'Maç: '+tsi(row['fixture_start_utc'])+' | Aday: '+tsi(g),
            f"Önceki doğrulanmış sonuç: {p['prior_n']} | {p['screen']['status']}",
            f"Ham toplam {sum(map(sum,p['raw_quarters'])):.2f} → Gölge {m['FULL']['total']['mean']:.2f}",
            'Ev – Dep. | Toplam | Nominal %80'])
        for k in MARKETS:
            v=m[k];s=v['total']
            lines.append(f"{k}: {v['home']['mean']:.2f} – {v['away']['mean']:.2f} | {s['mean']:.2f} | {s['p10']:.0f}–{s['p90']:.0f}")
        lines.append('Kayıt: '+pin[:16])
    metrics=comparison(r,now)
    if metrics:
        lines.extend(['','İLK GÜNCELLEME ADAYI / AYNI MAÇLAR'])
        for k in MARKETS:
            m=metrics[(k,'total')]
            lines.append(f"{k}: n={m['n']} | MAE {m['raw_mae']:.2f} → {m['new_mae']:.2f} | Bias {m['new_bias']:+.2f} | %80 kapsama {m['coverage80']:.1%}")
    else:lines.append('Güncelleme adayının gerçek sonuç performansı henüz ölçülmedi.')
    if not r['entries']:lines.append('Doğrulanmış yeni zamanlı aday yok.')
    lines.append('Piyasa ve sakatlık etkisi güncellenmedi. Aktarılan hata dağılımı bağımsız kalibrasyon değildir.')
    return split_blocks(lines,limit=3200)

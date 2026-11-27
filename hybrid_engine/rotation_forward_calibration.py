"""Prospective point-score correction, separate from immutable joint receipts."""
import time
from collections import defaultdict,Counter
import numpy as np
from core.team_identity import digest
from hybrid_engine.data import local_path,Abstain
from hybrid_engine.rotation_periods import read
from hybrid_engine.rotation_joint import MARKETS
from hybrid_engine.rotation_calibration import SHRINKAGE,MAX_CELL_SHIFT
from hybrid_engine.time_policy import PREMATCH_MINIMUM_LEAD_SECONDS

VERSION='NBA_ROTATION_FORWARD_CORRECTION_V1'

def raw_quarters(p):
    q=np.asarray([[p['simulation']['markets'][f'{i}Q'][s]['mean'] for s in ('home','away')] for i in range(1,5)],dtype=float)
    if q.shape!=(4,2) or not np.isfinite(q).all() or (q<0).any():
        raise ValueError('FORWARD_CORRECTION_RAW_SCORE')
    return q

def candidate(entries,target,decision):
    from hybrid_engine.rotation_report import actual_periods
    g,_,pin,p,row=target
    if not g<=decision<row['fixture_start_utc']-PREMATCH_MINIMUM_LEAD_SECONDS:
        raise Abstain('FORWARD_CORRECTION_WINDOW')
    prior=[];seen=set()
    for h,_,rp,base,r in sorted(entries,key=lambda e:(e[0],e[4]['fixture_id'],e[2])):
        fid=r['fixture_id']
        if (fid==row['fixture_id'] or r['season']!=row['season']
            or base['original_model_version']!=p['original_model_version'] or h>=g):continue
        label=r.get('label_available_utc')
        # Freeze the observation cutoff at the raw prediction decision,
        # not the later time when this separate receipt is written.
        if type(label) is not int or label>=g:continue
        actual=actual_periods(r,g)
        if actual is None:continue
        if fid in seen:raise ValueError('FORWARD_CORRECTION_DUPLICATE_PRIOR')
        seen.add(fid)
        prior.append(dict(fixture_id=fid,receipt=rp,label_available_utc=label,
            errors=(actual-raw_quarters(base)).tolist()))
    n=len(prior)
    if not n:raise Abstain('FORWARD_CORRECTION_NO_SETTLED_PRIOR')
    raw=raw_quarters(p)
    shift=np.clip(np.median([r['errors'] for r in prior],axis=0)*n/(n+SHRINKAGE),-MAX_CELL_SHIFT,MAX_CELL_SHIFT)
    corrected=np.maximum(raw+shift,0)
    return dict(format=VERSION,status='FORWARD_CORRECTION_RESEARCH',fixture_id=row['fixture_id'],
        season=row['season'],fixture_start_utc=row['fixture_start_utc'],generated_at_utc=decision,
        raw_decision_utc=g,raw_receipt_sha256=pin,original_snapshot_sha256=row['snapshot_sha256'],
        original_model_version=p['original_model_version'],prior_n=n,prior=prior,
        policy=dict(shrinkage=SHRINKAGE,max_cell_shift=MAX_CELL_SHIFT),
        raw_quarters=raw.tolist(),corrected_quarters=corrected.tolist(),shift=(corrected-raw).tolist(),
        corrected_team_scores=corrected.sum(axis=0).tolist(),corrected_total=float(corrected.sum()),
        intervals_available=False,calibrated=False,production_enabled=False,forecast_changed=False)

def capture_new(root,ledger,raw_pin):
    from hybrid_engine.rotation_report import records
    from hybrid_engine.rotation_cycle import publish
    folder=local_path(root)/'player-shadow'
    now=int(time.time());entries,_,_=records(folder,ledger,now=now)
    matches=[e for e in entries if e[2]==raw_pin]
    if len(matches)!=1:raise Abstain('FORWARD_CORRECTION_RAW_NOT_FIRST_VERIFIED')
    target=matches[0]
    if target[4]['actual'] is not None:raise Abstain('FORWARD_CORRECTION_TARGET_SETTLED')
    # This entry point is called only as a continuation of fresh automatic
    # capture, not as a backfill of existing historical forecasts.
    if now-target[0]>300:raise Abstain('FORWARD_CORRECTION_RAW_TOO_OLD')
    p=candidate(entries,target,now)
    pin=publish(folder,'correction-score-',p,p['fixture_start_utc'])
    return dict(status='CAPTURED',receipt_sha256=pin,prior_n=p['prior_n'],corrected_total=p['corrected_total'])

def review(folder,entries,now):
    from hybrid_engine.rotation_report import actual_periods
    folder=local_path(folder)
    by_pin={e[2]:e for e in entries};chosen=defaultdict(list);excluded=Counter()
    for path in sorted(folder.glob('correction-score-*.json')):
        try:
            pin=path.stem.removeprefix('correction-score-');p=read(folder,'correction-score-',pin)
            target=by_pin[p['raw_receipt_sha256']]
            g=p['generated_at_utc'];tip=target[4]['fixture_start_utc']
            if (type(g) is not int or g>now or g-target[0]>300
                or not g<=path.stat().st_mtime<tip-PREMATCH_MINIMUM_LEAD_SECONDS
                or digest(candidate(entries,target,g))!=pin):
                raise ValueError('FORWARD_CORRECTION_REPLAY')
            chosen[(target[4]['season'],target[4]['fixture_id'])].append((g,pin,p,target[4]))
        except (ValueError,KeyError,TypeError,OSError,IndexError) as exc:
            reason=str(exc);excluded[reason if reason.isupper() and len(reason)<100 else type(exc).__name__]+=1
    groups=defaultdict(lambda:dict(pending=0,rows=[]));duplicates=0
    for (season,fid),items in sorted(chosen.items()):
        duplicates+=len(items)-1
        _,_,p,row=min(items,key=lambda r:r[:2])
        group=groups[season];actual=actual_periods(row,now)
        if actual is None:group['pending']+=1;continue
        group['rows'].append((p,actual))
    out=[]
    for season,v in sorted(groups.items()):
        rows=v['rows'];markets={}
        for market,idx in MARKETS.items():
            old=[float((np.asarray(p['raw_quarters'])[idx]-a[idx]).sum()) for p,a in rows]
            new=[float((np.asarray(p['corrected_quarters'])[idx]-a[idx]).sum()) for p,a in rows]
            if old:
                markets[market]=dict(n=len(old),raw_mae=float(np.mean(np.abs(old))),corrected_mae=float(np.mean(np.abs(new))),
                    raw_rmse=float(np.sqrt(np.mean(np.square(old)))),corrected_rmse=float(np.sqrt(np.mean(np.square(new)))),
                    raw_bias=float(np.mean(old)),corrected_bias=float(np.mean(new)))
        out.append(dict(season=season,matched=len(rows),pending=v['pending'],markets=markets))
    return dict(groups=out,duplicates=duplicates,exclusions=dict(excluded),
        calibrated=False,production_enabled=False,publication_evidence='LOCAL_FILE_CLOCK_NOT_EXTERNAL_ATTESTATION')

def render(folder,entries,now):
    r=review(folder,entries,now)
    lines=['NBA ROTASYON — MAÇ ÖNCESİ DÜZELTME ADAYI','Kalibre edilmedi. Ham tahmin korunuyor.',
        f"Tekrarlı kayıt: {r['duplicates']} | Dışlanan: {sum(r['exclusions'].values())}"]
    for g in r['groups']:
        lines.append(f"{g['season']}: {g['matched']} sonuçlandı / {g['pending']} bekliyor")
        for k,m in g['markets'].items():
            lines.append(f"{k}: MAE {m['raw_mae']:.2f} → {m['corrected_mae']:.2f}")
    if not r['groups']:lines.append('Doğrulanmış ileriye dönük düzeltme kaydı yok.')
    lines.append('Aralık ve olasılık kalibrasyonu bu modülde yapılmaz.')
    return ['\n'.join(lines)]

"""Read-only prequential replay of a candidate-specific residual correction.

No forecast is published or altered. Replay is designed after earlier
forecasts and cannot be represented as a prospective calibration trial.
"""
from collections import defaultdict
import math
import numpy as np
from hybrid_engine.rotation_joint import MARKETS

SHRINKAGE=8
MAX_CELL_SHIFT=3.
LEVELS=(80,90)

def radius(errors,level):
    # Finite-sample rank. Do not substitute a percentile if rank is unavailable.
    n=len(errors);k=(level*(n+1)+99)//100
    if not n or k>n:return None
    return float(sorted(abs(float(e)) for e in errors)[k-1])

def audit(entries,now):
    from hybrid_engine.rotation_report import actual_periods
    groups=defaultdict(list)
    seen=set()
    for g,_,pin,p,row in sorted(entries,key=lambda e:(e[0],e[4]['fixture_id'],e[2])):
        key=(row['season'],row['fixture_id'])
        if key in seen:raise ValueError('CALIBRATION_DUPLICATE_FIXTURE')
        seen.add(key)
        raw=np.array([[p['simulation']['markets'][f'{q}Q'][s]['mean'] for s in ('home','away')]
                      for q in range(1,5)],dtype=float)
        if raw.shape!=(4,2) or not np.isfinite(raw).all() or (raw<0).any():raise ValueError('CALIBRATION_RAW_SCORE')
        group=groups[(row['season'],p['original_model_version'])]
        # Only labels strictly earlier than the original forecast decision.
        prior=[r for r in group if r['actual'] is not None and r['label']<g and r['decision']<g]
        n=len(prior)
        shift=np.clip(np.median([r['actual']-r['raw'] for r in prior],axis=0)*n/(n+SHRINKAGE),
                      -MAX_CELL_SHIFT,MAX_CELL_SHIFT) if n else np.zeros((4,2))
        corrected=np.maximum(raw+shift,0)
        actual=actual_periods(row,now)
        bands={}
        for market,idx in MARKETS.items():
            center=float(corrected[idx].sum())
            past=[float((r['actual'][idx]-r['corrected'][idx]).sum()) for r in prior]
            bands[market]={str(level):None if (w:=radius(past,level)) is None else [max(0.,center-w),center+w] for level in LEVELS}
        group.append(dict(fixture_id=row['fixture_id'],receipt=pin,decision=g,
            label=row.get('label_available_utc') if actual is not None else None,
            actual=actual,raw=raw,corrected=corrected,prior_n=n,prior_ids=[r['fixture_id'] for r in prior],
            bands=bands))
    reports=[]
    for (season,version),rows in sorted(groups.items()):
        matched=[r for r in rows if r['actual'] is not None]
        paired=[r for r in matched if r['prior_n']>0]
        markets={}
        for market,idx in MARKETS.items():
            base=[float((r['raw'][idx]-r['actual'][idx]).sum()) for r in paired]
            new=[float((r['corrected'][idx]-r['actual'][idx]).sum()) for r in paired]
            metrics=dict(n=len(paired),raw_mae=float(np.mean(np.abs(base))) if base else None,
                corrected_mae=float(np.mean(np.abs(new))) if new else None,
                raw_bias=float(np.mean(base)) if base else None,
                corrected_bias=float(np.mean(new)) if new else None,
                raw_rmse=float(np.sqrt(np.mean(np.square(base)))) if base else None,
                corrected_rmse=float(np.sqrt(np.mean(np.square(new)))) if new else None)
            for level in LEVELS:
                cases=[(r['bands'][market][str(level)],float(r['actual'][idx].sum()))
                       for r in paired if r['bands'][market][str(level)] is not None]
                metrics['band'+str(level)]=dict(n=len(cases),coverage=sum(lo<=y<=hi for (lo,hi),y in cases)/len(cases) if cases else None,
                    mean_width=float(np.mean([hi-lo for (lo,hi),_ in cases])) if cases else None)
            markets[market]=metrics
        reports.append(dict(season=season,model_version=version,matched=len(matched),
            pending=len(rows)-len(matched),paired_correction_cases=len(paired),markets=markets,
            trace=[dict(fixture_id=r['fixture_id'],receipt=r['receipt'],decision=r['decision'],
                prior_n=r['prior_n'],prior_ids=r['prior_ids'],settled=r['actual'] is not None) for r in rows]))
    return dict(format='NBA_ROTATION_PREQUENTIAL_REPLAY_V1',groups=reports,
        fit_policy=dict(shrinkage=SHRINKAGE,max_cell_shift=MAX_CELL_SHIFT),
        retrospectively_designed=True,production_enabled=False,calibrated=False,
        original_archive_read_only=True)

def render(entries,now,excluded,duplicates):
    a=audit(entries,now)
    lines=['NBA ROTASYON — GEÇMİŞE DAYALI KALİBRASYON DENEMESİ',
           'Salt okunur geriye dönük yeniden yürütme; yeni tahmin yayımlanmadı.',
           f'Tekrarlı kayıt: {duplicates} | Dışlanan: {sum(excluded.values())}']
    for g in a['groups']:
        lines.append(f"{g['season']}: {g['matched']} sonuçlandı / {g['pending']} bekliyor")
        lines.append(f"Önceki sonuçla düzeltme denenebilen eşleşmiş maç: {g['paired_correction_cases']}")
        for k,m in g['markets'].items():
            if m['n']:
                lines.append(f"{k}: MAE ham {m['raw_mae']:.2f} → düzeltme {m['corrected_mae']:.2f}")
                for level in LEVELS:
                    b=m['band'+str(level)]
                    if b['n']:lines.append(f"  Nominal %{level}: n={b['n']} | kapsama {b['coverage']:.1%}")
        if not g['paired_correction_cases']:lines.append('Zamanında bilinen önceki sonuçla test edilebilen maç yok.')
    if not a['groups']:lines.append('Doğrulanmış araştırma kaydı yok.')
    lines.append('100 maç şartı yok. Yetersiz sıradan ampirik aralık üretilmez; kesin kalibrasyon iddiası yok.')
    return ['\n'.join(lines)]

"""Read-only integrated staging display and result audit for joint research."""
import argparse
from collections import Counter,defaultdict
from datetime import datetime
import re
import time
from zoneinfo import ZoneInfo
import numpy as np
from core.team_identity import digest
from hybrid_engine.data import local_path
from hybrid_engine.rotation_periods import read,capture
from hybrid_engine.rotation_joint import VERSION,MARKETS,residual_pool,simulate
from hybrid_engine.time_policy import PREMATCH_MINIMUM_LEAD_SECONDS

def records(root,ledger,*,now=None,selector=None,diagnostics=None):
    from hybrid_engine.runtime_reports import RuntimeLedgerReports
    from hybrid_engine.player_inputs import load_snapshot
    root=local_path(root);ledger=local_path(ledger)
    now=int(time.time()) if now is None else now
    if type(now) is not int or now>int(time.time()):raise ValueError('ROTATION_REVIEW_CLOCK')
    if not ledger.is_file():return [],{'LEDGER_NOT_PRESENT':1},0
    native=RuntimeLedgerReports(ledger).read('NBA',summarize=False)
    if native['status']!='VERIFIED_LIVE_REPORT':raise ValueError('ROTATION_LEDGER_UNVERIFIED')
    originals={(r['fixture_id'],r['snapshot_sha256']):r for r in native['forecasts']}
    counts=Counter(r['fixture_id'] for r in native['forecasts'])
    paths=sorted(root.glob('joint-score-*.json'))
    if len(paths)>4096:raise ValueError('ROTATION_RECEIPT_SCAN_BUDGET')
    chosen=defaultdict(list);excluded=Counter()
    for path in paths:
        m=re.fullmatch(r'joint-score-([0-9a-f]{64})\.json',path.name)
        if not m:continue
        try:
            pin=m[1];p=read(root,'joint-score-',pin)
            # A concurrent writer can publish after the report clock was frozen.
            # This is not a failed historical receipt; review on the next call.
            if type(p.get('generated_at_utc')) is int and p['generated_at_utc']>now:continue
            row=originals[(p['fixture_id'],p['original_snapshot_sha256'])]
            if selector and selector!=row['fixture_id'] and selector not in row['provider_fixture_ids']:continue
            tip=row['fixture_start_utc'];g=p['generated_at_utc']
            if (p['format']!=VERSION or p['status']!='FORWARD_JOINT_RESEARCH'
                or p['production_enabled'] or p['forecast_changed'] or p['calibrated']
                or p['fixture_start_utc']!=tip or p['original_model_version']!=row['model_version']
                or not row['prediction_generated_at_utc']<=g<=now
                or not g<=path.stat().st_mtime<tip-PREMATCH_MINIMUM_LEAD_SECONDS):
                raise ValueError('ROTATION_RECEIPT_CLOCK_OR_SCOPE')
            period=read(root,'period-score-',p['period_sha256'])
            period_path=root/('period-score-'+p['period_sha256']+'.json')
            if (period['fixture_id']!=row['fixture_id'] or period['original_snapshot_sha256']!=row['snapshot_sha256']
                or not period['generated_at_utc']<=period_path.stat().st_mtime<g+1):
                raise ValueError('ROTATION_PERIOD_CLOCK_OR_IDENTITY')
            factor=read(root,'factor-score-',period['factor_sha256'])
            a=read(root,'period-model-',period['control_sha256'])
            b=read(root,'period-model-',period['model_sha256'])
            if counts[row['fixture_id']]!=1:raise ValueError('EXACTLY_ONE_ARCHIVED_NBA_MODEL_REQUIRED')
            snapshot=load_snapshot(ledger,row['fixture_id'],verified_row=row)
            replay=capture(root,factor,period['factor_sha256'],snapshot,
                dict(payload=a,sha256=period['control_sha256']),
                dict(payload=b,sha256=period['model_sha256']),period['generated_at_utc'])
            if not np.allclose(replay['player_allocation']['quarters'],period['player_allocation']['quarters'],rtol=0,atol=1e-6):
                raise ValueError('ROTATION_PERIOD_REPLAY')
            pool=read(root,'joint-pool-',p['residual_pool_sha256'])
            cutoff=p.get('residual_cutoff_utc',g)
            if type(cutoff) is not int or not row['prediction_generated_at_utc']<=cutoff<=g:
                raise ValueError('ROTATION_RESIDUAL_CUTOFF')
            reconstructed=residual_pool(native['forecasts'],row,cutoff)
            if digest(reconstructed)!=p['residual_pool_sha256'] or len(pool)!=p['residual_games']:
                raise ValueError('ROTATION_RESIDUAL_POOL_REPLAY')
            # Original capture simulates the stored period point scores. The
            # independent tolerance check above still guards the period replay.
            sim=simulate(period['player_allocation']['quarters'],pool)
            if digest(sim)!=digest(p['simulation']):raise ValueError('ROTATION_SIMULATION_REPLAY')
            chosen[(row['season'],row['fixture_id'])].append((g,path.stat().st_mtime,pin,p,row))
        except (ValueError,KeyError,TypeError,OSError,IndexError,np.linalg.LinAlgError) as exc:
            reason=str(exc);reason=reason if reason.isupper() and len(reason)<100 and reason.replace('_','').isalnum() else type(exc).__name__
            excluded[reason]+=1
            if diagnostics is not None:diagnostics.append(dict(receipt=m[1],reason=reason))
    selected=[min(v,key=lambda x:x[:3]) for v in chosen.values()]
    return sorted(selected,key=lambda x:(x[4]['fixture_start_utc'],x[4]['fixture_id'])),dict(excluded),sum(len(v)-1 for v in chosen.values())

def actual_periods(row,now):
    label=row.get('label_available_utc')
    if row['actual'] is None or type(label) is not int or label>now:return None
    q=np.asarray([row['actual_periods'][s][:4] for s in ('home','away')],dtype=float).T
    if (label<=row['fixture_start_utc'] or q.shape!=(4,2) or not np.isfinite(q).all() or (q<0).any()
        or not np.array_equal(q.sum(axis=0),row['actual'])):
        raise ValueError('ROTATION_INVALID_FINAL')
    return q

def result_metrics(entries,now):
    groups=defaultdict(list);pending=Counter()
    for _,_,_,p,row in entries:
        actual=actual_periods(row,now)
        if actual is None:pending[row['season']]+=1;continue
        groups[row['season']].append((p,row,actual))
    out={}
    for season in sorted(set(groups)|set(pending)):
        rows=groups[season];markets={}
        for label,idx in MARKETS.items():
            errors=[];hits80=[];hits90=[];width80=[]
            for p,row,q in rows:
                actual=float(q[idx].sum());s=p['simulation']['markets'][label]['total']
                errors.append(s['mean']-actual)
                hits80.append(s['p10']<=actual<=s['p90'])
                hits90.append(s['p05']<=actual<=s['p95'])
                width80.append(s['p90']-s['p10'])
            if errors:
                markets[label]=dict(mae=float(np.mean(np.abs(errors))),rmse=float(np.sqrt(np.mean(np.square(errors)))),
                    bias=float(np.mean(errors)),coverage80=sum(hits80)/len(errors),coverage90=sum(hits90)/len(errors),
                    mean_width80=float(np.mean(width80)))
        out[season]=dict(matched=len(rows),pending=pending[season],markets=markets,
            original_total_mae=float(np.mean([abs(sum(r['prediction'])-q.sum()) for p,r,q in rows])) if rows else None)
    return out

def render(root,ledger,args=(),*,now=None):
    now=int(time.time()) if now is None else now
    args=list(args or [])
    if args and args[0].upper()=='NBA':args=args[1:]
    if len(args)>1 or (args and args[0] not in ('results','calibration','list','forward','selective','audit','refresh','direction') and not re.fullmatch(r'(?:[0-9]{1,15}|[0-9a-f]{64})',args[0])):
        return ['Kullanım: /rotation [NBA] [ESPN maç kimliği, results, calibration, forward, selective, refresh, direction, audit veya list]']
    review=bool(args and args[0] in ('results','calibration','list','forward','selective','audit','refresh','direction'))
    details=[]
    entries,excluded,duplicates=records(root,ledger,now=now,selector=args[0] if args and not review else None,diagnostics=details)
    warning='ARAŞTIRMA • KALİBRE EDİLMEDİ • Normal süre • Eski tahmin değişmedi.'
    if args==['audit']:
        from hybrid_engine.elite_render import split_blocks
        lines=[warning,'ROTASYON ARŞİV DENETİMİ',f'Benzersiz: {len(entries)} | Tekrarlı: {duplicates} | Dışlanan: {sum(excluded.values())}']
        for reason,n in sorted(excluded.items()):lines.append(f'{reason}: {n}')
        for d in details[:40]:lines.append(d['receipt'][:16]+' | '+d['reason'])
        if len(details)>40:lines.append(f'{len(details)-40} ek dışlanan kayıt; terminal denetimi gerekli.')
        return split_blocks(lines,limit=3200)
    if args==['direction']:
        from hybrid_engine.rotation_direction_policy import render as render_direction
        return render_direction(entries,now,folder=root,ledger=ledger)
    if args==['refresh']:
        from hybrid_engine.rotation_refresh import render as render_refresh
        return render_refresh(root,entries,now)
    if args==['selective']:
        from hybrid_engine.rotation_selective import render as render_selective
        return render_selective(root,entries,now)
    if args==['forward']:
        from hybrid_engine.rotation_forward_calibration import render as render_forward
        return render_forward(root,entries,now)
    if args==['calibration']:
        from hybrid_engine.rotation_calibration import render as render_calibration
        from hybrid_engine.rotation_direction_policy import render as render_direction
        return render_direction(entries,now,folder=root,ledger=ledger)
    if args==['list']:
        lines=[warning,'DOĞRULANMIŞ YAKLAŞAN MAÇLAR']
        for _,_,pin,p,row in entries:
            if now>=row['fixture_start_utc']-PREMATCH_MINIMUM_LEAD_SECONDS:continue
            clock=datetime.fromtimestamp(row['fixture_start_utc'],ZoneInfo('Europe/Istanbul')).strftime('%d.%m %H:%M')
            ids=row['provider_fixture_ids']
            lines.append(f"{clock} | {row['home']} – {row['away']} | /rotation {ids[0] if ids else row['fixture_id']}")
        if len(lines)==2:lines.append('Uygun kayıt yok.')
        from hybrid_engine.elite_render import split_blocks
        return split_blocks(lines,limit=3200)
    if review:
        lines=[warning,'ORTAK SİMÜLASYON SONUÇ DENETİMİ',f'Tekrarlı kayıt: {duplicates} | Dışlanan: {sum(excluded.values())}']
        for reason,n in sorted(excluded.items()):lines.append(f'Dışlama: {reason} ({n})')
        metrics=result_metrics(entries,now)
        for season,v in metrics.items():
            lines.append(f"{season}: {v['matched']} sonuçlandı / {v['pending']} bekliyor")
            for k,m in v['markets'].items():
                lines.append(f"{k}: MAE {m['mae']:.2f} | RMSE {m['rmse']:.2f} | Bias {m['bias']:+.2f} | gözlenen %80 kapsama {m['coverage80']:.1%}")
            if v['original_total_mae'] is not None:lines.append(f"İlk model aynı maçlarda toplam MAE {v['original_total_mae']:.2f}")
        if not entries:lines.append('Doğrulanmış araştırma kaydı yok.')
        if not any(v['matched'] for v in metrics.values()):lines.append('Henüz gerçek hata veya kapsama ölçülemedi.')
        return ['\n'.join(lines)]
    if not args:entries=[e for e in entries if now<e[4]['fixture_start_utc']-PREMATCH_MINIMUM_LEAD_SECONDS]
    messages=[]
    for g,_,pin,p,row in entries[:4]:
        sim=p['simulation'];tip=row['fixture_start_utc'];clock=lambda t:datetime.fromtimestamp(t,ZoneInfo('Europe/Istanbul')).strftime('%d.%m.%Y %H:%M TSİ')
        lines=[warning,f"{row['home']} – {row['away']}",f'Maç: {clock(tip)} | Kayıt: {clock(g)}',
            'ARŞİV KAYDI — YENİ CANLI HESAP DEĞİL',
            f"{p['residual_games']} geçmiş hata kaydı | {sim['scenarios']} senaryo",
            'Ev – Dep. | Toplam | Nominal %80 aralık']
        for k in MARKETS:
            m=sim['markets'][k];t=m['total']
            lines.append(f"{k}: {m['home']['mean']:.2f} – {m['away']['mean']:.2f} | {t['mean']:.2f} | {t['p10']:.0f}–{t['p90']:.0f}")
        full=sim['markets']['FULL']['total']
        lines.extend([f"Maç nominal %90: {full['p05']:.0f}–{full['p95']:.0f}",
            'Eski modelin hata dağılımı aktarıldı; yeni modelin olasılık doğruluğu kanıtlanmadı.',
            'Kesin kadro veya güncel sakatlık teyidi değildir.',f'Kayıt: {pin[:16]}'])
        if now>=tip-PREMATCH_MINIMUM_LEAD_SECONDS:lines.append('Maç öncesi yayın penceresi kapalı; yalnız tarihsel kayıt.')
        messages.append('\n'.join(lines))
    if not messages:return [warning+'\nUygun doğrulanmış kayıt yok. Yeni tahmin üretilmedi. /rotation results ile denetimi aç.']
    return messages

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--data-directory',required=True);p.add_argument('query',nargs='*')
    a=p.parse_args();root=local_path(a.data_directory)
    for msg in render(root/'player-shadow',root/'live-nba/nba-hybrid.sqlite',a.query):print(msg+'\n')
if __name__=='__main__':main()

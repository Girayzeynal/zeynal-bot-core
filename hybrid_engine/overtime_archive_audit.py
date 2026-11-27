"""Read-only empirical overtime audit using earliest verified native receipt clocks.
No live settlement admission, network calls, or mutation of forecast/history files.
"""
import time
from collections import defaultdict

from core.team_identity import digest
from historical_research import historical_rows
from hybrid_engine.adaptive_data import native_catalog
from hybrid_engine.data import STRICT,Abstain,available_at,regulation
from hybrid_engine.overtime_research import fit,walk_forward,DURATION,POLICY

def earliest_rows(store,league,year,now,*,deadline):
    earliest={};identity={};conflicts=set();receipts=0
    for ref in store.references(league,year):
        if time.monotonic()>=deadline:raise TimeoutError('OVERTIME_ARCHIVE_READ_DEADLINE')
        receipt=store.read_source(ref)
        if receipt['ingested_at_utc']>now:continue
        catalog=native_catalog(receipt,league,year)
        if digest(catalog['payload']['fixtures'])!=ref['fixtures_sha256']:
            raise ValueError('OVERTIME_NATIVE_CATALOG_PIN')
        receipts+=1
        for versions in historical_rows([(catalog,catalog['sha256'])]):
            for row in versions:
                if row['league'].upper()!=league or row['season']!=f'{year}/{year+1}':
                    raise ValueError('OVERTIME_ARCHIVE_SCOPE_CONFLICT')
                if not row['fixture_start_utc']<available_at(row,STRICT)<=now or regulation(row) is None:continue
                key=row['fixture_id']
                sig=(row['fixture_start_utc'],row['home_team_id'],row['away_team_id'],
                     digest(row['periods']),tuple(row['final_scores']))
                if key in identity and identity[key]!=sig:conflicts.add(key);continue
                identity[key]=sig
                if key not in earliest or (available_at(row,STRICT),row['source_catalog_sha256']) < (
                    available_at(earliest[key],STRICT),earliest[key]['source_catalog_sha256']):
                    earliest[key]=row
                if len(earliest)>POLICY['maximum_games']:raise ValueError('OVERTIME_COHORT_BUDGET')
    return [[row] for key,row in sorted(earliest.items()) if key not in conflicts],receipts,len(conflicts)

def audit(store,league,year):
    if league not in DURATION or type(year) is not int or not 2000<=year<=2100:
        raise ValueError('OVERTIME_LEAGUE_SEASON_REQUIRED')
    now=int(time.time());deadline=time.monotonic()+25
    rows,receipts,conflicts=earliest_rows(store,league,year,now,deadline=deadline)
    report=dict(league=league,season=f'{year}/{year+1}',native_receipts=receipts,native_games=len(rows),
                conflicting_finals_excluded=conflicts,ot_games=sum(len(v[0]['periods']['home'])>4 for v in rows),
                fit_status='NOT_AVAILABLE',fit_sha256=None,walk_forward=None,
                forecast_changed=False,live_market_admission=False)
    if not rows:
        report['fit_status']='OVERTIME_NATIVE_HISTORY_EMPTY';return report
    try:
        model=fit(rows,cutoff_utc=now)
        report['fit_status']='RESEARCH_FITTED_NOT_PROMOTED';report['fit_sha256']=model['sha256']
    except Abstain as exc:report['fit_status']=str(exc)
    if time.monotonic()>=deadline:raise TimeoutError('OVERTIME_ARCHIVE_READ_DEADLINE')
    report['walk_forward']=walk_forward(rows,asof_utc=now)
    return report

def render(r):
    lines=['ZEYNAL | UZATMA ARAŞTIRMA DENETİMİ | SALT OKUNUR',
           r['league']+' '+r['season'],
           f"Native makbuz: {r['native_receipts']} · Maç: {r['native_games']} · Uzatmalı: {r['ot_games']}",
           f"Çelişkili sonuç nedeniyle dışlanan maç: {r['conflicting_finals_excluded']}",
           'Model: '+r['fit_status']]
    if r['fit_sha256']:lines.append('Araştırma SHA: '+r['fit_sha256'])
    w=r['walk_forward']
    if w:
        lines.append('Zaman ayrımlı bağımsız uzatma testi: '+str(w['n'])+' · '+w['status'])
        if w['n']:
            lines.append('Uzatma skor hata ölçüleri: '+str(w['conditional_ot_team_scores']))
            lines.append('Uzatma kazananı olasılık ölçüleri: '+str(w['conditional_ot_winner']))
            lines.append('Eşit olasılık referansı: '+str(w['baseline_fair_ot_winner']))
        lines.append('Dışlanan testler: '+str(w['blocked']))
    lines.extend(['En erken doğrulanmış yerel sonuç zamanı kullanılır; geçmiş tarih varsayılmaz.',
                  'İlk tahmin ve normal süre değişmedi. Canlı piyasa kabulü yok. NOT_CALIBRATED.'])
    return '\n'.join(lines)

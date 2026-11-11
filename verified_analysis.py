"""Shared NBA/EuroLeague score analysis from current, pinned native sources."""
import asyncio
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime,timedelta,timezone
import hashlib
import html
import json
import os
import platform
import re
import sqlite3
from pathlib import Path
from statistics import mean,pstdev
import time
from zoneinfo import ZoneInfo

from core.team_identity import digest
from core.league_identity import resolve_league
from live_analysis_ledger import LiveAnalysisLedger
from prematch_monte_carlo import PrematchMonteCarloEngine,PrematchSimulationInput
from season_archive_collect import fetch_document
from season_archive_inventory import archive_catalog
from universal_analysis import UniversalAnalyzeService,render_preflight,require_fresh_source
from verified_history import checked_fetch,nba_history


IST=ZoneInfo('Europe/Istanbul')
MODEL_VERSION='FAZ13_SCORE_MATCHUP_PERIODS_V1'
MODEL_DIGEST=digest({f:hashlib.sha256(Path(__file__).with_name(f).read_bytes()).hexdigest()
    for f in ('verified_analysis.py','verified_history.py','prematch_monte_carlo.py')})
_receipts=ContextVar('analysis_receipts',default=None)


def project_scores(history,home_id,away_id):
    series={}
    for side,tid in [('home',home_id),('away',away_id)]:
        games=[g for g in history if tid in (g['home_team_id'],g['away_team_id'])]
        games=sorted(games,key=lambda g:(g['start_ts_utc'],g['canonical_id']))[-10:]
        if len(games)<6:raise ValueError('INSUFFICIENT_VERIFIED_HISTORY')
        pf=[g['periods']['home' if g['home_team_id']==tid else 'away'][:4] for g in games]
        pa=[g['periods']['away' if g['home_team_id']==tid else 'home'][:4] for g in games]
        series[side]=dict(n_games=len(games),game_ids=[g['canonical_id'] for g in games],
            provider_game_ids=[g['provider_fixture_ids'] for g in games],
            points_for=mean(sum(p) for p in pf),points_against=mean(sum(p) for p in pa),
            points_for_std=pstdev(sum(p) for p in pf),
            quarters_for=[mean(p[q] for p in pf) for q in range(4)],
            quarters_against=[mean(p[q] for p in pa) for q in range(4)])
    h=(series['home']['points_for']+series['away']['points_against'])/2
    a=(series['away']['points_for']+series['home']['points_against'])/2
    quarters={s:[(series[s]['quarters_for'][q]+series['away' if s=='home' else 'home']['quarters_against'][q])/2
        for q in range(4)] for s in ('home','away')}
    halves={s:[sum(quarters[s][:2]),sum(quarters[s][2:])] for s in ('home','away')}
    simulation=None
    if min(series[s]['points_for_std'] for s in series)>0:
        simulation=asdict(PrematchMonteCarloEngine().simulate(PrematchSimulationInput(
            home_mean=h,away_mean=a,home_std=series['home']['points_for_std'],away_std=series['away']['points_for_std'],
            score_correlation=0.0,shared_pace_std=0.0,simulations=10000,seed=20261108)))
    return dict(home=h,away=a,total=h+a,margin=h-a,home_handicap=-h+a,quarters=quarters,halves=halves,
        simulation=simulation,home_win_probability=None if simulation is None else simulation['home_regulation_win_probability']),series


class VerifiedAnalyzeService:
    def __init__(self,ledger,fetcher=fetch_document,*,release_sha='UNKNOWN',ledger_factory=None,configuration_error=None):
        self.ledger=ledger;self.transport=fetcher;self.release_sha=release_sha;self.cache={}
        self.ledger_factory=ledger_factory
        self.configuration_error=configuration_error
        self.cache_sizes={}
        self.identity=UniversalAnalyzeService(fetcher=self.fetch)

    def fetch(self,provider,url):
        now=int(time.time())
        for key,value in list(self.cache.items()):
            if not 0<=now-value['observed_at_utc']<240:
                self.cache.pop(key,None);self.cache_sizes.pop(key,None)
        cached=self.cache.get((provider,url))
        if cached and 0<=now-cached['observed_at_utc']<240:r=deepcopy(cached)
        else:
            r=self.transport(provider,url)
            if r.get('status')=='DOCUMENT_RECEIVED':
                size=len(json.dumps(r['document']).encode())
                while self.cache and (len(self.cache)>=32 or sum(self.cache_sizes.values())+size>16*1024*1024):
                    oldest=min(self.cache,key=lambda k:self.cache[k]['observed_at_utc'])
                    self.cache.pop(oldest);self.cache_sizes.pop(oldest,None)
                if size<=16*1024*1024:
                    self.cache[(provider,url)]=deepcopy(r);self.cache_sizes[(provider,url)]=size
        receipts=_receipts.get()
        if receipts is not None and r.get('status')=='DOCUMENT_RECEIVED':receipts.append({k:v for k,v in r.items() if k!='document'})
        return r

    async def list_nba_games(self,day):
        from nba_command import parse_espn_scoreboard,utc_dates_for_turkey_day
        games={}
        for date in utc_dates_for_turkey_day(day):
            u='https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates='+date.replace('-','')+'&limit=1000'
            r=await asyncio.to_thread(checked_fetch,self.fetch,'ESPN',u)
            statuses={e['id']:e.get('status',{}).get('type',{}) for e in r['document']['events']}
            for g in parse_espn_scoreboard(r['document'],day):
                status=statuses[g['id']]
                g['status']=('Tamamlandı' if status.get('completed') is True else 'Canlı' if status.get('state')=='in' else
                    'Başlamadı' if status.get('name')=='STATUS_SCHEDULED' else 'Ertelendi / durum doğrulanmalı')
                games[g['id']]=g
        return sorted(games.values(),key=lambda g:g['start'])

    async def analyze(self,league,day,home,away):
        token=_receipts.set([])
        try:
            if self.configuration_error:return dict(status='ABSTAIN',html=html.escape(self.configuration_error))
            if resolve_league(league).code not in ('NBA','EUROLEAGUE'):
                return dict(status='ABSTAIN',html='Bu lig için doğrulanmış analiz motoru henüz bağlı değil. LEAGUE_MODEL_NOT_CONFIGURED')
            report=await self.identity.preflight(league,day,home,away)
            ready=(report['status']=='VERIFIED_NBA_FIXTURE' or report.get('reason')=='VERIFIED_PACE_AND_PROSPECTIVE_MODEL_ARCHIVE_NOT_CONFIGURED')
            if not ready:return dict(status='ABSTAIN',html=html.escape(render_preflight(report)),preflight=report)
            if self.ledger is None and self.ledger_factory is not None:self.ledger=await asyncio.to_thread(self.ledger_factory)
            if self.ledger is None:return dict(status='ABSTAIN',html='Kalıcı tahmin arşivi kullanılamıyor; tahmin kaydedilmedi. ARCHIVE_UNAVAILABLE')
            g=report['fixture'];code=report['league'];year=int(report['season_id'].split('/')[0])
            old=await asyncio.to_thread(self.ledger.get,code,g['canonical_id'],MODEL_DIGEST)
            if old:
                if int(time.time())>=g['start_ts_utc']:raise ValueError('TIPOFF_BEFORE_CACHED_RESPONSE')
                return dict(status='ANALYSIS_OK',snapshot=old,new_record=False,html=render_analysis(old))
            snapshot=await asyncio.to_thread(self.identity.participants.load,code,year)
            inputs=list(snapshot['payload']['source_pins'].values())
            if code=='NBA':
                games=[]
                for team in (report['home'],report['away']):
                    rows,pins=await asyncio.to_thread(nba_history,self.fetch,team['provider_id'],year,int(time.time()),
                        result_sink=lambda b:self.ledger.reconcile(b,trusted_sha256=b['sha256']))
                    games.extend(rows);inputs.extend(pins)
                unique={}
                for row in games:
                    cid=row['canonical_id']
                    if cid in unique and unique[cid]!=row:raise ValueError('CONFLICTING_TEAM_HISTORY_SOURCES')
                    unique[cid]=row
                games=list(unique.values())
            else:
                url=f'https://api-live.euroleague.net/v2/competitions/E/seasons/E{year}/games'
                r=await asyncio.to_thread(checked_fetch,self.fetch,'EUROLEAGUE_LIVE',url)
                cat=archive_catalog(r['document'],provider='EUROLEAGUE_LIVE',season_start_year=year,
                    observed_at_utc=r['observed_at_utc'],ingested_at_utc=r['ingested_at_utc'])
                await asyncio.to_thread(self.ledger.reconcile,cat,trusted_sha256=cat['sha256'])
                games=[v for v in cat['payload']['fixtures'] if v['completed'] and v['periods'] is not None and v['start_ts_utc']<int(time.time())]
            prediction,series=await asyncio.to_thread(project_scores,games,report['home']['provider_id'],report['away']['provider_id'])
            # Fresh authoritative fixture recheck before the short SQLite transaction.
            for key in list(self.cache):
                if '/scoreboard?' in key[1] or key[1].endswith('/games'):
                    self.cache.pop(key,None);self.cache_sizes.pop(key,None)
            checked=await self.identity.preflight(code,day,home,away)
            if checked.get('fixture')!=g or checked.get('reason') not in (None,'VERIFIED_PACE_AND_PROSPECTIVE_MODEL_ARCHIVE_NOT_CONFIGURED'):
                raise ValueError('FIXTURE_CHANGED_DURING_ANALYSIS')
            inputs.extend(_receipts.get())
            pins=sorted({digest(p):p for p in inputs}.values(),key=digest)
            for pin in pins:require_fresh_source(pin)
            payload=dict(record_type='LIVE_PREMATCH_PREDICTION',evaluation_class='LIVE_RECORDED',actual=None,
                league=code,season=report['season_id'],fixture_id=g['canonical_id'],provider_fixture_ids=g['provider_fixture_ids'],
                fixture_start_utc=g['start_ts_utc'],home=report['home'],away=report['away'],scope='REGULATION_ONLY',
                model_version=MODEL_VERSION,model_digest=MODEL_DIGEST,release_sha=self.release_sha,
                runtime_python=platform.python_version(),
                prediction=prediction,history=series,input_clocks=pins,source_digest=digest(pins),provider=report['provider'],
                missing_data=['pace','injuries','lineups','rotation','market'],calibration_status='NOT_CALIBRATED')
            saved,created=await asyncio.to_thread(self.ledger.commit,payload)
            return dict(status='ANALYSIS_OK',snapshot=saved,new_record=created,html=render_analysis(saved))
        except (ValueError,KeyError,TypeError,OSError) as exc:
            return dict(status='ABSTAIN',html='Analiz kaydedilmedi: '+html.escape(str(exc) if isinstance(exc,ValueError) else 'SOURCE_OR_ARCHIVE_ERROR'))
        except sqlite3.Error:
            return dict(status='ABSTAIN',html='Analiz kaydedilmedi: ARCHIVE_LOCKED_OR_UNAVAILABLE')
        finally:_receipts.reset(token)


def render_analysis(p):
    esc=html.escape;x=p['prediction'];h=esc(p['home']['official_name']);a=esc(p['away']['official_name'])
    start=datetime.fromtimestamp(p['fixture_start_utc'],IST);created=datetime.fromtimestamp(p['created_at_utc'],IST)
    lines=[f"<b>🏀 {esc(p['league'])} | MAÇ ÖNCESİ ANALİZ</b>",f'{h} – {a}',
        f"Başlangıç: {start:%d.%m.%Y %H:%M} TSİ | Normal süre: {'48' if p['league']=='NBA' else '40'} dk",
        f"<b>Skor: {x['home']:.2f} – {x['away']:.2f} | Toplam: {x['total']:.2f}</b>",
        f"Ev sahibi farkı: {x['margin']:+.2f} | Model handikabı (ev): {x['home_handicap']:+.2f}",
        f"1H: {x['halves']['home'][0]:.2f} – {x['halves']['away'][0]:.2f}",
        f"2H: {x['halves']['home'][1]:.2f} – {x['halves']['away'][1]:.2f}"]
    lines.extend(f"{q+1}Q: {x['quarters']['home'][q]:.2f} – {x['quarters']['away'][q]:.2f}" for q in range(4))
    sim=x.get('simulation')
    if sim:
        lines.extend([f"Monte Carlo: {sim['simulations']:,} senaryo | seed {sim['seed']}",
            f"Normal süre: Ev %{100*sim['home_regulation_win_probability']:.1f} | Dep %{100*sim['away_regulation_win_probability']:.1f} | Eşitlik %{100*sim['regulation_tie_probability']:.1f}",
            f"Toplam P05–P95: {sim['total_quantiles']['p05']:.1f}–{sim['total_quantiles']['p95']:.1f}"])
    else:lines.append('Monte Carlo: doğrulanmış skor varyansı yetersiz; hesaplanmadı.')
    lines.extend([f"Geçmiş maç: Ev {p['history']['home']['n_games']} | Dep {p['history']['away']['n_games']}",
        f"Kaynak: {esc(p['provider'])} | Tempo, kadro, sakatlık, rotasyon ve piyasa doğrulanmadı.",
        'Skor modeli geçmiş atılan/yenilen sayıları kullanır; çeyrekler geçmiş periyot ortalamalarıdır.',
        'Olasılıklar kalibre edilmedi; skor korelasyonu 0 varsayımıdır. Uzatma dahil değil.',
        f"Kayıt: {created:%d.%m.%Y %H:%M:%S} TSİ | LIVE_PREMATCH_PREDICTION",
        f"Model: {esc(p['model_version'])} | SHA {p['model_digest'][:12]}",
        f"Kaynak SHA: {p['source_digest'][:12]} | Kayıt SHA: {digest(p)[:12]}"])
    return '\n'.join(lines)


def production_service():
    path=os.getenv('PREDICTION_LEDGER_DB','/data/prediction_ledger.sqlite')
    p=Path(path).absolute()
    sha=os.getenv('ZEYNAL_RELEASE_SHA','UNKNOWN')
    if re.fullmatch('[0-9a-f]{40}',sha) is None:
        return VerifiedAnalyzeService(None,release_sha=sha,configuration_error='RELEASE_SHA_NOT_CONFIGURED')
    def existing_ledger():
        if os.path.ismount('/data') and Path('/data') in p.parents and p.resolve()==p and p.is_file():
            return LiveAnalysisLedger(p,require_legacy=True)
        return None
    # /nba and startup stay available during a transient database lock; analysis
    # retries this factory and still refuses to send an unarchived prediction.
    return VerifiedAnalyzeService(None,release_sha=sha,ledger_factory=existing_ledger)

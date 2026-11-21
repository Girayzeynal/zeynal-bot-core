"""Separate offline E/U team hierarchies; no NBA/other-league parameter transfer."""
import argparse
import hashlib
import json
from pathlib import Path
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np

from core.league_identity import resolve_league
from core.team_identity import digest
from historical_research import historical_rows
from hybrid_engine.boxes import publish_json
from hybrid_engine.data import STRICT, Abstain, available_at, local_path, regulation
from hybrid_engine.models import HierarchicalStrength
from hybrid_engine.source_policy import ControlledTransport
from season_archive_collect import fetch_document
from season_archive_inventory import archive_catalog

VERSION='EUROPE_OFFLINE_TEAM_BAYES_V1'


def specification(league,year):
    s=resolve_league(league)
    if s.code not in ('EUROLEAGUE','EUROCUP') or type(year) is not int or not 2000<=year<=2100:
        raise ValueError('EUROPE_COMPETITION_AND_SEASON_REQUIRED')
    return s


def season_url(league,year):
    s=specification(league,year)
    return f'https://api-live.euroleague.net/v2/competitions/{s.competition_code}/seasons/{s.competition_code}{year}/games'


def catalog(receipt,league,year,*,max_age=240):
    s=specification(league,year);now=int(time.time())
    if (receipt.get('provider')!='EUROLEAGUE_LIVE' or receipt.get('source_url')!=season_url(league,year) or
            receipt.get('status')!='DOCUMENT_RECEIVED' or receipt.get('http_status')!=200 or
            digest(receipt['document'])!=receipt.get('document_sha256') or
            any(type(receipt.get(k)) is not int for k in ('observed_at_utc','ingested_at_utc')) or
            not 0<receipt['observed_at_utc']<=receipt['ingested_at_utc']<=now or
            (max_age is not None and now-receipt['observed_at_utc']>max_age)):
        raise ValueError('EUROPE_NATIVE_SOURCE_BINDING_OR_CLOCK')
    return archive_catalog(receipt['document'],provider='EUROLEAGUE_LIVE',competition_code=s.competition_code,
        season_start_year=year,observed_at_utc=receipt['observed_at_utc'],ingested_at_utc=receipt['ingested_at_utc'])


def past_rows(bundle,cutoff):
    cohort=historical_rows([(bundle,bundle['sha256'])])
    return [max(v,key=lambda r:available_at(r,STRICT)) for v in cohort if v and
            all(r['fixture_start_utc']<available_at(r,STRICT)<=cutoff and regulation(r) is not None for r in v)]


def pins():
    root=Path(__file__).parent
    return {name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in
        ('europe_models.py','europe_live.py','models.py','data.py','distributions.py','intervals.py')}


def prepare(directory,league,year,receipt):
    s=specification(league,year);b=catalog(receipt,league,year);cutoff=int(time.time());rows=past_rows(b,cutoff)
    model=HierarchicalStrength().fit(rows,cutoff_utc=cutoff,mode=STRICT)
    root=local_path(directory);root.mkdir(parents=True,exist_ok=True)
    ref=dict(file='training-'+digest(receipt)+'.json',sha256=digest(receipt));publish_json(root/ref['file'],receipt)
    p=dict(format=VERSION,league=s.code,season=f'{year}/{year+1}',prepared_at_utc=int(time.time()),
        model=model.artifact(),model_sha256=model.artifact_digest,training_source=ref,source_pins=pins(),
        training_games=len(rows),source_catalog_sha256=b['sha256'],training_in_request=False,
        calibration_status='NOT_CALIBRATED',confidence_index=None,production_enabled=False)
    pin=digest(p);path=root/f'prepared-{s.code}-{year}-{pin}.json'
    publish_json(path,dict(payload=p,sha256=pin))
    return dict(status='PREPARED',league=s.code,path=str(path),sha256=pin,training_games=len(rows),
        parameter_fit_cutoff_utc=cutoff,production_changed=False)


class PreparedEurope:
    def __init__(self,directory,league,year):
        root=local_path(directory);s=specification(league,year);choices=[]
        for path in root.glob(f'prepared-{s.code}-{year}-*.json'):
            if len(choices)>=128:raise ValueError('EUROPE_MODEL_SCAN_BUDGET')
            path=local_path(path)
            if path.stat().st_size>2*1024*1024:raise ValueError('EUROPE_MODEL_SIZE_BUDGET')
            w=json.loads(path.read_text());p=w['payload']
            if digest(p)!=w['sha256'] or path.stem!=f'prepared-{s.code}-{year}-'+w['sha256']:
                raise ValueError('EUROPE_PREPARED_MODEL_PIN')
            choices.append(w)
        if not choices:raise Abstain('EUROPE_OFFLINE_PREPARATION_REQUIRED')
        w=max(choices,key=lambda x:(x['payload']['prepared_at_utc'],x['sha256']));p=w['payload'];a=p['model'];now=int(time.time())
        identity=('EuroLeague' if s.code=='EUROLEAGUE' else 'EuroCup',f'{year}/{year+1}')
        if (p['format']!=VERSION or p['league']!=s.code or p['season']!=identity[1] or tuple(a['identity'])!=identity or
                a['players'] or a['mode']!=STRICT or p['source_pins']!=pins() or digest(a)!=p['model_sha256'] or
                not 0<a['training_available_max']<=a['cutoff_utc']<=p['prepared_at_utc']<=now or
                now-p['prepared_at_utc']>3*86400 or p['production_enabled'] is not False):
            raise ValueError('EUROPE_MODEL_SCOPE_SOURCE_OR_AGE')
        ref=p['training_source']
        if Path(ref['file']).name!=ref['file']:raise ValueError('EUROPE_TRAINING_ASSET_PATH')
        source=local_path(root/ref['file'])
        if source.stat().st_size>8*1024*1024:raise ValueError('EUROPE_TRAINING_SOURCE_BUDGET')
        receipt=json.loads(source.read_text())
        if digest(receipt)!=ref['sha256']:raise ValueError('EUROPE_TRAINING_SOURCE_PIN')
        b=catalog(receipt,s.code,year,max_age=None);rows=past_rows(b,a['cutoff_utc'])
        trace=digest([dict(id=r['fixture_id'],scores=regulation(r),source=r['source_catalog_sha256'],
            available=available_at(r,STRICT)) for r in rows])
        if (p['source_catalog_sha256']!=b['sha256'] or a['training_ids']!=sorted(r['fixture_id'] for r in rows) or
                a['training_digest']!=trace or p['training_games']!=len(rows) or len(rows)<30):
            raise ValueError('EUROPE_TRAINING_TRACE_CONFLICT')
        n=2+2*len(a['teams']);coef=np.asarray(a['coefficients']);cov=np.asarray(a['covariance'])
        if (not 1<=len(a['teams'])<=64 or len(set(a['teams']))!=len(a['teams']) or coef.shape!=(n,) or cov.shape!=(n,n) or
                not np.isfinite(coef).all() or not np.isfinite(cov).all() or not np.allclose(cov,cov.T) or
                not 0<a['noise_variance']<10000):raise ValueError('EUROPE_MODEL_PARAMETER_BUDGET')
        try:np.linalg.cholesky(cov)
        except np.linalg.LinAlgError as exc:raise ValueError('EUROPE_MODEL_COVARIANCE') from exc
        m=HierarchicalStrength();m.identity=identity;m.mode=STRICT;m.cutoff=a['cutoff_utc'];m.teams=a['teams']
        m.team_index={t:i for i,t in enumerate(m.teams)};m.players=[];m.player_index={};m.duration=40
        m.coefficients=coef;m.covariance=cov;m.noise_variance=a['noise_variance'];m.training_ids=a['training_ids']
        m.artifact_digest=p['model_sha256'];m.fitted=True
        self.model=m;self.wrapper=w;self.receipt=receipt;self.sha256=w['sha256'];self.year=year;self.league=s.code


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--directory',required=True)
    p.add_argument('--league',default='ALL');p.add_argument('--year',type=int);a=p.parse_args()
    now=datetime.now(ZoneInfo('Europe/Istanbul'));year=a.year if a.year is not None else now.year-(now.month<7)
    leagues=('EUROLEAGUE','EUROCUP') if a.league.upper()=='ALL' else (resolve_league(a.league).code,)
    fetch=ControlledTransport(fetch_document);results=[]
    for league in leagues:
        try:results.append(prepare(a.directory,league,year,fetch('EUROLEAGUE_LIVE',season_url(league,year))))
        except (ValueError,KeyError,TypeError,OSError) as exc:
            results.append(dict(league=league,status='BLOCKED',error_type=type(exc).__name__,reason='OFFICIAL_HISTORY_OR_MODEL_PREPARATION_FAILED'))
    print(json.dumps(dict(results=results,training_in_telegram=False,production_changed=False),sort_keys=True))
    return 0 if all(r['status']=='PREPARED' for r in results) else 2


if __name__=='__main__':raise SystemExit(main())

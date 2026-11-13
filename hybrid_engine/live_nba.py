"""Opt-in isolated NBA pregame inference; Bayesian fitting is an offline CLI task."""
import argparse
import asyncio
from dataclasses import asdict,replace
import gzip
import hashlib
import html
import json
from pathlib import Path
import sqlite3
import time

import numpy as np

from core.team_identity import digest
from historical_research import historical_rows
from hybrid_engine.boxes import publish_json
from hybrid_engine.confidence import confidence_index
from hybrid_engine.data import STRICT,Abstain,available_at,feature_cut,load_manifest,local_path,regulation
from hybrid_engine.distributions import Forecast
from hybrid_engine.elite_render import render_elite
from hybrid_engine.intervals import prediction_intervals
from hybrid_engine.models import HierarchicalStrength
from hybrid_engine.source_policy import ControlledTransport
from live_analysis_ledger import LiveAnalysisLedger
from projection_integrity import assert_projection
from season_archive_collect import fetch_document
from universal_analysis import render_preflight,require_fresh_source
from verified_analysis import VerifiedAnalyzeService
from verified_history import nba_history

VERSION='ELITE_HYBRID_NBA_BAYES_QMC_RESEARCH_V1'


def sampler_pins():
    root=Path(__file__).parent
    return {n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in
        ('models.py','distributions.py','data.py','live_nba.py','../verified_history.py','../universal_analysis.py')}


def prepare_rows(rows,*,cutoff,provenance):
    """No target fixture or test outcome enters offline parameter estimation."""
    if not rows or any(r['league']!='NBA' or r['fixture_start_utc']>=cutoff or
        not r['fixture_start_utc']<max(r['observed_at_utc'],r['ingested_at_utc'])<=cutoff for r in rows):
        raise ValueError('OFFLINE_NATIVE_PAST_LABELS_REQUIRED')
    model=HierarchicalStrength().fit(rows,cutoff_utc=cutoff,mode=STRICT)
    p=dict(format='NBA_OFFLINE_BAYES_PREPARED_V1',prepared_at_utc=int(time.time()),model=model.artifact(),
        model_sha256=model.artifact_digest,source_code_pins=sampler_pins(),
        provenance={k:provenance[k] for k in ('manifest_sha256','source_pins','data_class','source_permission','fixture_kind') if k in provenance},
        training_rows=[dict(fixture_id=r['fixture_id'],start_utc=r['fixture_start_utc'],
            observed_at_utc=r['observed_at_utc'],ingested_at_utc=r['ingested_at_utc'],
            catalog_sha256=r['source_catalog_sha256'],regulation_scores=regulation(r)) for r in rows],
        acceptance='RESEARCH_ONLY_NOT_A_PROMOTION_OR_CALIBRATION',training_in_request=False)
    return dict(payload=p,sha256=digest(p))


class PreparedBayes:
    def __init__(self,path,*,trusted_sha256):
        path=local_path(path)
        if path.stat().st_size>4*1024*1024:raise ValueError('PREPARED_ARTIFACT_SIZE_BUDGET')
        w=json.loads(path.read_text());p=w['payload'];a=p['model'];now=int(time.time())
        if w['sha256']!=trusted_sha256 or digest(p)!=trusted_sha256 or digest(a)!=p['model_sha256']:
            raise ValueError('PREPARED_ARTIFACT_TRUSTED_PIN')
        if p['format']!='NBA_OFFLINE_BAYES_PREPARED_V1' or p['source_code_pins']!=sampler_pins():
            raise ValueError('PREPARED_SOURCE_OR_FORMAT_CONFLICT')
        if (a['format']!='BAYES_HIERARCHY_ARTIFACT_V1' or a['identity'][0]!='NBA' or a['mode']!=STRICT or
            a['players'] or not 0<a['training_available_max']<=a['cutoff_utc']<=p['prepared_at_utc']<=now or
            not 1<=len(a['teams'])<=30 or len(set(a['teams']))!=len(a['teams']) or
            len(a['training_ids'])<30 or len(set(a['training_ids']))!=len(a['training_ids'])):
            raise ValueError('PREPARED_SCOPE_CLOCK_OR_TRAINING_CONFLICT')
        if sorted(r['fixture_id'] for r in p['training_rows'])!=a['training_ids'] or any(
            not 0<r['start_utc']<r['observed_at_utc']<=r['ingested_at_utc']<=a['cutoff_utc'] for r in p['training_rows']):
            raise ValueError('PREPARED_TRAINING_TRACE_CONFLICT')
        size=2+2*len(a['teams']);coef=np.asarray(a['coefficients'],dtype=float);cov=np.asarray(a['covariance'],dtype=float)
        if (coef.shape!=(size,) or cov.shape!=(size,size) or not np.isfinite(coef).all() or
            not np.isfinite(cov).all() or not np.allclose(cov,cov.T) or
            np.linalg.eigvalsh(cov).min()<=0 or not np.isfinite(a['noise_variance']) or a['noise_variance']<=0):
            raise ValueError('PREPARED_NUMERIC_PARAMETERS_INVALID')
        model=HierarchicalStrength();model.identity=tuple(a['identity']);model.mode=STRICT;model.cutoff=a['cutoff_utc']
        model.teams=a['teams'];model.team_index={t:i for i,t in enumerate(a['teams'])};model.players=[];model.player_index={}
        model.duration=48;model.coefficients=coef;model.covariance=cov;model.noise_variance=a['noise_variance']
        model.training_ids=a['training_ids'];model.artifact_digest=p['model_sha256'];model.fitted=True
        self.model=model;self.payload=p;self.sha256=trusted_sha256
        self.digest=digest(dict(version=VERSION,prepared_artifact=trusted_sha256,seed=20261112,scenarios=10000,source_code_pins=sampler_pins()))


class LiveNBAHybridService:
    def __init__(self,directory,prepared,*,fetcher=fetch_document):
        self.root=local_path(directory);self.root.mkdir(parents=True,exist_ok=True)
        self.assets=self.root/'assets';self.assets.mkdir(exist_ok=True)
        self.prepared=prepared;self.ledger=LiveAnalysisLedger(self.root/'nba-hybrid.sqlite')
        self.prepared_asset=self._asset('prepared',dict(payload=prepared.payload,sha256=prepared.sha256))
        # History summaries are large. Keep one collector document and at most
        # 1 MiB fallback data, rather than two 16 MiB parsed-document caches.
        self.transport=ControlledTransport(fetcher,max_cache_bytes=1024*1024)
        self.collector=VerifiedAnalyzeService(None,fetcher=self._fetch)
        self.sources={};self.source_refs_by_url={};self.lock=asyncio.Lock();self.deadline=None

    def _check_budget(self):
        if self.deadline is not None and time.monotonic()>self.deadline:raise ValueError('LIVE_REQUEST_TIME_BUDGET')

    def _asset(self,kind,value):
        pin=digest(value);path=self.assets/(kind+'-'+pin+'.json')
        publish_json(path,value)
        return dict(file=path.name,sha256=pin)

    def _fetch(self,provider,url):
        self._check_budget()
        if provider!='ESPN':raise ValueError('NBA_NATIVE_SOURCE_REQUIRED')
        self.collector.cache.clear();self.collector.cache_sizes.clear()
        r=self.transport(provider,url)
        self._check_budget()
        if r.get('status')=='DOCUMENT_RECEIVED':
            ref=self._asset('source',r);self.sources[digest(r)]=ref
            self.source_refs_by_url[url]=(ref,r['observed_at_utc'],r['ingested_at_utc'],r['document_sha256'])
        return r

    def _inputs(self,report):
        catalogs=[];pins=[];g=report['fixture'];year=int(report['season_id'].split('/')[0])
        membership=self.collector.identity.participants.load('NBA',year)
        for pin in membership['payload']['source_pins'].values():
            ref,observed,ingested,document=self.source_refs_by_url[pin['url']]
            if (observed,ingested,document)!=(pin['observed_at_utc'],pin['ingested_at_utc'],pin['document_sha256']):
                raise ValueError('PARTICIPANT_SOURCE_ASSET_CONFLICT')
            self.sources[ref['sha256']]=ref
        for side in ('home','away'):
            _,p=nba_history(self.collector.fetch,report[side]['provider_id'],year,int(time.time()),result_sink=catalogs.append)
            pins.extend(p)
        cohort=historical_rows([(c,c['sha256']) for c in catalogs])
        now=int(time.time())
        target=dict(league='NBA',season=report['season_id'],fixture_id=g['canonical_id'],fixture_start_utc=g['start_ts_utc'],
            home_team_id=g['home_team_id'],away_team_id=g['away_team_id'])
        if target['fixture_id'] in self.prepared.model.training_ids:raise ValueError('TARGET_IN_OFFLINE_TRAINING')
        cut=feature_cut(cohort,target,mode=STRICT)
        if any(r['fixture_id']==target['fixture_id'] or available_at(r,STRICT)>now for r in cut.history):
            raise ValueError('LIVE_FEATURE_CUTOFF_LEAKAGE')
        cut=replace(cut,cutoff_utc=now)
        for r in self.collector.cache.values():
            require_fresh_source(r)
            self.sources[digest(r)]=self._asset('source',r)
        asset=self._asset('input-cut',asdict(cut))
        return cut,pins,asset

    def _predict(self,cut):
        qmc=self.prepared.model.predict(cut,method='RQMC_HALTON',bounded_workspace=True)
        mc=self.prepared.model.predict(cut,method='MC',bounded_workspace=True)
        assert_projection(qmc.summary());bands=prediction_intervals(qmc)
        return qmc,bands,dict(method='SAME_POSTERIOR_MC_VS_QMC_NOT_ACCURACY_EVIDENCE',
            mc=mc.summary(),mc_bands=prediction_intervals(mc),qmc_sample_sha256=bands['sample_sha256'])

    def _render(self,p,new):
        for ref in [p['input_asset'],p['prepared_asset'],*p['source_assets']]:
            path=local_path(self.assets/ref['file'])
            if path.parent!=self.assets or digest(json.loads(path.read_text()))!=ref['sha256']:
                raise ValueError('LIVE_INPUT_ASSET_PIN_CONFLICT')
        forecast=Forecast(p['model_version'],np.array(p['prediction']['quarters']),metadata=p['prediction']['metadata'])
        record=dict(league='NBA',fixture=dict(home_name=p['home']['official_name'],away_name=p['away']['official_name'],
            start_ts_utc=p['fixture_start_utc']),created_at_utc=p['created_at_utc'],
            prediction_generated_at_utc=p['prediction_generated_at_utc'],source_data_time_utc=p['source_data_time_utc'],
            official_source=p['fixture_source_url'],models={'BAYES_QMC':dict(model_digest=p['model_digest'])})
        parts=render_elite(record,forecast,p['intervals'],p['confidence'],live=True,prediction=p['prediction'])
        return dict(status='ANALYSIS_OK',snapshot=p,new_record=new,html=parts[0],html_parts=parts)

    async def analyze(self,league,day,home,away):
        async with self.lock:
            try:
                if league.upper()!='NBA':raise ValueError('NBA_LIVE_SCOPE_REQUIRED')
                self.sources={};self.deadline=time.monotonic()+90
                report=await self.collector.identity.preflight('NBA',day,home,away)
                if report['status']!='VERIFIED_NBA_FIXTURE':return dict(status='ABSTAIN',html=html.escape(render_preflight(report)),preflight=report)
                g=report['fixture'];old=await asyncio.to_thread(self.ledger.get,'NBA',g['canonical_id'],self.prepared.digest)
                if old:
                    if int(time.time())>=g['start_ts_utc']:raise ValueError('TIPOFF_BEFORE_CACHED_RESPONSE')
                    return self._render(old,False)
                cut,pins,asset=await asyncio.to_thread(self._inputs,report)
                forecast,bands,comparison=await asyncio.to_thread(self._predict,cut)
                simulated=int(time.time())
                # Re-fetch authoritative fixture status before durable commit.
                self.collector.cache.clear();self.collector.cache_sizes.clear();self.transport.cache.clear()
                checked=await self.collector.identity.preflight('NBA',day,home,away)
                if checked['status']!='VERIFIED_NBA_FIXTURE' or checked.get('fixture')!=g:raise ValueError('FIXTURE_CHANGED_DURING_ANALYSIS')
                for ref in self.sources.values():
                    r=json.loads((self.assets/ref['file']).read_text());pins.append({k:v for k,v in r.items() if k!='document'})
                pins=sorted({digest(p):p for p in pins}.values(),key=digest)
                for pin in pins:require_fresh_source(pin)
                generated=int(time.time())
                q=confidence_index(context=dict(prediction_utc=generated,model_digest=self.prepared.digest,
                    minimum_team_history=min(cut.features[s]['n_games'] for s in ('home','away')),verified_roster_and_rotation=False))
                payload=dict(record_type='LIVE_PREMATCH_PREDICTION',evaluation_class='LIVE_RECORDED',actual=None,
                    league='NBA',season=report['season_id'],fixture_id=g['canonical_id'],provider_fixture_ids=g['provider_fixture_ids'],
                    fixture_start_utc=g['start_ts_utc'],record_deadline_utc=g['start_ts_utc'],scope='REGULATION_ONLY',
                    home=report['home'],away=report['away'],model_version=VERSION,model_digest=self.prepared.digest,
                    prediction=forecast.summary(),intervals=bands,confidence=q,calibration_status='NOT_CALIBRATED',
                    prediction_generated_at_utc=generated,input_clocks=pins,source_data_time_utc=max(p['ingested_at_utc'] for p in pins),
                    simulation_completed_at_utc=simulated,feature_cutoff_utc=cut.cutoff_utc,
                    source_digest=digest(pins),provider='ESPN',input_asset=asset,source_assets=list(self.sources.values()),
                    prepared_artifact_sha256=self.prepared.sha256,parameter_fit_cutoff_utc=self.prepared.model.cutoff,
                    prepared_asset=self.prepared_asset,
                    fixture_source_url=next(p['source_url'] for p in pins if '/scoreboard?' in p.get('source_url','')),
                    mc_qmc=comparison,production=False,missing_data=['verified_pace','injuries','lineups','rotation','market'],
                    history={s:dict(n_games=cut.features[s]['n_games'],game_ids=cut.features[s]['recent_game_ids']) for s in ('home','away')})
                self._check_budget()
                saved,new=await asyncio.to_thread(self.ledger.commit,payload)
                return self._render(saved,new)
            except (ValueError,KeyError,TypeError,OSError,sqlite3.Error) as exc:
                return dict(status='ABSTAIN',html='İzole NBA hibrit analiz kaydedilmedi: '+html.escape(str(exc) if isinstance(exc,ValueError) else 'SOURCE_OR_ARCHIVE_ERROR'))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--prepare-manifest',required=True);p.add_argument('--output-directory',required=True)
    args=p.parse_args();cohort,provenance=load_manifest(args.prepare_manifest);now=int(time.time());rows=[]
    for versions in cohort:
        candidates=[r for r in versions if r['league']=='NBA' and r['season']=='2026/2027' and r.get('_native_truth',True) and
            regulation(r) is not None and r['fixture_start_utc']<now and max(r['observed_at_utc'],r['ingested_at_utc'])<=now]
        if candidates:rows.append(max(candidates,key=lambda r:r['ingested_at_utc']))
    artifact=prepare_rows(rows,cutoff=now,provenance=provenance)
    root=local_path(args.output_directory);root.mkdir(parents=True,exist_ok=True);path=root/('nba-prepared-'+artifact['sha256']+'.json')
    publish_json(path,artifact);print(json.dumps(dict(path=str(path),sha256=artifact['sha256'],training_games=len(rows),training_in_request=False)))


if __name__=='__main__':main()

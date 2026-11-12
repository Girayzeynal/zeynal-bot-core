"""Read-only prospective records and deterministic inference replay. Never creates PREMATCH."""
from dataclasses import replace
import gzip
import hashlib
import html
import json
from pathlib import Path
import re
import time
import unicodedata

import numpy as np

from core.team_identity import digest
from hybrid_engine.data import Cut,local_path
from hybrid_engine.evaluation import v1_forecast
from hybrid_engine.models import HierarchicalStrength
from hybrid_engine.possession import PossessionModel
from season_archive_inventory import archive_catalog
from telegram_delivery import tsi
from projection_integrity import assert_projection


def read_gzip(path,maximum=8*1024*1024):
    # A single read(maximum+1) reserves an 8 MiB buffer even for a tiny file.
    # Stream bounded chunks so the cap is a refusal limit, not an allocation.
    chunks=[];size=0
    with gzip.open(path,'rb') as f:
        while True:
            part=f.read(min(65536,maximum+1-size))
            if not part:break
            chunks.append(part);size+=len(part)
            if size>maximum:raise ValueError('FROZEN_INPUT_SIZE_BUDGET')
    raw=b''.join(chunks)
    if len(raw)>maximum:raise ValueError('FROZEN_INPUT_SIZE_BUDGET')
    return json.loads(raw)


def norm(value):
    return ''.join(c for c in unicodedata.normalize('NFKD',value.casefold()) if c.isalnum())


TRUSTED_FIVE_INDEX='c87489f84f5efa2c3abfae51f641bc066a6ab875f44c94bc197a0a49588b03d1'


class FrozenArchive:
    def __init__(self,directory,*,trusted_index_digest=TRUSTED_FIVE_INDEX):
        self.path=local_path(directory)
        indexes=list(self.path.glob('index-*.json'))
        if len(indexes)!=1:raise ValueError('ONE_TRUSTED_CAPTURE_INDEX_REQUIRED')
        self.index=json.loads(indexes[0].read_text())
        if indexes[0].stem!='index-'+digest(self.index) or digest(self.index)!=trusted_index_digest:raise ValueError('CAPTURE_INDEX_PIN')
        self.records={};self.files={}
        for entry in self.index['records']:
            name=entry['sha256']+'.json';p=local_path(self.path/name)
            raw=p.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=entry['file_sha256']:raise ValueError('FROZEN_FILE_PIN')
            wrapper=json.loads(raw);r=wrapper['payload']
            if digest(r)!=wrapper['sha256'] or wrapper['sha256']!=entry['sha256']:raise ValueError('FROZEN_PAYLOAD_PIN')
            g=r['fixture']
            if (r['record_type']!='REAL_PREMATCH_RESEARCH_NOT_PRODUCTION' or r['actual'] is not None or
                r['source_commit']!=self.index['source_commit'] or
                not r['source_data_time_utc']<=r['created_at_utc']<g['start_ts_utc'] or
                not r['history_available_max_utc']<=r['history_cutoff_utc']<=r['created_at_utc']):
                raise ValueError('FROZEN_PREMATCH_CLOCK_OR_KIND')
            if g['canonical_id']!=entry['fixture_id'] or g['provider_fixture_id']!=entry['provider_fixture_id']:
                raise ValueError('FROZEN_INDEX_IDENTITY')
            self._validate_inputs(r)
            for model in r['models'].values():
                if model['status']=='FORECAST_CREATED':assert_projection(model['prediction'])
            if g['canonical_id'] in self.records:raise ValueError('DUPLICATE_CAPTURE_FIXTURE')
            self.records[g['canonical_id']]=r;self.files[g['canonical_id']]=entry

    def _validate_inputs(self,r):
        for prefix,key in [('inputs-','input_file_sha256'),('official-','official_receipt_file_sha256')]:
            path=local_path(self.path/(prefix+r[key]+'.json.gz'))
            if hashlib.sha256(path.read_bytes()).hexdigest()!=r[key]:raise ValueError('FROZEN_INPUT_PIN')
        source=read_gzip(self.path/('official-'+r['official_receipt_file_sha256']+'.json.gz'))
        if digest(source['document'])!=source['document_sha256'] or source['document_sha256']!=r['official_document_sha256']:
            raise ValueError('FROZEN_NATIVE_SOURCE_PIN')
        if (source['source_url']!=r['official_source'] or source['provider']!='EUROLEAGUE_LIVE' or
            r['official_source']!='https://api-live.euroleague.net/v2/competitions/E/seasons/E2026/games' or
            source.get('status')!='DOCUMENT_RECEIVED' or source.get('http_status')!=200 or
            not 0<source['observed_at_utc']<=source['ingested_at_utc']<=r['created_at_utc']):raise ValueError('FROZEN_SOURCE_PROVIDER_OR_CLOCK')
        catalog=archive_catalog(source['document'],provider=source['provider'],season_start_year=2026,
            observed_at_utc=source['observed_at_utc'],ingested_at_utc=source['ingested_at_utc'])
        matches=[g for g in catalog['payload']['fixtures'] if g['canonical_id']==r['fixture']['canonical_id']]
        if len(matches)!=1:raise ValueError('FROZEN_NATIVE_FIXTURE_MISSING')
        g=matches[0];target=r['fixture']
        if (g['completed'] or any(g[k]!=target[k] for k in ('home_team_id','away_team_id','start_ts_utc'))):
            raise ValueError('FROZEN_NATIVE_FIXTURE_CONFLICT')

    def find(self,league,day,home,away):
        code=league.casefold()
        if code not in ('euroleague','e'):return None
        for r in self.records.values():
            g=r['fixture']
            if (g['start_iso_utc'][:10]==day and norm(home)==norm(g['home_name']) and norm(away)==norm(g['away_name'])):return r
        return None

    def replay(self,r,component='BAYES_QMC',*,cut=None):
        """Frozen coefficients/inputs; no fit, label download, promotion or archive write."""
        if cut is None:
            raw=read_gzip(self.path/('inputs-'+r['input_file_sha256']+'.json.gz'));cut=Cut(**raw)
        if cut.inputs_digest!=r['input_digest'] or cut.cutoff_utc!=r['history_cutoff_utc']:raise ValueError('FROZEN_CUT_PIN')
        if component=='BAYES_QMC':
            expected=r['models'][component]['prediction']['metadata']['artifact_digest']
            path=local_path(self.path/('bayes-'+expected+'.json'));p=json.loads(path.read_text())
            if digest(p)!=expected or p['cutoff_utc']>cut.cutoff_utc or p['training_available_max']>p['cutoff_utc']:
                raise ValueError('FROZEN_BAYES_ARTIFACT_PIN_OR_CLOCK')
            model=HierarchicalStrength();model.identity=tuple(p['identity']);model.mode=p['mode'];model.cutoff=p['cutoff_utc']
            model.teams=p['teams'];model.team_index={t:i for i,t in enumerate(p['teams'])}
            model.players=p['players'];model.player_index={t:i for i,t in enumerate(p['players'])}
            model.duration=40;model.coefficients=np.array(p['coefficients']);model.covariance=np.array(p['covariance'])
            model.noise_variance=p['noise_variance'];model.training_ids=p['training_ids'];model.artifact_digest=expected;model.fitted=True
            forecast=model.predict(cut,method='RQMC_HALTON',bounded_workspace=True)
        elif component=='FAZ13_MC':forecast=v1_forecast(cut)
        elif component in ('POSSESSION_ANALYTIC','POSSESSION_MC'):
            forecast=PossessionModel().predict(cut,method='MC' if component.endswith('_MC') else 'ANALYTIC')
        else:raise ValueError('UNKNOWN_FROZEN_COMPONENT')
        expected=r['models'][component]['prediction'];actual=forecast.summary()
        for key in ('home','away','total','margin','home_handicap','quarters','halves','winner'):
            if not np.allclose(actual[key],expected[key],atol=1e-10,rtol=1e-12):raise ValueError('FROZEN_REPLAY_REGRESSION:'+key)
        return forecast


class FrozenHybridService:
    """Isolated test bot: replay the actual immutable forecast, including after tipoff."""
    def __init__(self,archive):self.archive=archive;self.last_latency_seconds=None

    def _replay_components(self,r):
        primary=None;cut=Cut(**read_gzip(self.archive.path/('inputs-'+r['input_file_sha256']+'.json.gz')))
        for name in ('BAYES_QMC','POSSESSION_ANALYTIC','POSSESSION_MC','FAZ13_MC'):
            if r['models'].get(name,{}).get('status')!='FORECAST_CREATED':continue
            f=self.archive.replay(r,name,cut=cut)
            if name=='BAYES_QMC':primary=f
        if primary is None:raise ValueError('NO_FROZEN_PRIMARY_COMPONENT')
        return primary,min(cut.features[s]['n_games'] for s in ('home','away'))

    async def analyze(self,league,day,home,away):
        import asyncio
        r=self.archive.find(league,day,home,away)
        if r is None:return dict(status='ABSTAIN',html='İzole hibrit test arşivinde bu maç için kayıt yok. Yeni tahmin üretilmedi.')
        began=time.perf_counter();f,history_count=await asyncio.to_thread(self._replay_components,r)
        from hybrid_engine.intervals import prediction_intervals
        from hybrid_engine.confidence import confidence_index
        from hybrid_engine.elite_render import render_elite
        bands=await asyncio.to_thread(prediction_intervals,f)
        scores=np.array([[m['prediction']['home'],m['prediction']['away']] for m in r['models'].values() if m['status']=='FORECAST_CREATED'])
        quality=confidence_index(context=dict(prediction_utc=r['created_at_utc'],model_digest=r['models']['BAYES_QMC']['model_digest'],
            minimum_team_history=history_count,verified_roster_and_rotation=False,
            relative_interval_width=bands['markets']['TOTAL']['wide_width']/max(1.,f.scores.sum()),
            model_disagreement=min(1.,float(np.max(np.ptp(scores,axis=0)))/max(1.,float(scores.mean())))))
        parts=render_elite(r,f,bands,quality)
        self.last_latency_seconds=time.perf_counter()-began
        return dict(status='FROZEN_REPLAY_OK',html=parts[0],html_parts=parts,bands=bands,confidence=quality,new_record=False,
            timeline=dict(prediction_generated_at_utc=None,snapshot_created_at_utc=r['created_at_utc'],
                first_archived_at_utc=None,telegram_sent_at_utc=None,replay_completed_at_utc=int(time.time()),
                snapshot_sha256=digest(r),reused_forecast=True),record=r)

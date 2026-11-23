"""Five-minute European prematch adapter for new forecasts only.

The historical europe_live.py source pin is intentionally unchanged; this
versioned adapter reuses its original prediction/fixture validation sequence
with the newly approved lead time. Existing archive records replay unchanged.
"""
import asyncio
import time
from dataclasses import asdict, replace
from datetime import datetime

from core.league_identity import resolve_league
from core.team_identity import digest
from historical_research import historical_rows
from hybrid_engine.data import STRICT,Abstain,available_at,feature_cut
from hybrid_engine.distributions import Budget
from hybrid_engine.evaluation import v1_forecast
from hybrid_engine.europe_models import PreparedEurope,catalog,season_url
from hybrid_engine.intervals import prediction_intervals
from hybrid_engine.time_policy import PREMATCH_MINIMUM_LEAD_SECONDS
from universal_analysis import render_preflight


async def analyze(self,league,day,home,away):
    """New forward-only admission at T-300, preserving pinned model and replay flow."""
    async with self.lock:
        try:
            if resolve_league(league).code!=self.league:raise ValueError('EUROPE_SERVICE_LEAGUE_MISMATCH')
            datetime.strptime(day,'%Y-%m-%d')
            old=await asyncio.to_thread(self.existing,day,home,away)
            if old:return self.render(old)
            if self.previous is not None:
                prior,pair=await asyncio.to_thread(self.previous._find,day,home,away)
                if prior:return self.previous._render(prior,pair,new=False)
            legacy=self.legacy(day,home,away)
            if legacy is not None and self.fallback is not None:
                return await self.fallback.analyze('EUROLEAGUE',legacy['fixture']['start_iso_utc'][:10],home,away)
            check=await self.preflight.preflight(self.league,day,home,away)
            if check.get('stage')!='MODEL_INPUTS' or check.get('reason')!='VERIFIED_PACE_AND_PROSPECTIVE_MODEL_ARCHIVE_NOT_CONFIGURED':
                return dict(status='ABSTAIN',html=render_preflight(check),preflight=check)
            g=check['fixture'];year=g['season_start_year'];now=int(time.time())
            saved=next((v for v in self.registry.independent_records() if v['payload']['fixture']['canonical_id']==g['canonical_id']),None)
            if saved:return self.render(saved)
            if self.previous is not None:
                saved=next((v for v in self.previous.registry.independent_records() if v['payload']['fixture']['canonical_id']==g['canonical_id']),None)
                if saved:return self.previous._render(saved,self.previous._pair(saved['payload']),new=False)
            if g['completed'] or g['start_ts_utc']<=now+PREMATCH_MINIMUM_LEAD_SECONDS:raise Abstain('EUROPE_SAFE_PRETIPOFF_WINDOW_CLOSED')
            prepared=await asyncio.to_thread(PreparedEurope,self.models,self.league,year)
            receipt=await asyncio.to_thread(self.fetcher,'EUROLEAGUE_LIVE',season_url(self.league,year))
            b=catalog(receipt,self.league,year);cohort=historical_rows([(b,b['sha256'])]);freeze=int(time.time())
            if not any(v==g for v in b['payload']['fixtures']):raise ValueError('EUROPE_FIXTURE_CHANGED_BEFORE_SIMULATION')
            cohort=[[r for r in v if r['fixture_start_utc']<available_at(r,STRICT)<=freeze] for v in cohort]
            target=dict(league='EuroLeague' if self.league=='EUROLEAGUE' else 'EuroCup',season=f'{year}/{year+1}',
                fixture_id=g['canonical_id'],fixture_start_utc=g['start_ts_utc'],home_team_id=g['home_team_id'],away_team_id=g['away_team_id'])
            cut=replace(feature_cut(cohort,target,mode=STRICT),cutoff_utc=freeze)
            if g['canonical_id'] in prepared.model.training_ids:raise ValueError('EUROPE_TARGET_IN_TRAINING')
            def infer():
                qmc=prepared.model.predict(cut,method='RQMC_HALTON',budget=Budget(seconds=5),bounded_workspace=True)
                mc=prepared.model.predict(cut,method='MC',budget=Budget(seconds=5),bounded_workspace=True)
                reference=v1_forecast(cut)
                return {n:dict(status='FORECAST_CREATED',prediction=f.summary(),intervals=prediction_intervals(f))
                    for n,f in (('BAYES_QMC',qmc),('BAYES_MC',mc),('FAZ13_REFERENCE',reference))}
            components=await asyncio.to_thread(infer)
            latest=await asyncio.to_thread(self.fetcher,'EUROLEAGUE_LIVE',season_url(self.league,year))
            lc=catalog(latest,self.league,year)
            if not any(v==g for v in lc['payload']['fixtures']):raise ValueError('EUROPE_FIXTURE_CHANGED_DURING_SIMULATION')
            generated=int(time.time())
            if generated>=g['start_ts_utc']:raise Abstain('EUROPE_TIPOFF_DURING_SIMULATION')
            source=self.registry.asset('source',receipt);recheck=self.registry.asset('source',latest)
            model_ref=self.registry.asset('prepared',prepared.wrapper);training=self.registry.asset('training',prepared.receipt)
            cut_ref=self.registry.asset('cut',asdict(cut))
            p,new=self.registry.record(dict(format='EUROPE_COMPONENT_FORECAST_V1',fixture=g,actual=None,
                version=prepared.sha256,prediction_generated_at_utc=generated,
                source_available_max_utc=max(receipt['ingested_at_utc'],latest['ingested_at_utc'],max(available_at(r,STRICT) for r in cut.history)),
                fixture_source=source,feature_cutoff_utc=freeze,assets=[source,recheck,model_ref,training,cut_ref],
                components=components,training_in_request=False,calibration_status='NOT_CALIBRATED',confidence_index=None))
            matches=[v for v in self.registry.records() if digest(v['payload'])==digest(p)]
            if len(matches)!=1 or not matches[0]['publication']['eligible_for_prospective_audit']:
                raise ValueError('EUROPE_PREMATCH_PUBLICATION_REQUIRED')
            return self.render(matches[0],new=new)
        except Abstain as exc:
            reason=str(exc) if str(exc) in ('EUROPE_OFFLINE_PREPARATION_REQUIRED','EUROPE_SAFE_PRETIPOFF_WINDOW_CLOSED','EUROPE_TIPOFF_DURING_SIMULATION') else 'EUROPE_VERIFIED_HISTORY_INSUFFICIENT'
            return dict(status='ABSTAIN',html='Analiz durduruldu: '+reason+'\n'+
                ('İzole model hazırlığı: --prepare-europe. ' if reason=='EUROPE_OFFLINE_PREPARATION_REQUIRED' else '')+
                'Yeni PREMATCH kaydı üretilmedi; eski kayıtlar korundu.')
        except (ValueError,KeyError,TypeError,OSError):
            return dict(status='ABSTAIN',html='Avrupa lig kaynağı/modeli/arşivi doğrulanamadı. İzole --prepare-europe durumunu kontrol edin. Eski kayıtlar korundu.')


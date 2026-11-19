"""Isolated E/U inference and append-only results; parameter fitting is offline."""
import asyncio
from dataclasses import asdict,replace
import html
import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from core.league_identity import resolve_league
from core.team_identity import digest
from historical_research import historical_rows
from hybrid_engine.boxes import publish_json
from hybrid_engine.data import STRICT,Abstain,available_at,feature_cut,local_path
from hybrid_engine.distributions import Budget
from hybrid_engine.elite_render import split_blocks
from hybrid_engine.evaluation import v1_forecast
from hybrid_engine.europe_models import PreparedEurope,catalog,season_url
from hybrid_engine.forward_validation import ForwardRegistry
from hybrid_engine.frozen_archive import norm
from hybrid_engine.intervals import prediction_intervals
from hybrid_engine.live_euroleague import names
from universal_analysis import UniversalAnalyzeService,render_preflight
from telegram_delivery import tsi


class EuropeanRegistry(ForwardRegistry):
    def __init__(self,directory,league):
        super().__init__(directory);self.league=resolve_league(league).code
        if self.league not in ('EUROLEAGUE','EUROCUP'):raise ValueError('EUROPE_REGISTRY_LEAGUE')

    def outcome(self,payload):
        g=payload['fixture'];fid=g['canonical_id'];found=None
        for path in sorted(self.root.glob('outcome-'+fid+'-*.json')):
            w=json.loads(local_path(path).read_text());o=w['payload']
            if digest(o)!=w['sha256'] or path.stem!='outcome-'+fid+'-'+w['sha256']:raise ValueError('EUROPE_OUTCOME_PIN')
            if o['forecast_sha256']!=digest(payload):continue
            receipt=self.read_asset(o['source']);b=catalog(receipt,self.league,g['season_start_year'],max_age=None)
            matches=[v for v in b['payload']['fixtures'] if v['canonical_id']==fid and v['completed'] and v['periods']]
            if len(matches)!=1:raise ValueError('EUROPE_OFFICIAL_FINAL_REQUIRED')
            final=matches[0]
            if (any(final[k]!=g[k] for k in ('start_ts_utc','home_team_id','away_team_id','provider_fixture_ids')) or
                    receipt['observed_at_utc']<=g['start_ts_utc'] or o['periods']!=final['periods'] or o['full_final']!=final['final_scores']):
                raise ValueError('EUROPE_FINAL_IDENTITY_SCORE_OR_CLOCK')
            if found is not None and found!=o:raise ValueError('EUROPE_CONFLICTING_FINALS_REQUIRE_REVIEW')
            found=o
        return found

    def settle(self,receipt,year=None):
        if year is None:raise ValueError('EXPLICIT_EUROPE_SETTLEMENT_SEASON_REQUIRED')
        b=catalog(receipt,self.league,year);games={g['canonical_id']:g for g in b['payload']['fixtures']};rows=[]
        for item in self.records():
            p=item['payload'];g=p['fixture'];fid=g['canonical_id']
            if g['season_start_year']!=year:continue
            final=games.get(fid)
            if final is None or not final['completed'] or not final['periods']:continue
            if (any(final[k]!=g[k] for k in ('start_ts_utc','home_team_id','away_team_id','provider_fixture_ids')) or
                    not p['prediction_generated_at_utc']<g['start_ts_utc']<receipt['observed_at_utc']):
                raise ValueError('EUROPE_SETTLEMENT_IDENTITY_OR_CLOCK')
            old=self.outcome(p)
            if old:
                if old['periods']!=final['periods'] or old['full_final']!=final['final_scores']:
                    raise ValueError('EUROPE_RESULT_CORRECTION_REQUIRES_REVIEW')
                continue
            o=dict(fixture_id=fid,forecast_sha256=digest(p),periods=final['periods'],full_final=final['final_scores'],
                source=self.asset('source',receipt),recorded_at_utc=int(time.time()),
                eligible=item['publication']['eligible_for_prospective_audit'],calibration_fit=False)
            publish_json(self.root/('outcome-'+fid+'-'+digest(o)+'.json'),dict(payload=o,sha256=digest(o)))
            rows.append(dict(fixture_id=fid,status='VERIFIED_FINAL_APPENDED'))
        return rows


class EuropeanService:
    def __init__(self,league,directory,models_directory,fetcher,*,archive=None,fallback=None,previous=None):
        self.league=resolve_league(league).code;self.registry=EuropeanRegistry(directory,self.league)
        self.models=local_path(models_directory);self.fetcher=fetcher;self.archive=archive;self.fallback=fallback
        self.previous=previous
        self.preflight=UniversalAnalyzeService(fetcher=fetcher);self.lock=asyncio.Lock()

    def pair(self,p):
        receipt=self.registry.read_asset(p['fixture_source']);g=p['fixture']
        b=catalog(receipt,self.league,g['season_start_year'],max_age=None)
        matches=[v for v in b['payload']['fixtures'] if v==g]
        if len(matches)!=1:raise ValueError('EUROPE_ARCHIVED_FIXTURE_PIN')
        return names(receipt['document'])[g['provider_fixture_ids'][0]]

    def existing(self,day,home,away):
        for item in self.registry.independent_records():
            p=item['payload'];start=datetime.fromtimestamp(p['fixture']['start_ts_utc'],ZoneInfo('Europe/Istanbul'))
            if start.date().isoformat()!=day:continue
            pair=self.pair(p)
            if (norm(home),norm(away))==tuple(map(norm,pair)):return item
        return None

    def legacy(self,day,home,away):
        if self.league!='EUROLEAGUE' or self.archive is None:return None
        for r in self.archive.records.values():
            g=r['fixture'];start=datetime.fromtimestamp(g['start_ts_utc'],ZoneInfo('Europe/Istanbul'))
            if start.date().isoformat()==day and tuple(map(norm,(home,away)))==tuple(map(norm,(g['home_name'],g['away_name']))):return r
        return None

    def render(self,item,*,new=False):
        p=item['payload'];q=p['components']['BAYES_QMC']['prediction'];b=p['components']['BAYES_QMC']['intervals']
        h,a=self.pair(p);esc=html.escape
        blocks=[f'<b>ZEYNAL | {self.league} HİBRİT ARAŞTIRMA</b>\n{esc(h)} – {esc(a)}\n'+tsi(p['fixture']['start_ts_utc'])+
            '\nNormal süre: 40 dk · Uzatma hariç\n'+('Yeni maç öncesi kayıt.' if new else 'ARŞİV REPLAY: Yeni PREMATCH tahmini üretilmedi.'),
            f"<b>SKOR PROJEKSİYONU</b>\n{q['home']:.2f} – {q['away']:.2f}\nToplam {q['total']:.2f} | Fark (ev) {q['margin']:+.2f}"]
        periods=['<b>PERİYOT ANALİZİ</b>']
        for label,v in [(str(i+1)+'Q',v) for i,v in enumerate(q['quarters'])]+[(str(i+1)+'H',v) for i,v in enumerate(q['halves'])]:
            periods.append(f'{label}: {v[0]:.2f} – {v[1]:.2f} | Toplam {sum(v):.2f}')
        blocks.append('\n'.join(periods));bands=['<b>HAM TAHMİN ARALIKLARI</b>']
        for key,title in (('TOTAL','Maç toplamı'),('HOME','Ev toplamı'),('AWAY','Deplasman toplamı'),('MARGIN','Fark')):
            v=b['markets'][key];bands.append(f"{title}: P50 {v['p50']:.1f} | P25–P75 {v['p25']:.1f}–{v['p75']:.1f} | P05–P95 {v['p05']:.1f}–{v['p95']:.1f}")
        bands.append('Nominal bantlar; doğrulanmış kapsama veya güven garantisi değil.');blocks.append('\n'.join(bands))
        prob=q['winner'];blocks.append('<b>MODEL DENETİMİ</b>\nNOT_CALIBRATED · Güven endeksi yok.\n'+
            f"Ham normal süre ev/eşitlik/dep: %{100*prob[0]:.1f} / %{100*prob[1]:.1f} / %{100*prob[2]:.1f}\n"+
            'Kadro, sakatlık, rotasyon ve ölçülmüş tempo doğrulanmadı; modele uygulanmadı.\n'+
            'Piyasa verisi doğrulanamadı; barem veya edge üretilmedi.\n'+
            'Lig/sezon için ayrı hazırlanmış Bayesian/QMC; ensemble eğitilmedi.\n'+
            'Yöntem: RQMC_HALTON | Örnek: '+str(b['scenarios'])+'\nModel: '+esc(q['model'])+'\nSürüm SHA: '+p['version']+
            '\nÜretim: '+tsi(p['prediction_generated_at_utc'])+'\nİlk kalıcı arşiv: '+tsi(item['publication']['first_archived_at_utc'])+
            '\nKaynak: '+season_url(self.league,p['fixture']['season_start_year'])+'\nTahmin SHA: '+digest(p))
        parts=split_blocks(blocks)
        return dict(status='EUROPE_HYBRID_OK',html_parts=parts,html=parts[0],new_record=new,forecast_sha256=digest(p),
            timeline=dict(prediction_generated_at_utc=p['prediction_generated_at_utc'],first_archived_at_utc=item['publication']['first_archived_at_utc'],
                response_prepared_at_utc=int(time.time()),reused_forecast=not new))

    async def analyze(self,league,day,home,away):
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
                if g['completed'] or g['start_ts_utc']<=now+900:raise Abstain('EUROPE_SAFE_PRETIPOFF_WINDOW_CLOSED')
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

    def collect_results(self):
        years=sorted({r['payload']['fixture']['season_start_year'] for r in self.registry.records()})
        if len(years)>5:raise ValueError('EUROPE_RESULT_SEASON_BUDGET')
        return [self.registry.settle(self.fetcher('EUROLEAGUE_LIVE',season_url(self.league,y)),y) for y in years]

    def fixture_blocks(self,day):
        requested=datetime.strptime(day,'%Y-%m-%d');year=requested.year-(requested.month<7)
        receipt=self.fetcher('EUROLEAGUE_LIVE',season_url(self.league,year));b=catalog(receipt,self.league,year)
        pairs=names(receipt['document']);now=int(time.time());blocks=[f'<b>{self.league} | {html.escape(day)} | Türkiye saati</b>\nResmî fikstür; tahmin değil.']
        for g in sorted(b['payload']['fixtures'],key=lambda v:v['start_ts_utc']):
            start=datetime.fromtimestamp(g['start_ts_utc'],ZoneInfo('Europe/Istanbul'))
            if start.date().isoformat()!=day:continue
            h,a=pairs[g['provider_fixture_ids'][0]];state='Tamamlandı' if g['completed'] else 'Başlamadı' if g['start_ts_utc']>now else 'Başladı'
            line=html.escape(f'{start:%H:%M} | {h} – {a} | {state} | '+', '.join(g['provider_fixture_ids']))
            if not g['completed'] and g['start_ts_utc']>now+900:line+='\n<code>'+html.escape(f'/analyze {self.league} {day} {h} vs {a}')+'</code>'
            blocks.append(line)
        if len(blocks)==1:blocks.append('Bu Türkiye takvim gününde doğrulanmış maç yok.')
        return split_blocks(blocks)

"""Opt-in test-bot decision decoration. Never edits an issued forecast or its model."""
import asyncio
import html
import json
from pathlib import Path
import time

from core.team_identity import digest
from hybrid_engine.decision_layer import POLICY_SHA,DecisionDistribution,QuoteEvidence,evaluate_quote
from hybrid_engine.elite_render import split_blocks
from hybrid_engine.intervals import prediction_intervals
from hybrid_engine.observed_markets import observe_espn
from telegram_delivery import DeliveryJournal,tsi


class DecisionJournal:
    def __init__(self,path):self.journal=DeliveryJournal(path)
    def record(self,*,snapshot_sha256,distribution,quotes,rule_by_quote=None,rejected=None):
        rules=rule_by_quote or {};quotes=sorted(quotes,key=lambda q:q.sha256)
        ids=[q.sha256 for q in quotes]
        if any(digest(q.payload)!=q.sha256 for q in quotes) or any(digest(r.payload)!=r.sha256 for r in rules.values()):
            raise ValueError('DECISION_INPUT_PAYLOAD_MUTATED')
        if len(set(ids))!=len(ids):raise ValueError('DUPLICATE_QUOTE_IN_DECISION_MANIFEST')
        manifest=dict(snapshot_sha256=snapshot_sha256,all_quote_ids=ids,rule_ids={k:r.sha256 for k,r in rules.items()},policy_sha256=POLICY_SHA,
            rejected_native_quotes=rejected or [])
        key='decision:'+digest(manifest);old=self.journal.get(key)
        if old is not None:return old
        now=int(time.time())
        evaluations=[evaluate_quote(distribution,q,rules.get(q.sha256),asof_utc=now) for q in quotes] or [evaluate_quote(distribution,asof_utc=now)]
        payload=dict(manifest,evaluations=evaluations,recorded_at_utc=int(time.time()),
            independent_unit='FIXTURE_NOT_QUOTE_COUNT',all_selected_and_unselected_retained=True,
            source_scope='ISOLATED_RESEARCH_NOT_BET_RECEIPTS',mean_median_mode=distribution.describe())
        return self.journal.append(key,payload)
    def read(self):return self.journal.read()


def render_decision(batch):
    blocks=['<b>ELITE KARAR VE KALİBRASYON DENETİMİ</b>\nAraştırma katmanı; üretim modeli değiştirilmedi.']
    d=batch['mean_median_mode'];modes=', '.join(str(x) for x in d['discrete_modes'][:4])
    blocks.append(f"Gerçek örnek dağılımı: {d['samples']:,}\nÖrnek ortalaması: {d['mean']:.2f} | Medyan P50: {d['p50']:.2f}\nAyrık örnek modu: {modes} (eşit tepe sayısı: {d['mode_count']})\nMod, beklenen skor veya medyan değildir.\nP25–P75: {d['p25']:.2f}–{d['p75']:.2f}\nP05–P95: {d['p05']:.2f}–{d['p95']:.2f}\nBantlar gerçekleşen kapsama garantisi değildir.")
    for item in batch['evaluations']:
        q=item.get('quote');text='<b>'+html.escape(item['status'])+'</b>'
        if q:
            text+=' | '+html.escape(str(q['bookmaker_id']))+' | '+q['period']+' '+q['market']+' '+str(q['line'])
            text+='\nGözlem: '+tsi(q['observed_at_utc'])+' | Fiyat: '+html.escape(str(q['prices']))
            text+='\nKaynak: '+html.escape(q['source_url'])+' | SHA '+item['quote_sha256'][:12]
            raw=item['raw_probabilities']
            if raw:text+=f"\nHam model: ALT/DEP %{100*raw['under']:.1f} | İADE %{100*raw['push']:.1f} | ÜST/EV %{100*raw['over']:.1f}\nOlasılıklar kalibre edilmiş güven yüzdesi değildir."
            if item['expected_value'] is not None:text+='\nHam model EV (birim stake): '+html.escape(str(item['expected_value']))
            if item['price_benchmarks'] is not None:
                text+='\nFiyat başabaş/no-vig ölçütü mevcut; gerçek olay olasılığı değildir.'
        else:text+='\nPiyasa verisi doğrulanamadı; çizgi, oran veya seçim üretilmedi.'
        if item['reasons']:text+='\n'+html.escape(', '.join(item['reasons']))
        blocks.append(text)
    blocks.append('Güven endeksi: hesaplanamadı.\nKalibrasyon: doğrulanmadı; model parametreleri donuk.\n100 / 250 / 500 bağımsız tahmin yalnızca inceleme noktalarıdır; otomatik eğitim yok.\nKarar kaydı: '+tsi(batch['recorded_at_utc'])+'\nSeçim veya üretim terfisi yapılmadı.')
    return split_blocks(blocks)


class DecisionService:
    def __init__(self,base,archive,journal,*,nba_service=None):
        self.base=base;self.archive=archive;self.journal=journal;self.nba_service=nba_service
        self.ledger=getattr(base,'ledger',None)

    def _decorate(self,report):
        rejected=[];quotes=[]
        if report.get('snapshot') is not None:
            from hybrid_engine.data import Cut
            from hybrid_engine.decision_audit import trace_for
            p=report['snapshot'];service=self.nba_service
            if service is None:raise ValueError('NBA_REPLAY_CONTEXT_UNAVAILABLE')
            cut=json.loads((service.assets/p['input_asset']['file']).read_text())
            if digest(cut)!=p['input_asset']['sha256']:raise ValueError('DECISION_INPUT_PIN')
            f=service.prepared.model.predict(Cut(**cut),method='RQMC_HALTON',bounded_workspace=True)
            if prediction_intervals(f)['sample_sha256']!=p['intervals']['sample_sha256']:raise ValueError('DECISION_SAMPLE_REGRESSION')
            trace=trace_for(p);pin=digest(p)
            for ref in p['source_assets']:
                r=json.loads((service.assets/ref['file']).read_text())
                if digest(r)!=ref['sha256']:raise ValueError('DECISION_NATIVE_SOURCE_PIN')
                if '/scoreboard?' not in r['source_url']:continue
                if r['ingested_at_utc']>trace['prediction_utc']:raise ValueError('DECISION_QUOTE_AFTER_FORECAST')
                parsed=observe_espn(r,now_utc=trace['prediction_utc']);rejected.extend(parsed['rejected'])
                for q in parsed['quotes']:
                    if q['payload']['fixture_id']==p['fixture_id']:quotes.append(QuoteEvidence.from_espn(q,trusted_sha256=q['sha256']))
        else:
            p=report['record'];f=self.archive.replay(p,'BAYES_QMC');g=p['fixture'];pin=digest(p)
            trace=dict(league='EUROLEAGUE',season=str(g['season_start_year'])+'/'+str(g['season_start_year']+1),fixture_id=g['canonical_id'],
                home_team_id=g['home_team_id'],away_team_id=g['away_team_id'],tipoff_utc=g['start_ts_utc'],
                model_version=f.model,model_digest=p['models']['BAYES_QMC']['model_digest'],prediction_utc=p['created_at_utc'],
                inputs_available_max_utc=p['source_data_time_utc'],prediction_clock_kind='FIRST_CAPTURE_NOT_SEPARATELY_RECORDED_GENERATION')
        unique={q.sha256:q for q in quotes};distribution=DecisionDistribution(f,trace)
        batch=self.journal.record(snapshot_sha256=pin,distribution=distribution,quotes=list(unique.values()),rejected=rejected)
        return render_decision(batch)

    async def analyze(self,*args):
        report=await self.base.analyze(*args)
        if report['status'] not in ('ANALYSIS_OK','FROZEN_REPLAY_OK'):return report
        before=digest(report.get('snapshot',report.get('record')))
        try:parts=await asyncio.to_thread(self._decorate,report)
        except (ValueError,KeyError,TypeError,OSError):
            parts=['<b>ELITE KARAR DENETİMİ</b>\nINSUFFICIENT_DATA: karar kaynakları doğrulanamadı. Seçim üretilmedi; kayıtlı tahmin değiştirilmedi.']
        if digest(report.get('snapshot',report.get('record')))!=before:raise ValueError('DECISION_LAYER_MUTATED_FORECAST')
        # Keep the original HTML and append supported, separately bounded blocks.
        return dict(report,html_parts=[*(report.get('html_parts') or [report['html']]),*parts])


class DecisionReports:
    def __init__(self,base,journal,*,audit_report=None):self.base=base;self.journal=journal;self.audit=audit_report
    def read(self,league=None,fixture_id=None):
        report=self.base.read(league,fixture_id);entries=self.journal.read()
        return dict(base=report,decision_batches=len(entries),selected=sum(bool(e['selected']) for b in entries for e in b['evaluations']),
            calibrated_profiles=0,automatic_updates=False,league=league,fixture_id=fixture_id,audit=self.audit)
    def _render(self,r,name):
        from ledger_reports import render_accuracy,render_compare
        if r['audit'] is not None and (r['league'] is None or r['league'].upper()=='NBA'):
            a=r['audit'];lines=['ZEYNAL | DOĞRULANMIŞ MAÇ-SONU ARAŞTIRMA | ÜRETİM DEĞİL']
            if name=='render_accuracy':
                for g in a['groups']:
                    if r['league'] and r['league'].upper()!=g['league'].upper():continue
                    m=g['metrics'];lines.append(f"{g['league']} | {g['model_version']} | n={m['n']} | Takım MAE {m['team_scores']['mae']:.2f} | Toplam MAE {m['total']['mae']:.2f}")
                lines.append('Normal süre ve OT ayrı; kalibrasyon doğrulanmadı. Piyasa başarı oranı için yeterli karar/kural kaydı yok.')
            else:
                for item in a['per_fixture']:
                    if r['fixture_id'] and r['fixture_id'] not in [item['fixture_id'],*item['provider_fixture_ids']]:continue
                    if r['league'] and r['league'].upper()!=item.get('league','NBA').upper():continue
                    lines.append(f"{item['provider_fixture_ids'][0]} | Tahmin {item['prediction'][0]:.2f}–{item['prediction'][1]:.2f} | Normal süre {item['regulation']} | OT dahil {item['final_with_ot']}")
            if len(lines)==1:lines.append('Bu kapsamda doğrulanmış sonuç yok.')
            lines.append('Tek maçtan otomatik kalibrasyon yapılmadı. Yeni tahmin üretilmedi.')
            return '\n'.join(lines)
        renderer=getattr(self.base,name,render_accuracy if name=='render_accuracy' else render_compare)
        return renderer(r['base'])+f"\nKarar denetimi: {r['decision_batches']} eklemeli kayıt | Seçim {r['selected']}\nKalibrasyon doğrulanmadı; 100/250/500 inceleme eşiği otomatik eğitim değildir."
    def render_accuracy(self,r):return self._render(r,'render_accuracy')
    def render_compare(self,r):return self._render(r,'render_compare')


def read_audit_report(path,trusted_sha256):
    from hybrid_engine.data import local_path
    path=local_path(path)
    if path.stat().st_size>4*1024*1024:raise ValueError('BOUNDED_AUDIT_REPORT_REQUIRED')
    w=json.loads(path.read_text());p=w['payload']
    if w['sha256']!=trusted_sha256 or digest(p)!=trusted_sha256 or p.get('format')!='IMMUTABLE_NBA_SCORE_AUDIT_V1':raise ValueError('AUDIT_REPORT_TRUSTED_PIN')
    if p.get('model_parameters_changed') or p.get('automatic_calibration'):raise ValueError('OBSERVATION_ONLY_REPORT_REQUIRED')
    return p

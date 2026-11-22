"""Fresh research assessments with stored joint paths; originals are never rewritten.

No fitting in Telegram. No player, news, itinerary or OT effect is invented.
These hourly assessments have their own clock and descriptive result cohort.
"""
from collections import defaultdict
from copy import deepcopy
import hashlib
import html
from pathlib import Path
import time

import numpy as np
from core.team_identity import digest
from hybrid_engine import adaptive_models,nba_dynamic
from hybrid_engine.adaptive_research import Registry,read_wrapper
from hybrid_engine.boxes import publish_json
from hybrid_engine.data import Abstain,local_path
from hybrid_engine.distributions import Forecast
from hybrid_engine.europe_prematch import publication_lock
from hybrid_engine.intervals import prediction_intervals
from hybrid_engine.issue90_research import pins,reason
from telegram_delivery import tsi

VERSION='CURRENT_RESEARCH_ASSESSMENT_V1'
POLICY=dict(version=VERSION,refresh_seconds=3600,maximum_model_age_seconds=21600,
    minimum_lead_seconds=900,maximum_records=512,maximum_bytes=256*1024*1024,
    automatic_promotion=False,original_performance_eligible=False)


class AssessmentRegistry(Registry):
    """Verify publication metadata on scan; authenticate all selected assets on use.

    Avoid decoding every 10,000-path asset for every unrelated match command.
    No cross-request cache and no asset is used without its archived SHA check.
    """
    def records(self):
        slots=sorted(self.root.glob('first-*.json'))
        if len(slots)>POLICY['maximum_records']:raise ValueError('CURRENT_ASSESSMENT_SCAN_BUDGET')
        out=[]
        for slot in slots:
            if slot.stat().st_size>65536:raise ValueError('CURRENT_PUBLICATION_SIZE')
            publication=self.publication(slot);ref=publication['forecast']
            if Path(ref['file']).name!=ref['file'] or (self.root/ref['file']).stat().st_size>256*1024:
                raise ValueError('CURRENT_FORECAST_PATH_OR_SIZE')
            p=self.read_asset(ref);key=digest(dict(fixture=p['fixture']['canonical_id'],version=p['version']))
            if slot.stem!='first-'+key or ref['file']!='forecast-'+digest(p)+'.json':raise ValueError('CURRENT_PUBLICATION_PIN')
            clocks=[p['source_available_max_utc'],p['prediction_generated_at_utc'],p['snapshot_created_at_utc'],
                publication['first_archived_at_utc'],p['fixture']['start_ts_utc']]
            if (any(type(v) is not int for v in clocks) or p.get('actual') is not None or
                    not 0<clocks[0]<=clocks[1]<=clocks[2]<=clocks[3]<=int(time.time()) or
                    clocks[3]>=clocks[4] or publication['classification']!='PREMATCH' or
                    publication['eligible_for_prospective_audit'] is not True):
                raise ValueError('CURRENT_PUBLICATION_CLOCK')
            receipt_path=self.root/('assessment-commit-'+key+'.json')
            if not receipt_path.is_file():raise Abstain('CURRENT_ASSESSMENT_COMMIT_UNCONFIRMED')
            receipt=read_wrapper(receipt_path,maximum=65536)['payload']
            if (receipt['forecast_sha256']!=ref['sha256'] or receipt['publication_sha256']!=digest(publication) or
                    type(receipt['completed_at_utc']) is not int or not clocks[3]<=receipt['completed_at_utc']<=int(time.time()) or
                    receipt['eligible']!=(receipt['completed_at_utc']<clocks[4]-900)):
                raise ValueError('CURRENT_ASSESSMENT_COMMIT_BINDING')
            if not receipt['eligible']:continue
            out.append(dict(payload=p,publication=publication))
        return out

    def record(self,payload):
        p,new=super().record(payload)
        if new:
            key=digest(dict(fixture=p['fixture']['canonical_id'],version=p['version']))
            publication=self.publication(self.root/('first-'+key+'.json'));completed=int(time.time())
            receipt=dict(forecast_sha256=publication['forecast']['sha256'],publication_sha256=digest(publication),
                completed_at_utc=completed,eligible=completed<p['fixture']['start_ts_utc']-900)
            publish_json(self.root/('assessment-commit-'+key+'.json'),dict(payload=receipt,sha256=digest(receipt)))
            if not receipt['eligible']:raise Abstain('CURRENT_ASSESSMENT_LATE_COMMIT_EXCLUDED')
        return p,new

    def validate_assets(self,p):
        for ref in p['assets']:
            if Path(ref['file']).name!=ref['file'] or (self.root/ref['file']).stat().st_size>16*1024*1024:
                raise ValueError('CURRENT_ASSET_PATH_OR_SIZE')
            self.read_asset(ref)


class CurrentAssessments:
    def __init__(self,directory,worker,study):
        self.root=local_path(directory);self.registry=AssessmentRegistry(self.root/'records')
        self.worker=worker;self.study=study;self.last_report=None

    def plan(self,create=False):
        path=self.root/'policy.json'
        with publication_lock(self.root):
            if not path.exists() and create:
                p=dict(policy=POLICY,source_pins=pins(),
                    registered_at_utc=int(time.time()),registration='LOCAL_RESEARCH_NOT_SUPERIORITY_PREREGISTRATION')
                publish_json(path,dict(payload=p,sha256=digest(p)))
        w=read_wrapper(path);p=w['payload']
        if (p['policy']!=POLICY or p['source_pins']!=pins() or
                not 0<p['registered_at_utc']<=int(time.time())):
            raise ValueError('CURRENT_ASSESSMENT_POLICY_CHANGED_NEW_STUDY_REQUIRED')
        return w

    def _capture(self,case,model,plan):
        target=case['target'];now=int(time.time());slot=now//POLICY['refresh_seconds']
        version=plan['sha256']+':'+str(slot)
        old=next((r['payload'] for r in self.registry.records() if r['payload']['version']==version and
                  r['payload']['fixture']['canonical_id']==target['fixture_id']),None)
        if old:
            if old['original_snapshot_sha256']!=case['original']:raise Abstain('CURRENT_ASSESSMENT_ORIGINAL_CONFLICT')
            self.registry.validate_assets(old);return old,False
        cutoff=model['payload']['cutoff_utc']
        if not 0<=now-cutoff<=POLICY['maximum_model_age_seconds']:raise Abstain('CURRENT_MODEL_TOO_OLD')
        if now>=target['fixture_start_utc']-900:raise Abstain('CURRENT_ASSESSMENT_SAFE_WINDOW_CLOSED')
        first=self.worker.verify(target)
        if target['league']=='NBA':forecast=nba_dynamic.predict(model,target,cutoff_utc=now)
        else:
            forecasts,_,_=adaptive_models.predict(model,target,cutoff_utc=now)
            forecast=forecasts['PACE_EFFICIENCY']
        final=self.worker.verify(target);generated=int(time.time())
        if generated>=target['fixture_start_utc']-900:raise Abstain('CURRENT_ASSESSMENT_SAFE_WINDOW_CLOSED')
        files=[f for f in self.registry.root.iterdir() if f.is_file()]
        if len(self.registry.records())>=POLICY['maximum_records'] or sum(f.stat().st_size for f in files)>POLICY['maximum_bytes']-4*1024*1024:
            raise Abstain('CURRENT_ASSESSMENT_STORAGE_BUDGET')
        bands=prediction_intervals(forecast);q=forecast.summary()
        paths=dict(format='INTEGER_JOINT_REGULATION_PATHS_V1',samples=forecast.samples.tolist(),
            dtype=forecast.samples.dtype.str,summary=q,intervals=bands,model_artifact_sha256=model['sha256'],feature_cutoff_utc=now)
        refs=[self.registry.asset('model',model),self.registry.asset('native-before',first),
              self.registry.asset('native-after',final),self.registry.asset('joint-paths',paths)]
        m=q['metadata'];features=dict(team_efficiency='APPLIED',
            box_pace='APPLIED_BOX_ESTIMATE_NOT_MEASURED_PBP',
            opponent_form='APPLIED' if m.get('opponent_adjusted') else 'TEAM_MODEL_ONLY',
            periods='STOCHASTIC_CORRELATED' if m.get('deterministic_period_allocation') is False else 'MODEL_PERIOD_PATHS',
            players='NOT_APPLIED_REQUIRES_VERIFIED_MINUTES_AND_FITTED_PLAYER_MODEL',
            news='OBSERVATION_ONLY_NOT_PLAYER_EFFECT',rest_travel='NOT_APPLIED',
            overtime='NO_VERIFIED_PATHS',market='SEPARATE_CURRENT_PRICE_REVIEW')
        body=dict(record_type=VERSION,version=version,protocol_sha256=plan['sha256'],
            runtime_implementation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            fixture=dict(target,canonical_id=target['fixture_id'],start_ts_utc=target['fixture_start_utc']),
            original_snapshot_sha256=case['original'],original_model_digest=case.get('snapshot',{}).get('model_digest'),
            source_available_max_utc=max(first['ingested_at_utc'],final['ingested_at_utc'],model['payload']['prepared_at_utc']),
            prediction_generated_at_utc=generated,feature_cutoff_utc=now,parameter_fit_cutoff_utc=cutoff,
            candidate=q,intervals=bands,features=features,assets=refs,actual=None,
            eligible_for_original_forecast_metrics=False,confidence_index=None,production_enabled=False)
        return self.registry.record(body)

    def refresh_fixture(self,snapshot):
        """Publish the currently requested NBA fixture, not arbitrary first two.

        Uses only prospective original snapshot and time-valid native data.
        Does not require a calibration threshold, replace the first ledger
        record, or introduce postgame player minutes.
        """
        if snapshot.get('league')!='NBA':raise Abstain('CURRENT_NBA_ONLY')
        now=int(time.time())
        if now>=snapshot['fixture_start_utc']-POLICY['minimum_lead_seconds']:
            raise Abstain('CURRENT_ASSESSMENT_SAFE_WINDOW_CLOSED')
        existing=self.latest(snapshot)
        if existing is not None and (0<=now-existing['prediction_generated_at_utc']<POLICY['refresh_seconds']
                and 0<=now-existing['parameter_fit_cutoff_utc']<=POLICY['maximum_model_age_seconds']):
            return dict(status='CURRENT_CANDIDATE_ALREADY_VALID',
                        fixture_id=snapshot['fixture_id'])
        pin=digest(snapshot)
        cases=self.worker.cases()
        found=[c for c in cases if c['target']['fixture_id']==snapshot['fixture_id']
               and c['original']==pin and c['target']['league']=='NBA']
        if len(found)!=1:raise Abstain('CURRENT_FIXTURE_OR_ORIGINAL_NOT_ELIGIBLE')
        plan=self.plan(create=True)
        model=self.study.fit(snapshot['season'])[0]
        p,new=self._capture(found[0],model,plan)
        return dict(status='CURRENT_CANDIDATE_PUBLISHED' if new else 'CURRENT_CANDIDATE_REPLAY',
                    fixture_id=p['fixture']['canonical_id'],sha256=digest(p))

    def tick(self,preferred_fixture_id=None):
        """Publish at most two eligible candidates, prioritizing a requested match."""
        if preferred_fixture_id is not None and (not isinstance(preferred_fixture_id,str)
                or not 0<len(preferred_fixture_id)<=160):
            raise ValueError('CURRENT_PREFERRED_FIXTURE_ID_INVALID')
        plan=self.plan(create=True);cases=self.worker.cases();captures=[];now=int(time.time())
        saved={(r['payload']['fixture']['canonical_id'],r['payload']['version']) for r in self.registry.records()}
        ready=[c for c in cases if (c['target']['fixture_id'],plan['sha256']+':'+str(now//3600)) not in saved]
        if preferred_fixture_id:
            ready.sort(key=lambda c:c['target']['fixture_id']!=preferred_fixture_id)
            if not any(c['target']['fixture_id']==preferred_fixture_id for c in cases):
                captures.append(dict(status='ABSTAIN',reason='CURRENT_REQUESTED_FIXTURE_NOT_ELIGIBLE',
                    error_type='Abstain'))
        targeted='NOT_REQUESTED'
        if preferred_fixture_id:
            eligible=any(c['target']['fixture_id']==preferred_fixture_id for c in cases)
            in_ready=any(c['target']['fixture_id']==preferred_fixture_id for c in ready)
            targeted=('IN_PROCESSING_BATCH' if in_ready else
                      'NOT_ELIGIBLE' if not eligible else 'ALREADY_RECORDED_THIS_HOUR')
        for c in ready[:2]:
            try:
                t=c['target']
                if t['league']=='NBA':model=self.study.fit(t['season'])[0]
                else:
                    rows=self.worker.store.cohort(c['code'],int(t['season'].split('/')[0]),int(time.time()))
                    model=self.worker.research.fit(rows,t['league'],t['season'])[0]
                p,new=self._capture(c,model,plan)
                captures.append(dict(status='ARCHIVED' if new else 'REPLAY',fixture_id=t['fixture_id'],sha256=digest(p)))
            except (ValueError,KeyError,TypeError,OSError,RuntimeError) as exc:
                captures.append(dict(status='ABSTAIN',reason=reason(exc),error_type=type(exc).__name__))
        if preferred_fixture_id and targeted=='IN_PROCESSING_BATCH':
            matched=[r for r in captures if r.get('fixture_id')==preferred_fixture_id]
            targeted=('PUBLISHED_OR_REPLAYED' if any(r.get('status') in ('ARCHIVED','REPLAY') for r in matched)
                      else 'FAILED_OR_ABSTAIN' if any(r.get('status')=='ABSTAIN' for r in captures)
                      else 'NOT_PROCESSED')
        published=sum(r.get('status')=='ARCHIVED' for r in captures)
        # A completed cycle with no publication is not a newly published score.
        self.last_report=dict(status='PARTIAL_ABSTAIN' if any(r['status']=='ABSTAIN' for r in captures) else
            'CHECKED_NO_NEW_CANDIDATE' if published==0 else 'CHECKED',
            observed_at_utc=int(time.time()),captures=captures,originals_changed=False,
            candidate_published_count=published,capture_attempt_count=len(captures),
            eligible_not_yet_saved_count=len(ready),
            requested_fixture_id=preferred_fixture_id,requested_fixture_status=targeted,
            performance=self.performance(self.worker.labels()))
        return self.last_report

    def performance(self,labels):
        """Native-labelled prospective candidates, paired only to their first original.

        These are two descriptive views: all eligible current assessments and
        the stricter, same-fixture original/candidate pairs. No postgame fitting,
        automatic score correction, or retrospective selection is allowed.
        """
        from hybrid_engine.live_metrics import metrics
        mapped={}
        for r in labels:
            if r.get('actual') is None:continue
            key=(r['fixture_id'],r['snapshot_sha256'])
            if key in mapped and any(mapped[key][k]!=r[k] for k in ('actual','actual_periods','fixture_start_utc')):
                raise ValueError('CURRENT_ASSESSMENT_NATIVE_LABEL_CONFLICT')
            mapped[key]=r
        groups=defaultdict(list);paired=defaultdict(list);first={}
        for entry in self.registry.records():
            p=entry['payload'];t=p['fixture'];q=p['candidate']
            key=(t['league'],t['season'],q['model'],t['fixture_id'])
            # Choose the earliest durable original evaluation, not the latest
            # refresh or the assessment that happens to fit the actual score.
            rank=(entry['publication']['first_archived_at_utc'],p['prediction_generated_at_utc'])
            old=first.get(key)
            if old is None or rank<old[0]:first[key]=(rank,p)
        for key,(_,p) in first.items():
            r=mapped.get((p['fixture']['fixture_id'],p['original_snapshot_sha256']))
            if r is None:continue
            self.registry.validate_assets(p)
            if (r['fixture_start_utc']!=p['fixture']['fixture_start_utc'] or
                    p.get('original_model_digest') and r['model_digest']!=p['original_model_digest']):
                raise ValueError('CURRENT_ASSESSMENT_NATIVE_LABEL_BINDING')
            q=p['candidate']
            current=dict(prediction=[q['home'],q['away']],actual=r['actual'],
                actual_periods=r['actual_periods'],predicted_quarters=q['quarters'],winner=q['winner'],
                intervals=p['intervals'],fixture_start_utc=r['fixture_start_utc'],
                prediction_generated_at_utc=p['prediction_generated_at_utc'],label_available_utc=r['label_available_utc'])
            group=key[:3]
            groups[group].append(current)
            original=r.get('prediction');issued=r.get('prediction_generated_at_utc')
            archived=r.get('first_archived_at_utc')
            # A match is paired only when the first score was genuinely issued,
            # persisted before the current candidate, and independently settled.
            # Missing publication clocks or original numbers are NOT backfilled.
            if (type(issued) is int and type(archived) is int and
                    0<issued<=archived<=p['prediction_generated_at_utc']<r['fixture_start_utc']-900 and
                    isinstance(original,(list,tuple)) and len(original)==2 and
                    all(type(v) in (int,float) and np.isfinite(v) and v>=0 for v in original)):
                baseline=dict(prediction=list(original),actual=r['actual'],
                    actual_periods=r['actual_periods'],fixture_start_utc=r['fixture_start_utc'],
                    prediction_generated_at_utc=issued,label_available_utc=r['label_available_utc'])
                paired[group].append((current,baseline))
        results=[]
        for group,values in sorted(groups.items()):
            pairs=paired[group]
            candidate_pair=metrics([v[0] for v in pairs]) if pairs else None
            baseline_pair=metrics([v[1] for v in pairs]) if pairs else None
            results.append(dict(league=group[0],season=group[1],model=group[2],
                metrics=metrics(values),paired_n=len(pairs),
                paired=dict(status='PAIRED_DESCRIPTIVE_ONLY' if pairs else 'NO_VERIFIED_FIRST_FORECAST_PAIR',
                    first_forecast_total_mae=None if not pairs else baseline_pair['total']['mae'],
                    candidate_total_mae=None if not pairs else candidate_pair['total']['mae'],
                    total_mae_delta=None if not pairs else
                        baseline_pair['total']['mae']-candidate_pair['total']['mae'],
                    first_forecast_team_mae=None if not pairs else baseline_pair['team_scores']['mae'],
                    candidate_team_mae=None if not pairs else candidate_pair['team_scores']['mae'],
                    paired_fixture_count=len(pairs),automatic_promotion=False)))
        return dict(groups=results,unit='FIRST_CURRENT_ASSESSMENT_PER_FIXTURE_AND_STRATEGY',
            paired_unit='SAME_NATIVE_SETTLED_FIXTURE_FIRST_ORIGINAL_VS_FIRST_PROSPECTIVE_CANDIDATE',
            cohort='CHRONOLOGICAL_REFRESH_STRATEGY_NOT_SINGLE_FIT',original_metrics_changed=False,
            superiority_claim=False,automatic_promotion=False)

    def render_performance(self):
        lines=['GÜNCEL DEĞERLENDİRMELER | AYRI BETİMSEL PERFORMANS',
            'Her maç/strateji için ilk değerlendirme; sonraki güncellemeler örnek sayısını artırmaz.']
        if not self.last_report or 'performance' not in self.last_report:
            return '\n'.join(lines+['Bu süreçte doğrulanmış rapor henüz hazırlanmadı.'])
        groups=self.last_report['performance']['groups']
        for g in groups:
            m=g['metrics'];lines.append(g['league']+' '+g['model']+
                f" · n={m['n']} · Takım MAE {m['team_scores']['mae']:.2f} · Toplam MAE {m['total']['mae']:.2f}")
            pair=g.get('paired') or {}
            if pair.get('paired_fixture_count',0)>0:
                lines.append('Aynı maçların ilk tahmini ile eşleştirme: '+
                    str(pair['paired_fixture_count'])+' maç · İlk toplam MAE '+
                    f"{pair['first_forecast_total_mae']:.2f}"+' · Güncel aday toplam MAE '+
                    f"{pair['candidate_total_mae']:.2f}"+' · Hata azalması (pozitif=aday iyi) '+
                    f"{pair['total_mae_delta']:+.2f}")
            else:
                lines.append('İlk tahminle yayın saati doğrulanmış karşılaştırma: 0 eşleşen maç.')
        if not groups:lines.append('Henüz doğrulanmış sonuçla eşleşme yok.')
        lines.append('Sonuçlar yalnız kayıtlı ileri tarihli adaylara aittir; eski 54 maça sonradan tahmin yazılmaz.')
        return '\n'.join(lines+['İlk tahmin performansına eklenmez; üstünlük veya kalibrasyon kanıtı değildir.'])

    def render_rows(self,rows):
        rendered=[];seen=set()
        for row in rows:
            key=(row['fixture_id'],row['snapshot_sha256'])
            if key in seen:continue
            seen.add(key)
            matches=[r['payload'] for r in self.registry.records() if r['payload']['fixture']['fixture_id']==row['fixture_id']]
            if not matches:continue
            p=matches[-1];t=p['fixture']
            ctx=dict(league=t['league'],season=t['season'],fixture_id=t['fixture_id'],
                fixture_start_utc=t['fixture_start_utc'],original_forecast_sha256=row['snapshot_sha256'],
                home=dict(provider_id=t['home_team_id']),away=dict(provider_id=t['away_team_id']))
            rendered.append(self.render(ctx))
        return '\n\n'.join(rendered)

    def latest(self,context):
        if not (self.root/'policy.json').is_file():return None
        self.plan();pin=context.get('original_forecast_sha256') or digest(context)
        fid=context['fixture_id'];rows=[r['payload'] for r in self.registry.records() if r['payload']['fixture']['canonical_id']==fid]
        if not rows:return None
        p=max(rows,key=lambda r:r['prediction_generated_at_utc'])
        self.registry.validate_assets(p)
        if p['original_snapshot_sha256']!=pin:raise ValueError('CURRENT_ASSESSMENT_ORIGINAL_PIN')
        t=p['fixture']
        if (t['league'].upper()!=context['league'].upper() or t['season']!=context['season'] or
                t['fixture_start_utc']!=context['fixture_start_utc'] or
                any(t[s+'_team_id']!=context[s]['provider_id'] for s in ('home','away'))):
            raise ValueError('CURRENT_ASSESSMENT_FIXTURE_BINDING')
        return p

    def market_context(self,context):
        p=self.latest(context)
        if p is None:return None
        now=int(time.time());age=now-p['prediction_generated_at_utc']
        if not 0<=age<=3600 or now>=p['fixture']['fixture_start_utc']:raise Abstain('CURRENT_ASSESSMENT_STALE_OR_STARTED')
        if now-p['parameter_fit_cutoff_utc']>21600:raise Abstain('CURRENT_MODEL_TOO_OLD')
        ref=next(r for r in p['assets'] if r['file'].startswith('joint-paths-'))
        asset=self.registry.read_asset(ref);q=p['candidate']
        samples=np.asarray(asset['samples'])
        if samples.shape!=(10000,4,2) or not np.issubdtype(samples.dtype,np.integer):raise ValueError('CURRENT_JOINT_PATH_SHAPE')
        if asset['dtype'] not in ('<i4','>i4','<i8','>i8') or np.any(samples<0) or np.any(samples>1000):
            raise ValueError('CURRENT_JOINT_PATH_DTYPE_OR_RANGE')
        samples=samples.astype(asset['dtype'])
        forecast=Forecast(q['model'],np.asarray(q['quarters']),samples=samples,metadata=q['metadata'])
        if asset['summary']!=q or prediction_intervals(forecast)!=p['intervals']:
            raise ValueError('CURRENT_JOINT_PATH_PIN')
        snap=dict(league=context['league'],season=context['season'],fixture_id=context['fixture_id'],
            fixture_start_utc=context['fixture_start_utc'],home=deepcopy(context['home']),away=deepcopy(context['away']),
            model_version=q['model'],model_digest=asset['model_artifact_sha256'],
            prediction_generated_at_utc=p['prediction_generated_at_utc'],intervals=p['intervals'],
            parameter_fit_cutoff_utc=p['parameter_fit_cutoff_utc'],
            input_clocks=[dict(ingested_at_utc=p['source_available_max_utc'])],record_type=VERSION,
            linked_original_snapshot_sha256=p['original_snapshot_sha256'],current_assessment_sha256=digest(p))
        from hybrid_engine.decision_audit import trace_for
        from hybrid_engine.decision_layer import DecisionDistribution
        return snap,DecisionDistribution(forecast,trace_for(snap))

    def available_market_context(self,context):
        try:return self.market_context(context)
        except Abstain as exc:
            if str(exc) not in ('CURRENT_ASSESSMENT_STALE_OR_STARTED','CURRENT_MODEL_TOO_OLD'):raise
            return None  # A stale assessment is never presented as current.

    def render(self,context):
        p=self.latest(context)
        if p is None:
            cutoff=context.get('parameter_fit_cutoff_utc')
            age='bilinmiyor' if type(cutoff) is not int else str(max(0,int(time.time())-cutoff)//3600)+' saat'
            return 'Güncel araştırma değerlendirmesi: kayıt henüz yok; ilk tahmin gösteriliyor.\nİlk modelin parametre yaşı: '+age
        q=p['candidate'];now=int(time.time())
        fresh=0<=now-p['prediction_generated_at_utc']<=3600 and now<context['fixture_start_utc'] and now-p['parameter_fit_cutoff_utc']<=21600
        return '\n'.join(['🧪 '+('GÜNCEL' if fresh else 'ARŞİV')+' ARAŞTIRMA DEĞERLENDİRMESİ',
            q['model'],f"Ev {q['home']:.2f} · Dep {q['away']:.2f} · Toplam {q['total']:.2f}",
            'Hesap: '+tsi(p['prediction_generated_at_utc'])+' · Model kesiti: '+tsi(p['parameter_fit_cutoff_utc']),
            'Tempo/verimlilik hesaba uygulandı; oyuncu, haber ve seyahat etkisi uygulanmadı.',
            'Tam ortak simülasyon yolları kayıtlı; piyasa aynı değerlendirmeyle karşılaştırılır.',
            'NOT_CALIBRATED · İlk tahmin ve eski deney değiştirilmedi.',
            'Değerlendirme SHA: '+digest(p)[:16]])


def install_display(state,assessments):
    """Read existing assessment only; no fit/source calls in handlers or callbacks."""
    base=state['verified_analysis_service']
    class Display:
        ledger=getattr(base,'ledger',None)
        def __init__(self):
            # Expose the read-only wrapper chain to /test runtime diagnostics.
            self.base=base
        async def analyze(self,league,*args):
            import asyncio
            response=await base.analyze(league,*args)
            context=response.get('snapshot');entry=None
            keyboard=response.get('reply_markup')
            if keyboard:
                try:
                    token=keyboard.inline_keyboard[0][0].callback_data.split(':')[1]
                    entry=state.get('premium_reports',{}).get(token)
                    if context is None and entry:context=entry.get('europe_context')
                except (AttributeError,IndexError,TypeError):pass
            if context is None:return response
            try:value=await asyncio.wait_for(asyncio.to_thread(assessments.render,context),timeout=10)
            except (ValueError,KeyError,TypeError,OSError,TimeoutError):
                value='Güncel araştırma değerlendirmesi doğrulanamadı; ilk tahmin korunuyor.'
            prefix=html.escape(value)+'\n\n'
            result=dict(response)
            parts=list(response.get('html_parts') or [response['html']])
            if len((prefix+parts[0]).encode('utf-16-le'))//2<=3500:parts[0]=prefix+parts[0]
            else:parts.insert(0,prefix)
            result['html_parts']=parts;result['html']=parts[0]
            if entry:
                from hybrid_engine.elite_render import split_blocks
                original=entry.get('summary','')
                if len((prefix+original).encode('utf-16-le'))//2<=3500:entry['summary']=prefix+original
                audit=entry['sections'].get('audit','')
                entry['sections']['audit']=prefix+audit
                entry['section_pages']['audit']=split_blocks(entry['sections']['audit'].splitlines(),limit=3200)
            return result
    state['verified_analysis_service']=Display()

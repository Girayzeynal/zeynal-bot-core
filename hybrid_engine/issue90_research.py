"""Serial background V3 research + automatic isolated calibration candidates.

The V1/V2 plans, predictors, published originals and production are untouched.
All candidate publications link an authenticated original and native fixture.
"""
import asyncio
import hashlib
from pathlib import Path
import time

import numpy as np

from core.team_identity import digest
from hybrid_engine import nba_dynamic,shadow_learning,nba_schedule_features
from hybrid_engine.adaptive_research import Registry,read_wrapper,source_pins as v2_pins
from hybrid_engine.archive_audit import audit_ledger
from hybrid_engine.challenger_review import source_pins as v1_pins
from hybrid_engine.boxes import publish_json
from hybrid_engine.data import Abstain,local_path
from hybrid_engine.europe_prematch import publication_lock
from hybrid_engine.intervals import prediction_intervals
from hybrid_engine.live_metrics import metrics
from hybrid_engine.time_policy import PREMATCH_MINIMUM_LEAD_SECONDS

POLICY=dict(version='ISSUE90_SEPARATE_NBA_STUDY_V2_INTEGRITY',primary=nba_dynamic.VERSION,
    minimum_future_games=100,minimum_day_clusters=20,minimum_coverage=.8,minimum_relative_gain=.02,
    baseline='ORIGINAL_FROZEN',selection='ALL_FUTURE_ORIGINALS_NO_RESULT_SELECTION',
    automatic_shadow_fit=True,automatic_promotion=False,production_enabled=False)


def pins():
    root=Path(__file__).parent
    return dict(v1=v1_pins(),v2=v2_pins(),issue90={n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in
        ('nba_dynamic.py','shadow_learning.py','issue90_research.py','joint_market_audit.py','nba_schedule_features.py',
         'nba_ledger_settlement.py','confirmed_nba.py','decision_layer.py','../season_archive_inventory.py')})


def reason(exc):
    text=str(exc)
    return text if text and len(text)<128 and all(c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ_0123456789' for c in text) else 'NATIVE_SOURCE_MODEL_OR_ARCHIVE_UNAVAILABLE'


class Research:
    def __init__(self,directory,worker):
        self.root=local_path(directory);self.root.mkdir(parents=True,exist_ok=True);self.worker=worker
        self.registry=Registry(self.root/'forecasts');self.shadow_registry=Registry(self.root/'shadow-forecasts')
        self.last_report=None;self.calibration_attempted=set();self.last_journal=0
        self.last_attempt={};self.retry_after={}

    def plan(self):
        path=self.root/'plan.json'
        with publication_lock(self.root):
            if not path.exists():
                p=dict(policy=POLICY,source_pins=pins(),registered_at_utc=int(time.time()),
                    registration='LOCAL_APPEND_ONLY_NOT_INDEPENDENT_PUBLIC_PREREGISTRATION')
                publish_json(path,dict(payload=p,sha256=digest(p)))
        w=read_wrapper(path);p=w['payload']
        if p['policy']!=POLICY or p['source_pins']!=pins() or not 0<p['registered_at_utc']<=int(time.time()):
            raise ValueError('ISSUE90_PLAN_CHANGED_REQUIRES_NEW_STUDY')
        return w

    def admit(self,case,plan):
        t=case['target'];key=digest(dict(plan=plan['sha256'],fixture=t['fixture_id']));path=self.root/('admit-'+key+'.json')
        with publication_lock(self.root):
            if path.exists():
                p=read_wrapper(path)['payload']
                if p['target']!=t or p['original_snapshot_sha256']!=case['original']:raise ValueError('ISSUE90_ADMISSION_CONFLICT')
                return
            if int(time.time())>=t['fixture_start_utc']-PREMATCH_MINIMUM_LEAD_SECONDS:raise Abstain('ISSUE90_PREMATCH_WINDOW_CLOSED')
            p=dict(target=t,original_snapshot_sha256=case['original'],protocol_sha256=plan['sha256'],admitted_at_utc=int(time.time()))
            publish_json(path,dict(payload=p,sha256=digest(p)))

    def fit(self,season):
        now=int(time.time());key=digest(dict(season=season,slot=now//21600));path=self.root/('model-'+key+'.json')
        if path.exists():return read_wrapper(path),False
        cohort=self.worker.store.cohort('NBA',int(season.split('/')[0]),now)
        model=nba_dynamic.fit(cohort,cutoff_utc=now)
        # No source timestamp is backdated to the six-hour scheduling boundary.
        publish_json(path,model);return model,True

    def capture(self,case,model,plan,calibrator=None):
        t=case['target']
        with publication_lock(self.root):
            old=next((r['payload'] for r in self.registry.records() if r['payload']['fixture']['canonical_id']==t['fixture_id']),None)
            if old:return old,False
            forecast=nba_dynamic.predict(model,t,cutoff_utc=int(time.time()))
            context=None;context_model=None;context_forecast=None;context_status='ABSTAIN_NATIVE_CALENDAR_UNAVAILABLE';context_receipts=[]
            if hasattr(self.worker,'transport'):
                try:
                    context_receipts=[self.worker.transport('ESPN',url) for url in nba_schedule_features.urls(t)]
                    context=nba_schedule_features.capture(t,context_receipts)
                    prior=[]
                    for r in self.registry.records():
                        old=r['payload']
                        if old.get('schedule_context'):
                            # Replay every derivation from archived native documents;
                            # a plain JSON claim cannot confer calendar evidence.
                            receipts=[self.registry.read_asset(ref) for ref in old['schedule_receipt_assets']]
                            with_target=old['schedule_context']['payload']['target']
                            # Past witnesses cannot be re-captured at today's clock.
                            # Verify their body/source binding using the original
                            # native receipts at their recorded capture boundary.
                            rebuilt=nba_schedule_features.capture(with_target,receipts,
                                asof_utc=old['schedule_context']['payload']['observed_at_utc'])
                            if rebuilt!=old['schedule_context']:raise ValueError('ISSUE90_NATIVE_SCHEDULE_REPLAY_CONFLICT')
                            prior.append(rebuilt)
                    try:
                        context_model=nba_schedule_features.fit(model,prior)
                        context_forecast=nba_schedule_features.predict(model,context_model,forecast,context)
                        context_status='EXPLORATORY_CONTEXT_FORECAST_CREATED'
                    except Abstain as exc:context_status=reason(exc)
                except (ValueError,KeyError,TypeError,OSError,RuntimeError) as exc:
                    context_status=reason(exc)
            receipt=self.worker.verify(t);stamp=int(time.time())
            if stamp>=t['fixture_start_utc']-PREMATCH_MINIMUM_LEAD_SECONDS:raise Abstain('ISSUE90_PREMATCH_WINDOW_CLOSED')
            shadow=None;shadow_status='ABSTAIN_CALIBRATION_TRAINING_INSUFFICIENT'
            if calibrator is not None:
                original=case['snapshot'];row=dict(fixture_id=t['fixture_id'],fixture_start_utc=t['fixture_start_utc'],
                    snapshot_sha256=case['original'],league='NBA',season=t['season'],model_digest=original['model_digest'],winner=original['prediction']['winner'])
                try:shadow=shadow_learning.apply(calibrator,row,generated_at_utc=stamp);shadow_status='SHADOW_PUBLISHED'
                except (ValueError,Abstain) as exc:shadow_status=reason(exc)
            refs=[self.registry.asset('model',model),self.registry.asset('current-fixture',receipt)]
            schedule_refs=[]
            if context is not None:
                schedule_refs=[self.registry.asset('schedule-source',r) for r in context_receipts];refs.extend(schedule_refs)
            if context_model is not None:refs.append(self.registry.asset('schedule-model',context_model))
            if calibrator is not None:refs.append(self.registry.asset('calibrator',calibrator))
            p=dict(version=POLICY['version'],protocol_sha256=plan['sha256'],
                fixture=dict(t,canonical_id=t['fixture_id'],start_ts_utc=t['fixture_start_utc']),
                source_available_max_utc=max(model['payload']['training_available_max'],receipt['ingested_at_utc']),
                prediction_generated_at_utc=stamp,original_snapshot_sha256=case['original'],
                original_model_digest=case['snapshot']['model_digest'],actual=None,assets=refs,
                candidate=forecast.summary(),intervals=prediction_intervals(forecast),
                schedule_context=context,schedule_receipt_assets=schedule_refs,schedule_status=context_status,
                schedule_candidate=None if context_forecast is None else context_forecast.summary(),
                baseline=case['frozen'],shadow=shadow,shadow_status=shadow_status,
                production_enabled=False,originals_changed=False,confidence_index=None)
            return self.registry.record(p)

    def capture_shadow(self,case,calibrator,plan):
        """Probability-only study does not depend on box/pace model readiness."""
        t=case['target'];original=case['snapshot']
        with publication_lock(self.root):
            old=next((r['payload'] for r in self.shadow_registry.records() if r['payload']['fixture']['canonical_id']==t['fixture_id']),None)
            if old:return old,False
            receipt=self.worker.verify(t);stamp=int(time.time())
            row=dict(fixture_id=t['fixture_id'],fixture_start_utc=t['fixture_start_utc'],snapshot_sha256=case['original'],
                league='NBA',season=t['season'],model_digest=original['model_digest'],winner=original['prediction']['winner'])
            shadow=shadow_learning.apply(calibrator,row,generated_at_utc=stamp)
            refs=[self.shadow_registry.asset('calibrator',calibrator),self.shadow_registry.asset('current-fixture',receipt)]
            p=dict(version=POLICY['version']+'_SHADOW',protocol_sha256=plan['sha256'],
                fixture=dict(t,canonical_id=t['fixture_id'],start_ts_utc=t['fixture_start_utc']),actual=None,assets=refs,
                prediction_generated_at_utc=stamp,source_available_max_utc=receipt['ingested_at_utc'],shadow=shadow,
                original_snapshot_sha256=case['original'],original_model_digest=original['model_digest'],production_enabled=False)
            return self.shadow_registry.record(p)

    def performance(self,labels,plan):
        publications=self.registry.records();admissions=[read_wrapper(p)['payload'] for p in self.root.glob('admit-*.json')]
        if len(admissions)>4096:raise ValueError('ISSUE90_ADMISSION_BUDGET')
        labelmap={}
        for r in labels:
            if r.get('league')!='NBA' or r['actual'] is None:continue
            key=(r['fixture_id'],r['snapshot_sha256'],r['model_digest'],r['season'])
            if key in labelmap:raise ValueError('ISSUE90_DUPLICATE_NATIVE_LABEL')
            labelmap[key]=r
        a=[];b=[];covered=0;due=0;shadows=[]
        for w in self.shadow_registry.records():
            p=w['payload'];s=p['shadow']
            if (p['protocol_sha256']!=plan['sha256'] or s['original_snapshot_sha256']!=p['original_snapshot_sha256'] or
                s['fixture_id']!=p['fixture']['canonical_id'] or
                not s['prediction_generated_at_utc']<=w['publication']['first_archived_at_utc']<p['fixture']['start_ts_utc']-PREMATCH_MINIMUM_LEAD_SECONDS):
                raise ValueError('ISSUE90_SHADOW_PUBLICATION_BINDING')
            shadows.append(s)
        admitted={}
        for item in admissions:
            t=item['target']
            if item['protocol_sha256']!=plan['sha256'] or not plan['payload']['registered_at_utc']<=item['admitted_at_utc']<t['fixture_start_utc']-PREMATCH_MINIMUM_LEAD_SECONDS:
                raise ValueError('ISSUE90_ADMISSION_CLOCK_OR_PLAN')
            key=(t['league'],t['season'],t['fixture_id'],item['original_snapshot_sha256'])
            if key in admitted:raise ValueError('ISSUE90_DUPLICATE_ADMISSION')
            admitted[key]=item
            if any(r['fixture_id']==t['fixture_id'] and r['snapshot_sha256']==item['original_snapshot_sha256'] for r in labelmap.values()):due+=1
        for w in publications:
            p=w['payload'];t=p['fixture'];stamp=w['publication']['first_archived_at_utc']
            if p['version']!=POLICY['version'] or p['protocol_sha256']!=plan['sha256'] or not plan['payload']['registered_at_utc']<=p['prediction_generated_at_utc']<=stamp<t['start_ts_utc']-PREMATCH_MINIMUM_LEAD_SECONDS:
                raise ValueError('ISSUE90_PUBLICATION_CLOCK_OR_PLAN')
            admission=admitted.get((t['league'],t['season'],t['fixture_id'],p['original_snapshot_sha256']))
            if admission is None or admission['admitted_at_utc']>p['prediction_generated_at_utc']:
                raise ValueError('ISSUE90_PUBLICATION_WITHOUT_PRIOR_ADMISSION')
            key=(t['fixture_id'],p['original_snapshot_sha256'],p['original_model_digest'],t['season']);label=labelmap.get(key)
            if label is None:continue
            if label['fixture_start_utc']!=t['start_ts_utc'] or not label['fixture_start_utc']<label['label_available_utc']<=int(time.time()):
                raise ValueError('ISSUE90_LABEL_IDENTITY_OR_CLOCK')
            pred=p['candidate'];record=dict(label,prediction=[pred['home'],pred['away']],predicted_quarters=pred['quarters'],
                predicted_halves=pred['halves'],winner=pred['winner'],intervals=p['intervals'])
            a.append(record);b.append(label);covered+=1
        day_count=len({(r['fixture_start_utc']+10800)//86400 for r in a});coverage=covered/due if due else 0.
        # Different original fit/season cohorts do not silently pool. Dynamic
        # candidate fits are a registered strategy, never calibration evidence.
        cohorts={(r['season'],r['model_digest'],r['model_version']) for r in b}
        calibration=shadow_learning.evaluate(shadows,labels,registered_at_utc=plan['payload']['registered_at_utc'])
        if len(cohorts)>1:
            return dict(admitted=len(admissions),published=len(publications),matched=covered,day_clusters=day_count,
                coverage=coverage,gate='ABSTAIN_SEPARATE_ORIGINAL_FIT_COHORTS_REQUIRED',
                groups=[dict(season=s,model_digest=md,model_version=v,
                    candidate=metrics([r for r in a if (r['season'],r['model_digest'],r['model_version'])==(s,md,v)]),
                    baseline=metrics([r for r in b if (r['season'],r['model_digest'],r['model_version'])==(s,md,v)])) for s,md,v in sorted(cohorts)],
                calibration=calibration,production_enabled=False)
        candidate=metrics(a) if a else None;baseline=metrics(b) if b else None
        gate='ABSTAIN_INSUFFICIENT_FUTURE_EVIDENCE';paired=None
        if len(a)>=100 and day_count>=20 and coverage>=.8:
            from hybrid_engine.statistics import paired_cluster_interval
            def paired_row(r):
                h,d=r['prediction'];q=r['predicted_quarters']
                return dict(fixture_id=r['fixture_id'],start_utc=r['fixture_start_utc'],actual=r['actual'],
                    actual_quarters=np.asarray([r['actual_periods'][s][:4] for s in ('home','away')]).T.tolist(),
                    prediction=dict(home=h,away=d,total=h+d,margin=h-d,quarters=q))
            left=[paired_row(r) for r in b];right=[paired_row(r) for r in a]
            paired=paired_cluster_interval(left,right,iterations=10000,family_size=1)
            # The helper's exact interval contract is checked below; never promote.
            improvement=baseline['team_scores']['mae']-candidate['team_scores']['mae']
            gate='REJECTED_NO_VERIFIED_IMPROVEMENT'
            interval=paired['metrics']['team_mae']['interval']
            if interval and improvement>=.02*baseline['team_scores']['mae'] and interval[1]<0:gate='CANDIDATE_FOR_MANUAL_REVIEW'
        return dict(admitted=len(admissions),published=len(publications),matched=covered,day_clusters=day_count,coverage=coverage,
            primary=POLICY['primary'],candidate=candidate,baseline=baseline,paired=paired,gate=gate,
            calibration=calibration,
            automatic_promotion=False,production_enabled=False)

    def tick(self):
        plan=self.plan();cases=[c for c in self.worker.cases() if c['code']=='NBA'];captures=[];now=int(time.time())
        for c in cases:self.admit(c,plan)
        latest={};labels=self.worker.labels();calibrators={};state='CHECKED';shadow_captures=[]
        # Expensive audited calibration fits run at most once per six-hour slot.
        slot=now//21600
        saved={r['payload']['fixture']['canonical_id'] for r in self.registry.records()}
        shadow_saved={r['payload']['fixture']['canonical_id'] for r in self.shadow_registry.records()}
        ready=[c for c in cases if (c['target']['fixture_id'] not in saved and
                self.retry_after.get(('score',c['target']['fixture_id']),0)<=now) or
                (c['target']['fixture_id'] not in shadow_saved and self.retry_after.get(('shadow',c['target']['fixture_id']),0)<=now)]
        # Result-blind fair rotation: two unsupported early fixtures cannot
        # monopolize every later tick. The admission denominator stays intact.
        ready.sort(key=lambda c:(self.last_attempt.get(c['target']['fixture_id'],0),c['target']['fixture_start_utc'],c['target']['fixture_id']))
        for c in ready[:2]:
            fid=c['target']['fixture_id'];self.last_attempt[fid]=now
            shadow_ready=fid not in shadow_saved and self.retry_after.get(('shadow',fid),0)<=now
            try:
                if not shadow_ready:raise Abstain('SHADOW_NOT_DUE')
                season=c['target']['season']
                md=c['snapshot']['model_digest'];ck=digest(dict(slot=slot,model=md,season=season));cp=self.root/('calibrator-'+ck+'.json')
                if cp.exists():calibrators[md]=read_wrapper(cp)
                elif (slot,md,season) not in self.calibration_attempted:
                    self.calibration_attempted={key for key in self.calibration_attempted if key[0]==slot}
                    if len(self.calibration_attempted)>=128:raise Abstain('SHADOW_MODEL_SCOPE_BUDGET')
                    self.calibration_attempted.add((slot,md,season))
                    audit=audit_ledger(self.worker.nba.ledger.path,assets_directory=self.worker.nba.assets)
                    try:
                        calibrators[md]=shadow_learning.fit(audit,model_digest=md,season=season);publish_json(cp,calibrators[md])
                    except Abstain:pass
                if md in calibrators:
                    p,new=self.capture_shadow(c,calibrators[md],plan)
                    shadow_captures.append(dict(fixture_id=c['target']['fixture_id'],status='ARCHIVED' if new else 'REPLAY',sha256=digest(p)))
                else:
                    self.retry_after[('shadow',fid)]=now+900
                    shadow_captures.append(dict(fixture_id=fid,status='ABSTAIN',reason='SHADOW_HUNDRED_NATIVE_SETTLED_ORIGINALS_REQUIRED'))
            except (ValueError,KeyError,TypeError,OSError,RuntimeError) as exc:
                if shadow_ready:
                    self.retry_after[('shadow',fid)]=now+900
                    state='PARTIAL_ABSTAIN';shadow_captures.append(dict(fixture_id=fid,status='ABSTAIN',reason=reason(exc),error_type=type(exc).__name__))
            if fid in saved or self.retry_after.get(('score',fid),0)>now:continue
            try:
                if c['target']['season'] not in latest:latest[c['target']['season']]=self.fit(c['target']['season'])[0]
                p,new=self.capture(c,latest[c['target']['season']],plan)
                captures.append(dict(fixture_id=c['target']['fixture_id'],status='ARCHIVED' if new else 'REPLAY',sha256=digest(p)))
            except (ValueError,KeyError,TypeError,OSError,RuntimeError) as exc:
                self.retry_after[('score',fid)]=now+300
                state='PARTIAL_ABSTAIN';captures.append(dict(fixture_id=c['target']['fixture_id'],status='ABSTAIN',reason=reason(exc),error_type=type(exc).__name__))
        if any(c['status']=='ABSTAIN' for c in shadow_captures):state='PARTIAL_ABSTAIN'
        self.last_report=dict(status=state,evaluation_version=POLICY['version'],observed_at_utc=int(time.time()),protocol_sha256=plan['sha256'],captures=captures,shadow_captures=shadow_captures,
            performance=self.performance(labels,plan),actual_telegram_delivery_verified=False,production_changed=False)
        p=self.last_report
        if any(c['status']=='ARCHIVED' for c in captures+shadow_captures) or int(time.time())-self.last_journal>=3600:
            if len(list(self.root.glob('report-*.json')))<4096:
                publish_json(self.root/('report-'+digest(p)+'.json'),dict(payload=p,sha256=digest(p)))
            self.last_journal=int(time.time())
        return p

    def render(self):
        p=self.last_report or {};m=p.get('performance') or {}
        return '\n'.join(['🧪 NBA V3 | AYRI DİNAMİK MODEL VE GÖLGE KALİBRASYON',
            'Son kontrol: '+p.get('status','HENÜZ_ÇALIŞMADI'),
            f"Kabul edilen maç {m.get('admitted',0)} · Ayrı kayıt {m.get('published',0)} · Eşleşmiş {m.get('matched',0)}/100 · Gün {m.get('day_clusters',0)}/20",
            'Kabul: '+m.get('gate','ABSTAIN'),
            'Kalibrasyon adayı: '+m.get('calibration',{}).get('status','ABSTAIN'),
            'Tempo box-score tahminidir. Oyuncu, ölçülmüş PBP, dinlenme/seyahat etkileri bu V3 adayında uygulanmadı.',
            'NOT_CALIBRATED · Güven endeksi yok · Otomatik üretim yükseltmesi yok.'])


async def run_serial(worker,study,app):
    """No concurrent V2/V3 fits, and no training inside a Telegram handler."""
    while True:
        try:
            app.bot_data['last_adaptive_v2_poll']=await worker.tick()
            app.bot_data['last_issue90_poll']=await asyncio.to_thread(study.tick)
        except asyncio.CancelledError:raise
        except Exception as exc:
            study.last_report=dict(status='ABSTAIN',reason=reason(exc),error_type=type(exc).__name__)
            app.bot_data['last_issue90_poll']=study.last_report
        await asyncio.sleep(60)


def status(directory):
    """No creation, source calls, plan registration or fitting in this reader."""
    root=local_path(directory);files=list(root.glob('report-*.json')) if root.is_dir() else []
    if len(files)>4096 or sum(p.stat().st_size for p in files)>64*1024*1024:raise ValueError('ISSUE90_REPORT_SCAN_BUDGET')
    last=None
    for path in files:
        w=read_wrapper(path,maximum=2*1024*1024)
        if path.stem!='report-'+w['sha256']:raise ValueError('ISSUE90_REPORT_FILE_PIN')
        p=w['payload']
        if last is None or p['observed_at_utc']>last['observed_at_utc']:last=p
    return dict(status='NO_RECORDED_ATTEMPT' if last is None else 'RECORDED_ATTEMPT_AVAILABLE',
        report=last,view_only=True,models_fitted_by_view=False,actual_telegram_delivery_verified=False,production_changed=False,
        evaluation_status='CURRENT_VERSION_RECORDED' if last and last.get('evaluation_version')==POLICY['version'] else 'NO_CURRENT_INTEGRITY_ATTESTATION',
        automatic_promotion=False)


if __name__=='__main__':
    import argparse,json
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--directory',required=True)
    args=parser.parse_args();print(json.dumps(status(args.directory),ensure_ascii=False))

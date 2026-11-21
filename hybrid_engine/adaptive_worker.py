"""Isolated background V2 data acquisition, fixed-schedule fits and captures.

Never called from /analyze. Old NBA protocol and first forecasts are untouched.
"""
import asyncio
from datetime import datetime,timezone,timedelta
import logging
import sqlite3
import time
from zoneinfo import ZoneInfo

from core.team_identity import digest
from hybrid_engine.adaptive_data import FeatureStore,native_catalog
from hybrid_engine.adaptive_research import AdaptiveResearch,read_wrapper
from hybrid_engine.data import Abstain,local_path
from hybrid_engine.europe_models import season_url
from hybrid_engine.europe_prematch import assert_unstarted,EuropeanPrematchScheduler
from hybrid_engine.europe_reports import EuropeanReports
from hybrid_engine.forward_nba_results import read_confirmed
from hybrid_engine.player_inputs import collect as collect_player_inputs
from hybrid_engine.prediction_audit import Assets,audit_snapshot
from hybrid_engine.source_policy import ControlledTransport
from ledger_reports import LedgerReports
from season_archive_collect import fetch_document
from universal_analysis import require_fresh_source
from telegram_delivery import tsi

LOG=logging.getLogger(__name__)


class AdaptiveWorker:
    def __init__(self,directory,*,nba=None,europe=None,fetcher=fetch_document,research_directory=None):
        self.root=local_path(directory);self.nba=nba;self.europe=europe or {}
        roots=([nba.assets] if nba is not None else [])+[s.registry.root for s in self.europe.values()]
        self.transport=ControlledTransport(fetcher,max_cache_bytes=1024*1024)
        self.store=FeatureStore(self.root/'inputs',roots,self.transport)
        self.research=AdaptiveResearch(research_directory if research_directory is not None else self.root,
            player_directory=self.root.parent/'player-shadow')
        self.journal=EuropeanPrematchScheduler({},self.root/'attempts')
        self.seen=set();self.running=False;self.sequence=0;self.retry={};self.player_retry={}
        self.last_report=None;self.last_journal=0;self.group_reports={};self.refreshed=set()
        self.progress=dict(phase='NOT_STARTED',phase_at_utc=None,
            started_at_utc=None,player_input_status='NO_ATTEMPT_OBSERVED')

    def _phase(self,phase,**fields):
        # In-memory progress only. No original ledger or fixture snapshot writes.
        self.progress.update(phase=phase,phase_at_utc=int(time.time()),**fields)

    def refresh_native_history(self,code,year):
        key=(code,year,int(time.time())//21600)
        if key in self.refreshed:return
        if code=='NBA':
            day=datetime.fromtimestamp(time.time(),ZoneInfo('America/New_York')).date()
            urls=['https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates='+
                  (day+timedelta(days=i)).strftime('%Y%m%d')+'&limit=1000' for i in (-1,0,1)]
        else:urls=[season_url(code,year)]
        for url in urls:
            r=self.transport('ESPN' if code=='NBA' else 'EUROLEAGUE_LIVE',url);require_fresh_source(r)
            self.store.observe(r,code,year)
        self.refreshed.add(key)
        if len(self.refreshed)>32:self.refreshed={key}

    def cases(self):
        cases=[];now=int(time.time())
        counts={}
        if self.nba is not None:
            self._phase('READ_NBA_FROZEN_LEDGER',source_scope='NBA')
            rows=read_confirmed(self.nba.ledger.path)
            counts['NBA']=len(rows)
            self.progress['original_scan_counts']=dict(counts)
            if len(rows)>2048:raise ValueError('ADAPTIVE_ORIGINAL_SCAN_BUDGET')
            fresh=sorted(rows,key=lambda r:r['snapshot']['prediction_generated_at_utc'],reverse=True)
            harvested=0
            for i,entry in enumerate(fresh):
                p=entry['snapshot'];pin=digest(p)
                if pin not in self.seen and harvested<2:
                    self._phase('VERIFY_NBA_FROZEN_ASSET',source_scope='NBA',
                                original_scan_position=i+1,original_scan_total=len(fresh))
                    audit_snapshot(p,self.nba.assets)
                    for ref in p['source_assets']:
                        receipt=Assets(self.nba.assets).read(ref);url=receipt['source_url']
                        if '/summary?event=' in url or '/scoreboard?' in url:
                            self.store.ingest(self.nba.assets/ref['file'],ref['sha256'],'NBA',int(p['season'].split('/')[0]))
                    self.seen.add(pin);harvested+=1
                if now+900<p['fixture_start_utc']<=now+36*3600:
                    t=dict(league='NBA',season=p['season'],fixture_id=p['fixture_id'],fixture_start_utc=p['fixture_start_utc'],
                        home_team_id=p['home']['provider_id'],away_team_id=p['away']['provider_id'],provider_fixture_ids=p['provider_fixture_ids'])
                    frozen=dict(status='FORECAST_CREATED',prediction=p['prediction'],intervals=p['intervals'])
                    cases.append(dict(target=t,original=pin,snapshot=p,frozen=frozen,code='NBA'))
        for code,service in self.europe.items():
            self._phase('READ_EUROPE_FROZEN_LEDGER',source_scope=code,
                        original_scan_position=0,original_scan_total=None)
            records=service.registry.independent_records()
            counts[code]=len(records)
            self.progress['original_scan_counts']=dict(counts)
            if len(records)>2048:raise ValueError('ADAPTIVE_ORIGINAL_SCAN_BUDGET')
            harvested=0
            for i,item in enumerate(sorted(records,key=lambda r:r['payload']['prediction_generated_at_utc'],reverse=True)):
                p=item['payload'];pin=digest(p);g=p['fixture']
                if pin not in self.seen and harvested<2:
                    self._phase('VERIFY_EUROPE_FROZEN_FIXTURE',source_scope=code,
                                original_scan_position=i+1,original_scan_total=len(records))
                    service.pair(p)  # Replays the original native fixture binding.
                    self._phase('INGEST_EUROPE_FROZEN_SOURCE',source_scope=code)
                    ref=p['fixture_source'];self.store.ingest(service.registry.root/ref['file'],ref['sha256'],code,g['season_start_year'])
                    self.seen.add(pin);harvested+=1
                if now+900<g['start_ts_utc']<=now+36*3600:
                    t=dict(league='EuroLeague' if code=='EUROLEAGUE' else 'EuroCup',season=f"{g['season_start_year']}/{g['season_start_year']+1}",
                        fixture_id=g['canonical_id'],fixture_start_utc=g['start_ts_utc'],home_team_id=g['home_team_id'],away_team_id=g['away_team_id'],
                        provider_fixture_ids=g['provider_fixture_ids'])
                    cases.append(dict(target=t,original=pin,frozen=p['components']['BAYES_QMC'],code=code))
        self._phase('ORIGINAL_SCAN_COMPLETE',source_scope=None,
                    original_scan_counts=dict(counts),
                    eligible_future_fixtures=len(cases),
                    eligible_nba_fixtures=sum(v['code']=='NBA' for v in cases))
        return sorted(cases,key=lambda c:(c['target']['fixture_start_utc'],c['code'],c['target']['fixture_id']))

    def verify(self,target):
        code=target['league'].upper();year=int(target['season'].split('/')[0])
        if code=='NBA':
            day=datetime.fromtimestamp(target['fixture_start_utc'],timezone.utc).strftime('%Y%m%d')
            url='https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates='+day+'&limit=1000'
            receipt=self.transport('ESPN',url)
        else:receipt=self.transport('EUROLEAGUE_LIVE',season_url(code,year))
        require_fresh_source(receipt);c=native_catalog(receipt,code,year)
        matches=[g for g in c['payload']['fixtures'] if g['canonical_id']==target['fixture_id']]
        if len(matches)!=1:raise Abstain('ADAPTIVE_EXACT_CURRENT_NATIVE_FIXTURE_REQUIRED')
        g=matches[0]
        if g['completed'] or any(g[k]!=target[t] for k,t in
                [('start_ts_utc','fixture_start_utc'),('home_team_id','home_team_id'),('away_team_id','away_team_id')]):
            raise Abstain('ADAPTIVE_CURRENT_FIXTURE_IDENTITY_OR_STATUS')
        if target.get('provider_fixture_ids') and set(target['provider_fixture_ids'])!=set(g['provider_fixture_ids']):
            raise Abstain('ADAPTIVE_CURRENT_PROVIDER_ID_CHANGED')
        if code=='NBA':
            events=[e for e in receipt['document']['events'] if e['id'] in g['provider_fixture_ids']]
            if len(events)!=1:raise Abstain('ADAPTIVE_EXACT_CURRENT_NATIVE_FIXTURE_REQUIRED')
            event=events[0];game=event['competitions'][0];state=game.get('status',event.get('status',{})).get('type',{})
            if state.get('name')!='STATUS_SCHEDULED' or any(float(t.get('score',0))!=0 for t in game['competitors']):
                raise Abstain('ADAPTIVE_SCHEDULED_ZERO_SCORE_REQUIRED')
        else:assert_unstarted(receipt,g)
        if int(time.time())>=g['start_ts_utc']-900:raise Abstain('ADAPTIVE_SAFE_WINDOW_CLOSED')
        return receipt

    def labels(self):
        rows=LedgerReports(self.nba.ledger.path).read('NBA')['forecasts'] if self.nba is not None else []
        for service in self.europe.values():rows.extend(EuropeanReports(service).read()['forecasts'])
        return rows

    async def tick(self):
        if self.running:return dict(status='ABSTAIN',reason='ADAPTIVE_ALREADY_RUNNING')
        self.running=True;self.sequence+=1;now=int(time.time())
        report=dict(format='ADAPTIVE_V2_BACKGROUND_ATTEMPT',evaluated_at_utc=now,completed_at_utc=now,sequence=time.time_ns(),
            status='CHECKED',groups={},captures=[],player_inputs=None,production_changed=False,original_predictions_changed=False,
            existing_nba_plan_changed=False,training_in_telegram_request=False,actual_telegram_delivery_verified=False)
        self.progress=dict(phase='REGISTER_ADAPTIVE_RESEARCH_PLAN',phase_at_utc=now,
            started_at_utc=now,sequence=self.sequence,
            player_input_status='NO_ATTEMPT_OBSERVED',source_scope=None)
        try:
            plan=await asyncio.to_thread(self.research.plan,create=True);report['protocol_sha256']=plan['sha256']
            self._phase('READ_SOURCE_PINNED_ORIGINALS')
            cases=await asyncio.to_thread(self.cases)
            self.progress.update(eligible_future_fixtures=len(cases),
                                 eligible_nba_fixtures=sum(c['code']=='NBA' for c in cases))
            # Prospective NBA player evidence does not depend on V2
            # admission, which may be slow on Android storage. Prioritize
            # the original fixture-bound witness while it is still pretipoff.
            # Prospective player inputs accumulate without a night-time command.
            # A lack of official corroboration stays an explicit block.
            eligible=[c for c in cases if c['code']=='NBA' and self.player_retry.get(c['target']['fixture_id'],0)<=int(time.time())]
            player_case=None
            if not eligible:
                self.progress['player_input_status']='NO_ELIGIBLE_NBA_OR_PRETIPOFF_SNAPSHOT'
            if eligible:
                c=eligible[0];player_case=c;fid=c['target']['fixture_id'];self.player_retry[fid]=int(time.time())+900
                self._phase('PREGAME_PLAYER_MINUTES_SOURCE',fixture_id=fid,player_input_status='RUNNING')
                result=await asyncio.to_thread(collect_player_inputs,c['snapshot'],self.nba.assets,self.research.players)
                self.progress['player_input_status']=result.get('status','UNKNOWN')
                # Expose the exact source/eligibility blocker as soon as the
                # player probe returns, even if expensive V2 box fitting runs.
                # No identity/URL/credential or live original forecast writes.
                code=result.get('reason')
                if isinstance(code,str) and len(code)<=110 and code and all(
                        ch in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ_0123456789' for ch in code):
                    self.progress['player_input_reason']=code
                else:
                    self.progress['player_input_reason']=None
                self.progress['player_input_completed_at_utc']=int(time.time())
                # Keep missing confirmation visible even when V2 is still
                # training. Limited to public team/player IDs and enum source
                # names: never embed report PDF, URLs or player medical notes.
                diag=result.get('roster_diagnostics')
                if isinstance(diag,dict):
                    missing=diag.get('missing_absence_corroboration')
                    missing=missing if isinstance(missing,list) else []
                    summaries=[]
                    for row in missing[:8]:
                        if not isinstance(row,dict):continue
                        tid=row.get('team')
                        pid=row.get('player_id')
                        sources=row.get('missing_sources')
                        summaries.append(dict(
                            team=str(tid)[:80] if tid is not None else None,
                            player_id=pid if isinstance(pid,str) and pid.isdigit() and len(pid)<=15 else None,
                            missing_sources=sorted(s for s in sources if s in ('ESPN','NBA_OFFICIAL_PDF'))
                                if isinstance(sources,list) else []))
                    count=diag.get('missing_absence_count')
                    status=diag.get('official_http_status')
                    source_code=diag.get('official_code')
                    if not (isinstance(source_code,str) and 4<=len(source_code)<=110 and
                            all(ch in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ_0123456789' for ch in source_code)):
                        source_code=None
                    index_origin=diag.get('official_discovery_mode')
                    if index_origin not in ('LIVE_OFFICIAL_INDEX',
                            'LIVE_NBA_COM_OFFICIAL_INDEX','EXPLICIT_OFFICIAL_CDN_LINK'):
                        index_origin=None
                    original_denial=diag.get('index_failure')
                    original_denial=original_denial if isinstance(original_denial,dict) else {}
                    alternate_denial=diag.get('alternate_index_failure')
                    alternate_denial=alternate_denial if isinstance(alternate_denial,dict) else {}
                    alternate_http=alternate_denial.get('http_status')
                    self.progress['player_input_corroboration']=dict(
                        official_code=source_code,
                        official_discovery_mode=index_origin,
                        legacy_index_denied_403=original_denial.get('http_status')==403,
                        nba_com_alternate_index_http_status=(alternate_http if
                            type(alternate_http) is int and 100<=alternate_http<=599 else None),
                        missing_absence_count=count if type(count) is int and 0<=count<=100 else None,
                        examples=summaries,
                        official_stage=diag.get('official_stage') if diag.get('official_stage') in
                            ('INDEX_FETCH','INDEX_DISCOVERY','PDF_FETCH','PDF_ARCHIVE','PDF_EXTRACTION','PLAYER_IDENTITIES','FIXTURE_ROWS') else None,
                        official_http_status=status if type(status) is int and 100<=status<=599 else None,
                        latest_report_verified=diag.get('latest_report_verified') is True,
                        official_parsed_rows=diag.get('official_parsed_rows') if
                            type(diag.get('official_parsed_rows')) is int else None,
                        official_expected_matchup=diag.get('official_expected_matchup') if
                            isinstance(diag.get('official_expected_matchup'),str) and
                            3<=len(diag['official_expected_matchup'])<=9 else None,
                        official_report_matchups_seen=[s for s in
                            (diag.get('official_report_matchups_seen') or [])[:40]
                            if isinstance(s,str) and 3<=len(s)<=9 and
                            all(ch in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ@' for ch in s)]
                            if isinstance(diag.get('official_report_matchups_seen'),list) else [],
                        official_fixture_rows=diag.get('official_fixture_rows') if
                            type(diag.get('official_fixture_rows')) is int else None)
                report['player_inputs']={k:result.get(k) for k in ('fixture_id','status','reason','projection','new_record')}
            # A new adaptive model forecast must NEVER skip original
            # prefixture admission. The source-only minute probe above has
            # no model score to publish and is safe to do first.
            self._phase('ADMIT_UNSTARTED_ORIGINALS',eligible_future_fixtures=len(cases),
                        admission_done=0,admission_skipped_after_cutoff=0,
                        admission_total=len(cases))
            for i,c in enumerate(cases):
                self.progress['admission_position']=i+1
                if int(time.time())>=c['target']['fixture_start_utc']-900:
                    self.progress['admission_skipped_after_cutoff']+=1
                    continue  # Past cutoff is NOT a new prefixture admission.
                await asyncio.to_thread(self.research.admit,c['target'],c['original'])
                self.progress['admission_done']+=1
            scopes=sorted({(c['code'],c['target']['season']) for c in cases})
            if scopes:
                code,season=scopes[(self.sequence-1)%len(scopes)]
                selected=[c for c in cases if (c['code'],c['target']['season'])==(code,season)]
                year=int(season.split('/')[0]);league=selected[0]['target']['league']
                self._phase('REFRESH_NATIVE_HISTORY',source_scope=code)
                await asyncio.to_thread(self.refresh_native_history,code,year)
                self._phase('READ_NATIVE_HISTORICAL_GAMES')
                cohort=await asyncio.to_thread(self.store.cohort,code,year,int(time.time()))
                self._phase('FETCH_MISSING_NATIVE_BOXSCORES')
                boxes=await asyncio.to_thread(self.store.acquire_boxes,cohort)
                self._phase('VERIFY_NATIVE_BOX_COHORT')
                cohort=await asyncio.to_thread(self.store.cohort,code,year,int(time.time()))
                state=dict(season=season,native_training_games=len(cohort),native_box_games=sum(bool(v[0].get('box')) for v in cohort),acquisition=boxes)
                try:
                    self._phase('FIT_TIME_ELIGIBLE_ADAPTIVE_MODEL')
                    artifact,new=await asyncio.to_thread(self.research.fit,cohort,league,season)
                    state.update(status='SCHEDULED_MODEL_AVAILABLE',new_model=new,model_sha256=artifact['sha256'],
                        fit_cutoff_utc=artifact['payload']['cutoff_utc'],player_readiness=artifact['payload']['player_readiness'])
                    saved={r['payload']['fixture']['canonical_id'] for r in self.research.registry.records()}
                    ready=[c for c in selected if c['target']['fixture_id'] not in saved and
                           self.retry.get(c['target']['fixture_id'],0)<=int(time.time())]
                    for c in ready[:2]:
                        fid=c['target']['fixture_id']
                        if self.retry.get(fid,0)>int(time.time()):continue
                        try:
                            self._phase('CAPTURE_ORIGINAL_LINKED_ADAPTIVE_SHADOW')
                            p,created=await asyncio.to_thread(self.research.capture,c['target'],c['original'],artifact,self.verify,frozen=c['frozen'])
                            report['captures'].append(dict(fixture_id=fid,status='ARCHIVED' if created else 'REPLAY',forecast_sha256=digest(p)))
                        except (ValueError,KeyError,TypeError,OSError) as exc:
                            self.retry[fid]=int(time.time())+300
                            report['captures'].append(dict(fixture_id=fid,status='ABSTAIN',reason='ADAPTIVE_INPUT_SOURCE_OR_CAPTURE_UNAVAILABLE',error_type=type(exc).__name__))
                except (ValueError,KeyError,TypeError,OSError) as exc:
                    state.update(status='ABSTAIN',reason='ADAPTIVE_NATIVE_BOX_HISTORY_OR_MODEL_INSUFFICIENT',error_type=type(exc).__name__)
                self.group_reports[code]=dict(state,observed_at_utc=int(time.time()))
            if player_case is not None and (report.get('player_inputs') or {}).get('status') in ('PROSPECTIVE_MINUTES_ARCHIVED','EXISTING_MINUTES_REPLAY'):
                c=player_case;fid=c['target']['fixture_id']
                def player_capture():
                    files=list(self.research.models.glob('model-*.json'))
                    if len(files)>4096:raise ValueError('ADAPTIVE_MODEL_SCAN_BUDGET')
                    models=[read_wrapper(f) for f in files]
                    models=[m for m in models if m['payload']['league']=='NBA' and m['payload']['season']==c['target']['season'] and
                            m['payload']['player_pair'] is not None and 0<=int(time.time())-m['payload']['cutoff_utc']<=21600]
                    if not models:raise Abstain('ADAPTIVE_PROSPECTIVE_PLAYER_MODEL_NOT_READY')
                    model=max(models,key=lambda m:m['payload']['prepared_at_utc'])
                    return self.research.capture_player(c['target'],c['original'],model,self.verify)
                self._phase('PLAYER_BAYES_SHADOW_CANDIDATE',fixture_id=fid)
                try:
                    p,new=await asyncio.to_thread(player_capture)
                    report['player_capture']=dict(status='ARCHIVED' if new else 'REPLAY',forecast_sha256=digest(p),fixture_id=fid)
                except (ValueError,KeyError,TypeError,OSError):
                    report['player_capture']=dict(status='ABSTAIN',reason='ADAPTIVE_PROSPECTIVE_PLAYER_MODEL_OR_FRESH_INPUTS_REQUIRED')
            report['groups']=dict(self.group_reports)
            self._phase('REVIEW_ACTUAL_MODEL_METRICS')
            report['performance']=await asyncio.to_thread(self.research.performance,await asyncio.to_thread(self.labels))
            report['completed_at_utc']=int(time.time())
            if any(g['status']=='ABSTAIN' for g in report['groups'].values()) or any(c['status']=='ABSTAIN' for c in report['captures']):report['status']='PARTIAL_ABSTAIN'
            if (report.get('player_inputs') or {}).get('status')=='BLOCKED' or (report.get('player_capture') or {}).get('status')=='ABSTAIN':
                report['status']='PARTIAL_ABSTAIN'
            if (any(c['status']=='ARCHIVED' for c in report['captures']) or
                    (report.get('player_capture') or {}).get('status')=='ARCHIVED' or
                    any(g.get('new_model') for g in report['groups'].values()) or int(time.time())-self.last_journal>=3600):
                self._phase('ARCHIVE_SEPARATE_RESEARCH_REPORT')
                await asyncio.to_thread(self.journal.publish,report);self.last_journal=int(time.time())
            self._phase('COMPLETED',completion_status=report['status'])
            self.last_report=report;return report
        except (ValueError,KeyError,TypeError,OSError,sqlite3.Error,RuntimeError) as exc:
            # Only internal uppercase error identifiers appear in Telegram.
            failure_phase=self.progress.get('phase','UNKNOWN')
            candidate=str(exc)
            safe=(candidate if 4<=len(candidate)<=110 and
                  candidate.startswith(('ADAPTIVE_','NATIVE_','NBA_','ISSUE90_','CURRENT_','PLAYER_')) and
                  all(ch in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ_0123456789' for ch in candidate)
                  else 'ADAPTIVE_PLAN_SOURCE_OR_ARCHIVE_UNAVAILABLE')
            self._phase('ABSTAIN',failure_type=type(exc).__name__,failure_code=safe)
            report.update(status='ABSTAIN',reason=safe,error_type=type(exc).__name__,
                          failed_phase=failure_phase)
            self.last_report=report;return report
        finally:self.running=False

    async def run(self,app):
        while True:
            try:app.bot_data['last_adaptive_v2_poll']=await self.tick()
            except asyncio.CancelledError:raise
            except Exception as exc:
                LOG.error('Adaptive V2 background failure: %s',type(exc).__name__)
                self.last_report=dict(status='ABSTAIN',reason='ADAPTIVE_BACKGROUND_UNAVAILABLE',error_type=type(exc).__name__)
                app.bot_data['last_adaptive_v2_poll']=self.last_report
            await asyncio.sleep(60)

    def render(self,league=None,fixture=None):
        lines=['🧪 AYRI ADAY MODEL ARAŞTIRMASI | V2','Aktif skor ve eski deney değiştirilmedi.','NOT_CALIBRATED · Güven endeksi yok.']
        last=self.last_report or {};lines.append('Son kontrol: '+last.get('status','HENÜZ_ÇALIŞMADI'))
        if last.get('reason'):lines.append('Engel: '+last['reason'])
        if last.get('failed_phase'):lines.append('Hatanın gerçekleştiği aşama: '+last['failed_phase'])
        if last.get('error_type'):lines.append('Hata sınıfı: '+last['error_type'])
        if last.get('protocol_sha256'):lines.append('Ayrı V2 planı: '+last['protocol_sha256'][:12])
        for code,g in last.get('groups',{}).items():
            if league and code!=league:continue
            lines.append(f"{code}: {g['status']} · Geçmiş maç {g['native_training_games']} · Box-score {g['native_box_games']}")
            for reason,n in g.get('acquisition',{}).get('failure_classes',{}).items():lines.append('Kaynak engeli: '+reason+' · '+str(n))
            if g.get('fit_cutoff_utc'):lines.append('Eğitim kesiti: '+tsi(g['fit_cutoff_utc'])+' · Altı saatlik hazırlama dilimi')
            player=g.get('player_readiness',{})
            if code=='NBA':lines.append('Oyuncu modeli: '+player.get('status','HENÜZ_HAZIR_DEĞİL')+' · Uygun dakika geçmişi '+str(player.get('eligible_games','?'))+'/100')
        player=last.get('player_inputs') or {}
        if player.get('status')=='BLOCKED':lines.append('Oyuncu girdisi engeli: '+str(player.get('reason','DOĞRULANMIŞ_VERİ_GEREKLİ')))
        for g in last.get('performance',{}).get('groups',[]):
            if league and g['league'].upper()!=league:continue
            lines.append(f"{g['league']} {g['season']}: eşleşmiş {g['matched']}/100 · gün {g['day_clusters']}/20 · {g['gate']}")
            for name,m in g.get('component_point_metrics',{}).items():
                lines.append(f"{name}: n={m['n']} · Takım MAE {m['team_mae']:.2f} · Toplam MAE {m['total_mae']:.2f}")
        if fixture:
            found=False;labels=self.labels()
            for entry in self.research.records():
                p=entry['payload'];g=p['fixture']
                if fixture not in [g['fixture_id'],*g.get('provider_fixture_ids',[])]:continue
                if league and g['league'].upper()!=league:continue
                found=True
                lines.append('Maç: '+fixture+' · Ayrı V2 üretim: '+tsi(p['prediction_generated_at_utc']))
                actual=next((r['actual'] for r in labels if r['fixture_id']==g['fixture_id'] and r['snapshot_sha256']==p['original_snapshot_sha256']),None)
                lines.append('Gerçek normal süre: '+(' – '.join(map(str,actual)) if actual is not None else 'Sonuç bekleniyor'))
                for name,c in p['components'].items():
                    if c['status']=='FORECAST_CREATED':
                        q=c['prediction'];lines.append(f"{name}: {q['home']:.2f} – {q['away']:.2f} · Toplam {q['total']:.2f}")
                    else:lines.append(name+': ABSTAIN · '+c['reason'])
            if not found:lines.append('Bu maç için ayrı V2 kaydı yok; geçmişe dönük tahmin oluşturulmadı.')
        lines.append('Tempo: box-score tahmini; ölçülmüş PBP pozisyonu değil. Oyuncu etkisi yalnız doğrulanmış dakika/model ile ayrı değerlendirilir.')
        return '\n'.join(lines)

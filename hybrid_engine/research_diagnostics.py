"""Observe existing research attempts without changing scientific source pins."""
from collections import Counter
import re
import asyncio
import time

from telegram_delivery import tsi


def code(value):
    if (type(value) is str and re.fullmatch(r'[A-Z][A-Z0-9_]{0,127}',value)
            and value.startswith(('ABSTAIN_','ADAPTIVE_','DYNAMIC_','ISSUE90_','SHADOW_',
                                   'NATIVE_','SOURCE_','NBA_','PLAYER_','CURRENT_','RULE_','MODEL_'))):return value
    return 'UNCLASSIFIED_RESEARCH_BLOCK'


def attempt_lines(title,attempt):
    if not attempt:return [title+': henüz gözlenmedi.']
    stamp,rows=attempt
    counts=Counter(row.get('status') for row in rows)
    line=title+': '+tsi(stamp)+' · '+', '.join(
        name+' '+str(counts[name]) for name in ('ARCHIVED','REPLAY','ABSTAIN') if counts[name])
    lines=[line]
    classes={'Abstain','ValueError','KeyError','TypeError','OSError','RuntimeError',
        'OperationalError','TimeoutError','MemoryError','LinAlgError','JSONDecodeError'}
    reasons=Counter((code(row.get('reason')),row.get('error_type') if
        type(row.get('error_type')) is str and row.get('error_type') in classes else None)
        for row in rows if row.get('status')=='ABSTAIN')
    lines.extend(title+' engeli: '+reason+' · '+str(n)+((' · '+error) if error else '')
        for (reason,error),n in sorted(reasons.items(),key=lambda item:(item[0][0],item[0][1] or ''))[:8])
    return lines


class ObservedResearch:
    """The original worker still owns all fitting/admission/publication policy.

    Keep the last attempted score and calibration diagnostics separately: a
    later idle/backoff tick must not hide why zero scores were published.
    Only in-memory status metadata is added, never forecasts or source assets.
    """
    def __init__(self,base):
        self.base=base;self.score_attempt=None;self.shadow_attempt=None

    def __getattr__(self,name):return getattr(self.base,name)

    @property
    def last_report(self):return self.base.last_report

    @last_report.setter
    def last_report(self,value):self.base.last_report=value

    def tick(self):
        report=self.base.tick()
        if not isinstance(report,dict):return report
        stamp=report.get('observed_at_utc')
        if type(stamp) is int and stamp>0:
            for field,attribute in (('captures','score_attempt'),('shadow_captures','shadow_attempt')):
                rows=report.get(field)
                if isinstance(rows,list) and rows:
                    metadata=[]
                    for row in rows[:32]:
                        if not isinstance(row,dict):continue
                        status=row.get('status')
                        metadata.append(dict(status=status if type(status) is str else 'UNKNOWN',
                            reason=code(row.get('reason')),error_type=row.get('error_type')
                            if type(row.get('error_type')) is str else None))
                    setattr(self,attribute,(stamp,metadata))
        return report

    def render(self):
        current=self.last_report or {}
        measured=current.get('performance') or {}
        ready=all(type(measured.get(k)) is int for k in ('admitted','published','matched'))
        lines=([self.base.render()] if ready else [
            '🧪 NBA V3 | ARAŞTIRMA KONTROLÜ BEKLENİYOR',
            'Son kontrol: '+current.get('status','HENÜZ_ÇALIŞMADI'),
            'Bu süreçte doğrulanmış sayaç raporu henüz hazırlanmadı.',
            'Kayıtlı maç/yayın sayıları henüz okunmadı; sıfır olarak yorumlanmaz.',
            'Mevcut arşiv ve deney planı korunuyor.'])
        if current.get('reason'):lines.append('V3 kontrol engeli: '+code(current['reason']))
        lines.extend(attempt_lines('V3 skor denemesi',self.score_attempt))
        lines.extend(attempt_lines('V3 kalibrasyon denemesi',self.shadow_attempt))
        lines.append('Skor üretimi ile kalibrasyon adayının koşulları ayrı değerlendirilir.')
        return '\n'.join(lines)


class ResearchCycle:
    """Serial, independently observed stages; V3 need not wait for V2 acquisition."""
    def __init__(self,worker,study,assessments=None):
        self.worker=worker;self.study=study;self.assessments=assessments;self.stages={}

    async def _stage(self,name,call,app,asynchronous=False):
        state=dict(status='QUEUED',queued_at_utc=int(time.time()))
        self.stages[name]=state
        def sync():
            state.update(status='RUNNING',started_at_utc=int(time.time()))
            return call()
        try:
            if asynchronous:
                state.update(status='RUNNING',started_at_utc=int(time.time()));value=await call()
            else:value=await asyncio.to_thread(sync)
            state.update(status='COMPLETED',completed_at_utc=int(time.time()))
            app.bot_data['last_'+name+'_poll']=value
        except asyncio.CancelledError:
            state['status']='CANCELLED';raise
        except Exception as exc:
            from hybrid_engine.issue90_research import reason
            value=dict(status='ABSTAIN',reason=reason(exc),error_type=type(exc).__name__)
            state.update(status='FAILED',completed_at_utc=int(time.time()),reason=code(value['reason']))
            app.bot_data['last_'+name+'_poll']=value
            if name=='issue90':self.study.last_report=value
            elif name=='adaptive_v2':self.worker.last_report=value
            elif self.assessments:self.assessments.last_report=value

    async def once(self,app):
        # V2 already collects native boxes and attempts the genuine NBA
        # player_minutes input packet. Start this source gate FIRST, not
        # after V3's potentially expensive independent calibration work.
        # Keep stages SERIAL: concurrent fits can corrupt source snapshots
        # or consume overlapping source quotas.
        # Read the player witness directory BEFORE the potentially slow
        # V2 network acquisition, so users immediately see a real blocker.
        # Refresh after V2, which may have appended a genuine new minute packet.
        players=getattr(getattr(self.worker,'research',None),'players',None)
        if players is not None:
            from hybrid_engine.player_shadow import readiness
            await self._stage('player_shadow',lambda:readiness(players),app)
        await self._stage('adaptive_v2',self.worker.tick,app,asynchronous=True)
        if players is not None:
            await self._stage('player_shadow',lambda:readiness(players),app)
        if self.study:await self._stage('issue90',self.study.tick,app)
        if self.assessments:await self._stage('current_assessment',self.assessments.tick,app)

    async def run(self,app):
        while True:
            await self.once(app);await asyncio.sleep(60)

    def render(self):
        lines=['Araştırma işçisi: oyuncu kanıtı ilk denetim → V2 → oyuncu kanıtı tekrar → V3 → değerlendirme']
        for name in ('adaptive_v2','player_shadow','issue90','current_assessment'):
            s=self.stages.get(name)
            if not s:lines.append(name+': İLK TUR BEKLENİYOR');continue
            elapsed=max(0,int(time.time())-s.get('started_at_utc',s['queued_at_utc']))
            lines.append(name+': '+s['status']+' · aşama başlangıcından '+str(elapsed)+' sn')
            if s.get('reason'):lines.append('Aşama engeli: '+s['reason'])
        return '\n'.join(lines)

"""Opt-in isolated NBA rotation research cycle; no production or ledger writes."""
import asyncio
from collections import defaultdict
from functools import partial
import time
import logging
from core.team_identity import digest
from hybrid_engine.data import Abstain,local_path
from hybrid_engine.time_policy import PREMATCH_MINIMUM_LEAD_SECONDS

RETRY_SECONDS=300
HORIZON_SECONDS=36*3600
START_LEAD_SECONDS=900
log=logging.getLogger(__name__)

def eligible(rows,now):
    grouped=defaultdict(list)
    for r in rows:grouped[r['fixture_id']].append(r)
    return sorted((v[0] for v in grouped.values() if len(v)==1
        and v[0]['league']=='NBA' and v[0]['actual'] is None
        and now+START_LEAD_SECONDS<=v[0]['fixture_start_utc']<=now+HORIZON_SECONDS),
        key=lambda r:(r['fixture_start_utc'],r['fixture_id']))

def publish(folder,prefix,payload,tip):
    from hybrid_engine.boxes import publish_json
    if int(time.time())>=tip-PREMATCH_MINIMUM_LEAD_SECONDS:
        raise Abstain('ROTATION_AUTO_PUBLICATION_WINDOW_CLOSED')
    pin=digest(payload)
    publish_json(folder/(prefix+pin+'.json'),dict(payload=payload,sha256=pin))
    return pin

def capture_one(root,ledger,row,rows,transport):
    from hybrid_engine import rotation_efficiency as factor
    from hybrid_engine import rotation_periods as period
    from hybrid_engine import rotation_joint as joint
    from hybrid_engine.adaptive_data import FeatureStore
    from hybrid_engine.historical_five import collect_historical
    from hybrid_engine.boxes import collect_boxes
    from hybrid_engine.player_inputs import load_snapshot
    root=local_path(root);folder=root/'player-shadow'
    tip=row['fixture_start_utc'];fid=row['fixture_id']
    snapshot=load_snapshot(ledger,fid)
    if digest(snapshot)!=row['snapshot_sha256'] or snapshot['fixture_start_utc']!=tip:
        raise ValueError('ROTATION_AUTO_SNAPSHOT_BINDING')
    cutoff=int(time.time())
    if cutoff>=tip-START_LEAD_SECONDS:raise Abstain('ROTATION_AUTO_START_WINDOW_CLOSED')
    # Check historical residual availability before any new provider requests.
    pool=joint.residual_pool(rows,row,cutoff)
    store=FeatureStore(root/'adaptive-v2/inputs',[root/'live-nba/assets'],
        lambda *a,**k: (_ for _ in ()).throw(RuntimeError('NETWORK_FORBIDDEN')))
    cohort=store.cohort('NBA',int(snapshot['season'].split('/')[0]),cutoff)
    games,_=factor.training_rows(cohort,cutoff)
    games=[g for g in games if g['season']==snapshot['season']]
    control=factor.fit(games,cutoff,players_enabled=False)
    candidate=factor.fit(games,cutoff,players_enabled=True)
    pgames,_=period.training_rows(cohort,cutoff)
    pgames=[g for g in pgames if g['season']==snapshot['season']]
    a=period.fit(pgames,cutoff,players_enabled=False)
    b=period.fit(pgames,cutoff,players_enabled=True)
    if int(time.time())>=tip-PREMATCH_MINIMUM_LEAD_SECONDS:
        raise Abstain('ROTATION_AUTO_PUBLICATION_WINDOW_CLOSED')
    # Existing box collector retains its cache, source cooldown and native identity checks.
    # No current injury index or roster source calls are needed.
    rotation=collect_historical(snapshot,root/'live-nba/assets',folder,
        box_collector=partial(collect_boxes,fetcher=transport))
    rotation={k:v for k,v in rotation.items() if k!='sha256'}
    result=factor.compare(rotation,snapshot,control,candidate,int(time.time()))
    for model in (control,candidate):
        publish(folder,'factor-model-',model['payload'],tip)
    factor_pin=publish(folder,'factor-score-',result,tip)
    result=period.capture(folder,result,factor_pin,snapshot,a,b,int(time.time()))
    for model in (a,b):publish(folder,'period-model-',model['payload'],tip)
    period_pin=publish(folder,'period-score-',result,tip)
    # Keep the exact source-time residual pool; new labels after the initial
    # decision are deliberately not admitted into this forecast.
    decision=int(time.time())
    pool=joint.residual_pool(rows,row,decision)
    sim=joint.simulate(result['player_allocation']['quarters'],pool)
    pool_pin=publish(folder,'joint-pool-',pool,tip)
    receipt=dict(format=joint.VERSION,status='FORWARD_JOINT_RESEARCH',fixture_id=fid,
        fixture_start_utc=tip,generated_at_utc=decision,original_snapshot_sha256=row['snapshot_sha256'],
        period_sha256=period_pin,original_model_version=row['model_version'],
        residual_games=len(pool),residual_pool_sha256=pool_pin,
        residual_model_digests=len({v['model_digest'] for v in pool}),simulation=sim,
        production_enabled=False,forecast_changed=False,calibrated=False)
    return publish(folder,'joint-score-',receipt,tip)

class RotationCycle:
    def __init__(self,root,ledger,transport,*,capture=capture_one,clock=time.time):
        self.root=local_path(root);self.ledger=local_path(ledger);self.transport=transport
        self.capture=capture;self.clock=clock;self.retry={};self.completed=set()
        self.last=dict(status='WAITING',enabled=True)
    def tick(self):
        from ledger_reports import LedgerReports
        from hybrid_engine.rotation_report import records
        now=int(self.clock())
        if not self.ledger.is_file():return dict(status='LEDGER_NOT_PRESENT',eligible=0)
        report=LedgerReports(self.ledger).read('NBA')
        if report['status']!='VERIFIED_LIVE_REPORT':raise ValueError('ROTATION_AUTO_LEDGER_UNVERIFIED')
        rows=eligible(report['forecasts'],now)
        keys={(r['fixture_id'],r['snapshot_sha256']) for r in rows}
        self.completed.intersection_update(keys)
        self.retry={k:v for k,v in self.retry.items() if k in keys}
        for row in rows:
            key=(row['fixture_id'],row['snapshot_sha256'])
            if key in self.completed or self.retry.get(key,0)>now:continue
            # Check the archive on restart. A valid first receipt is immutable.
            existing,_,_=records(self.root/'player-shadow',self.ledger,now=now,selector=row['fixture_id'])
            if any(e[4]['snapshot_sha256']==key[1] for e in existing):
                self.completed.add(key);continue
            try:
                pin=self.capture(self.root,self.ledger,row,report['forecasts'],self.transport)
                self.completed.add(key)
                return dict(status='CAPTURED',eligible=len(rows),fixture_id=key[0],
                    receipt_sha256=pin,completed=len(self.completed),calibrated=False)
            except Exception as exc:
                # Isolate failures per fixture; no new forecast is reported.
                self.retry[key]=int(self.clock())+RETRY_SECONDS
                reason=str(exc)
                safe=reason if reason.isupper() and len(reason)<100 and reason.replace('_','').isalnum() else type(exc).__name__
                return dict(status='ABSTAIN',eligible=len(rows),fixture_id=key[0],reason=safe,
                    retry_at_utc=self.retry[key],completed=len(self.completed))
        return dict(status='IDLE',eligible=len(rows),completed=len(self.completed),
                    retrying=sum(v>now for v in self.retry.values()))
    async def run(self):
        while True:
            try:self.last=await asyncio.to_thread(self.tick)
            except asyncio.CancelledError:raise
            except Exception as exc:
                self.last=dict(status='ABSTAIN',reason=type(exc).__name__)
                log.warning('Rotation cycle tick failed: %s',type(exc).__name__)
            await asyncio.sleep(RETRY_SECONDS)

    def render_status(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        r=self.last
        lines=['NBA OTOMATİK ROTASYON — İZOLE ARAŞTIRMA','Kalibre edilmedi; üretim tahmini değişmedi.',
            'Durum: '+r['status'], 'Uygun maç: '+str(r.get('eligible',0)),
            'Doğrulanmış/üretilmiş kayıt: '+str(r.get('completed',0))]
        if r.get('reason'):lines.append('Engel: '+r['reason'])
        if r.get('retry_at_utc'):
            lines.append('Yeniden deneme: '+datetime.fromtimestamp(r['retry_at_utc'],ZoneInfo('Europe/Istanbul')).strftime('%d.%m.%Y %H:%M TSİ'))
        if r.get('receipt_sha256'):lines.append('Kayıt: '+r['receipt_sha256'][:16])
        return '\n'.join(lines)

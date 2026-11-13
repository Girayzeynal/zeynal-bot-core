"""Bounded, read-only reports of committed live forecasts. No fitting or downloads."""
from collections import defaultdict
from contextlib import closing
import math
import os
from pathlib import Path
import sqlite3
import time

from core.league_identity import resolve_league
from core.team_identity import digest
from live_analysis_ledger import LiveAnalysisLedger
from season_archive_inventory import archive_catalog

MAX_ROWS = 1000
MAX_PAYLOAD_BYTES = 512*1024


class LedgerReports:
    def __init__(self, path):
        # Defer opening until a report is requested. Never create schema or a file.
        self.path = Path(path).absolute()

    def _result(self, raw, pin, forecast):
        import json
        r=json.loads(raw)
        if digest(r)!=pin or r.get('record_type')!='VERIFIED_FINAL_RESULT' or r.get('scope')!='REGULATION_ONLY':
            raise ValueError('REPORT_RESULT_PIN_OR_SCOPE')
        if (r['league'],r['fixture_id'])!=(forecast['league'],forecast['fixture_id']):raise ValueError('REPORT_RESULT_IDENTITY')
        if digest(r['source_fixture'])!=r['source_fixture_sha256']:raise ValueError('REPORT_NATIVE_RESULT_PIN')
        provider='ESPN' if r['league']=='NBA' else 'EUROLEAGUE_LIVE'
        native={'events':r['source_fixture']} if provider=='ESPN' else {'total':len(r['source_fixture']),'data':r['source_fixture']}
        options={} if provider=='ESPN' else dict(competition_code=resolve_league(r['league']).competition_code)
        b=archive_catalog(native,provider=provider,season_start_year=int(forecast['season'].split('/')[0]),
            observed_at_utc=r['observed_at_utc'],ingested_at_utc=r['ingested_at_utc'],**options)
        games=[g for g in b['payload']['fixtures'] if g['canonical_id']==forecast['fixture_id'] and g['completed'] and g['periods']]
        if len(games)!=1:raise ValueError('REPORT_NATIVE_FINAL_REQUIRED')
        g=games[0]
        if (g['home_team_id']!=forecast['home']['provider_id'] or g['away_team_id']!=forecast['away']['provider_id'] or
            not set(g['provider_fixture_ids'])&set(forecast['provider_fixture_ids']) or
            g['final_scores']!=r['final_with_ot'] or g['periods']!=r['periods'] or
            [sum(g['periods'][s][:4]) for s in ('home','away')]!=r['actual']):
            raise ValueError('REPORT_NATIVE_SCORE_CONFLICT')
        return r

    def read(self, league=None, fixture_id=None):
        code=None if league is None else resolve_league(league).code
        if fixture_id is not None and (not isinstance(fixture_id,str) or not 1<=len(fixture_id)<=128 or any(c.isspace() for c in fixture_id)):
            raise ValueError('REPORT_FIXTURE_ID_REQUIRED')
        if not self.path.is_file():return dict(status='ARCHIVE_UNAVAILABLE',groups=[],forecasts=[])
        if self.path.resolve()!=self.path:raise ValueError('REPORT_SYMLINK_REFUSED')
        with closing(sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True,timeout=.2)) as db:
            db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
            deadline=time.monotonic()+1
            db.set_progress_handler(lambda: int(time.monotonic()>deadline),1000)
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {'live_analysis_snapshots','live_analysis_commit_receipts','verified_analysis_results'}<=tables:
                return dict(status='NO_VERIFIED_LIVE_SCHEMA',groups=[],forecasts=[])
            where=[];args=[]
            if code:where.append('s.league=?');args.append(code)
            if fixture_id:where.append('(s.fixture_id=? OR EXISTS(SELECT 1 FROM json_each(s.payload,\'$.provider_fixture_ids\') p WHERE p.value=?))');args.extend([fixture_id,fixture_id])
            sql=f'''SELECT s.league,s.fixture_id,s.model_digest,
                CASE WHEN length(CAST(s.payload AS BLOB))<={MAX_PAYLOAD_BYTES} THEN s.payload END,
                s.sha256,r.snapshot_sha256,r.completed_utc,
                CASE WHEN length(CAST(o.payload AS BLOB))<={MAX_PAYLOAD_BYTES} THEN o.payload END,
                o.sha256,length(CAST(s.payload AS BLOB)),length(CAST(o.payload AS BLOB))
                FROM live_analysis_snapshots s JOIN live_analysis_commit_receipts r USING(league,fixture_id,model_digest)
                LEFT JOIN verified_analysis_results o ON o.league=s.league AND o.fixture_id=s.fixture_id AND o.scope='REGULATION_ONLY' '''
            if where:sql+=' WHERE '+' AND '.join(where)
            sql+=' ORDER BY s.league,s.fixture_id,s.model_digest LIMIT ?';args.append(MAX_ROWS+1)
            forecasts=[];groups=defaultdict(list);identities=set()
            for row in db.execute(sql,args):
                league,fixture,model,raw,pin,receipt,completed,outcome,opin,size,osize=row
                if len(forecasts)>=MAX_ROWS:raise ValueError('REPORT_SCAN_LIMIT')
                if size>MAX_PAYLOAD_BYTES or (osize or 0)>MAX_PAYLOAD_BYTES:raise ValueError('REPORT_PAYLOAD_LIMIT')
                p=LiveAnalysisLedger._decode(raw,pin,expected=(league,fixture,model))
                if receipt!=pin or not p['created_at_utc']<=completed<p.get('record_deadline_utc',p['fixture_start_utc']):
                    raise ValueError('REPORT_COMMIT_PROOF_CONFLICT')
                if p.get('scope')!='REGULATION_ONLY':raise ValueError('REPORT_FORECAST_SCOPE')
                scores=[p['prediction'][s] for s in ('home','away')]
                if not all(type(v) in (int,float) and math.isfinite(v) and v>=0 for v in scores):raise ValueError('REPORT_SCORE_REQUIRED')
                item=dict(fixture_id=fixture,league=league,model_version=p['model_version'],model_digest=model,
                    prediction=scores,created_utc=p['created_at_utc'],snapshot_sha256=pin,actual=None,
                    home=p['home'].get('official_name',p['home']['provider_id']),away=p['away'].get('official_name',p['away']['provider_id']))
                if outcome:
                    result=self._result(outcome,opin,p);item['actual']=result['actual']
                    if result['observed_at_utc']<=p['fixture_start_utc']:raise ValueError('REPORT_FINAL_BEFORE_TIPOFF')
                    groups[(league,model,p['model_version'])].append(item)
                forecasts.append(item);identities.add((league,fixture))
        metrics=[]
        for (league,model,version),rows in sorted(groups.items()):
            errors=[p-a for r in rows for p,a in zip(r['prediction'],r['actual'])]
            totals=[sum(r['prediction'])-sum(r['actual']) for r in rows]
            metrics.append(dict(league=league,model_digest=model,model_version=version,n=len(rows),
                team_mae=sum(map(abs,errors))/len(errors),team_rmse=math.sqrt(sum(e*e for e in errors)/len(errors)),
                total_mae=sum(map(abs,totals))/len(totals),claim='DESCRIPTIVE_ONLY_NOT_MODEL_SUPERIORITY'))
        return dict(status='VERIFIED_LIVE_REPORT',scope='REGULATION_ONLY',groups=metrics,forecasts=forecasts,
            unique_fixtures=len(identities),pending=sum(r['actual'] is None for r in forecasts),
            research_backtests_included=False,query_read_only=True)


def render_accuracy(report):
    if report['status']!='VERIFIED_LIVE_REPORT':return 'Doğrulanmış canlı tahmin arşivi kullanılamıyor. Başarı oranı hesaplanmadı.'
    lines=['ZEYNAL | DOĞRULANMIŞ CANLI PERFORMANS | Normal süre',
        f"Kayıtlı maç: {report['unique_fixtures']} | Sonucu beklenen tahmin: {report['pending']}"]
    if not report['groups']:lines.append('Doğrulanmış sonuç: 0. Başarı oranı ve kalibrasyon hesaplanamadı.')
    for g in report['groups'][:12]:
        lines.append(f"{g['league']} | {g['model_version'][:100]} | n={g['n']} | MAE {g['team_mae']:.2f} | RMSE {g['team_rmse']:.2f} | Toplam MAE {g['total_mae']:.2f}")
    if len(report['groups'])>12:lines.append('İlk 12 model grubu gösterildi; lig filtresi kullanın.')
    lines.append('Araştırma backtestleri dahil değil. Bu değerler model üstünlüğü veya güven yüzdesi değildir.')
    return '\n'.join(lines)


def render_compare(report):
    rows=report['forecasts']
    if not rows:return 'Bu maç için doğrulanmış kayıtlı model sürümü bulunamadı.'
    if len({(r['league'],r['fixture_id']) for r in rows})!=1:raise ValueError('REPORT_AMBIGUOUS_FIXTURE')
    lines=['ZEYNAL | KAYITLI MODEL KARŞILAŞTIRMASI | Normal süre',rows[0]['home']+' – '+rows[0]['away']]
    for r in rows[:12]:
        text=f"{r['model_version'][:100]} | {r['model_digest'][:12]} | Skor {r['prediction'][0]:.2f} – {r['prediction'][1]:.2f}"
        if r['actual'] is None:text+=' | Sonuç bekleniyor'
        else:text+=f" | Gerçek {r['actual'][0]} – {r['actual'][1]}"
        lines.append(text)
    if len(rows)==1:lines.append('Tek kayıtlı model; karşılaştırılacak ikinci doğrulanmış sürüm yok.')
    if len(rows)>12:lines.append('İlk 12 kayıt gösterildi.')
    lines.append('Kayıtlı olmayan hibrit modeller için sonuç üretilmedi. Model üstünlüğü çıkarılamaz.')
    return '\n'.join(lines)


async def accuracy_command(update,context):
    args=context.args or []
    if len(args)>1:
        await update.effective_message.reply_text('Kullanım: /accuracy [NBA|EUROLEAGUE|EUROCUP]');return
    await _reply(update,context,args[0] if args else None,None,render_accuracy)


async def compare_command(update,context):
    args=context.args or []
    if len(args)!=2:
        await update.effective_message.reply_text('Kullanım: /compare NBA maç_kimliği');return
    await _reply(update,context,args[0],args[1],render_compare)


async def _reply(update,context,league,fixture,renderer):
    import asyncio
    service=context.application.bot_data['ledger_reports']
    try:
        report=await asyncio.to_thread(service.read,league,fixture)
        text=getattr(service,renderer.__name__,renderer)(report)
    except (ValueError,KeyError,TypeError,sqlite3.Error,OSError,RuntimeError):
        text='Arşiv doğrulanamadı veya istek geçersiz. Performans sonucu üretilmedi.'
    await update.effective_message.reply_text(text,disable_web_page_preview=True)


def production_reports():
    return LedgerReports(os.getenv('PREDICTION_LEDGER_DB','/data/prediction_ledger.sqlite'))

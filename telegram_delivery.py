"""UTC delivery sidecars. Forecast snapshots are never edited to look newly generated."""
import asyncio
from datetime import datetime,timezone
import html
import json
from pathlib import Path
import sqlite3
import time
from zoneinfo import ZoneInfo

from core.team_identity import digest
from projection_integrity import assert_projection


def tsi(value):
    if value is None:return 'ayrı kaydedilmemiş / bilinmiyor'
    if type(value) is not int or value<=0:raise ValueError('UTC_INTEGER_REQUIRED')
    return datetime.fromtimestamp(value,ZoneInfo('Europe/Istanbul')).strftime('%d.%m.%Y %H:%M:%S TSİ')


class DeliveryJournal:
    """Dedicated test journal, physically separate from any prediction SQLite file."""
    def __init__(self,path):
        self.path=Path(path).absolute()
        if self.path.resolve()!=self.path or Path('/data') in self.path.parents or not self.path.parent.is_dir():
            raise ValueError('ISOLATED_DELIVERY_PATH_REQUIRED')
        with sqlite3.connect(self.path) as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS delivery_events
              (event_key TEXT PRIMARY KEY,payload TEXT NOT NULL,sha256 TEXT NOT NULL);
              CREATE TRIGGER IF NOT EXISTS delivery_no_update BEFORE UPDATE ON delivery_events
                BEGIN SELECT RAISE(ABORT,'IMMUTABLE_DELIVERY_EVENT'); END;
              CREATE TRIGGER IF NOT EXISTS delivery_no_delete BEFORE DELETE ON delivery_events
                BEGIN SELECT RAISE(ABORT,'IMMUTABLE_DELIVERY_EVENT'); END;''')

    def append(self,key,payload):
        if self.path.resolve()!=self.path:raise ValueError('DELIVERY_SYMLINK_REFUSED')
        body=json.dumps(payload,sort_keys=True,allow_nan=False)
        with sqlite3.connect(self.path,timeout=.2) as db:
            db.execute('INSERT OR IGNORE INTO delivery_events VALUES(?,?,?)',(key,body,digest(payload)))
            raw,pin=db.execute('SELECT payload,sha256 FROM delivery_events WHERE event_key=?',(key,)).fetchone()
        old=json.loads(raw)
        if digest(old)!=pin:raise ValueError('DELIVERY_HASH_MISMATCH')
        return old

    def read(self):
        with sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True) as db:
            rows=db.execute('SELECT payload,sha256 FROM delivery_events ORDER BY rowid').fetchall()
        values=[]
        for raw,pin in rows:
            p=json.loads(raw)
            if digest(p)!=pin:raise ValueError('DELIVERY_HASH_MISMATCH')
            values.append(p)
        return values

    def get(self,key):
        with sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True,timeout=.2) as db:
            row=db.execute('SELECT payload,sha256 FROM delivery_events WHERE event_key=?',(key,)).fetchone()
        if row is None:return None
        p=json.loads(row[0])
        if digest(p)!=row[1]:raise ValueError('DELIVERY_HASH_MISMATCH')
        return p


def timeline(report,service,now):
    if 'timeline' in report:return dict(report['timeline'],response_prepared_at_utc=now)
    p=report.get('snapshot')
    if p is None:return None
    archived=None;ledger=getattr(service,'ledger',None)
    if ledger is not None:
        path=ledger.path
        with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=.2) as db:
            row=db.execute('SELECT snapshot_sha256,completed_utc FROM live_analysis_commit_receipts WHERE league=? AND fixture_id=? AND model_digest=?',
                (p['league'],p['fixture_id'],p['model_digest'])).fetchone()
        if row:
            if row[0]!=digest(p):raise ValueError('TIMELINE_COMMIT_PROOF_CONFLICT')
            archived=row[1]
    return dict(prediction_generated_at_utc=p.get('prediction_generated_at_utc'),
        snapshot_created_at_utc=p['created_at_utc'],first_archived_at_utc=archived,
        archive_published_at_utc=archived,tipoff_utc=p.get('fixture_start_utc'),telegram_reply_at_utc=None,
        response_prepared_at_utc=now,telegram_sent_at_utc=None,
        snapshot_sha256=digest(p),reused_forecast=report.get('new_record') is False)


def render_timeline(text,times):
    if times is None:return text
    text=text.replace('\nKayıt: ','\nİlk snapshot kaydı: ',1)
    lines=[text]
    if times.get('reused_forecast'):lines.append('Mevcut tahmin yeniden gösteriliyor; yeniden üretilmedi.')
    lines.extend(['Üretim: '+tsi(times.get('prediction_generated_at_utc')),
        'İlk kalıcı arşiv: '+tsi(times.get('first_archived_at_utc')),
        'Yanıt hazırlandı: '+tsi(times['response_prepared_at_utc'])])
    # The server's accepted-send time is only known AFTER sendMessage completes.
    lines.append('Telegram gönderim zamanı: başarılı API yanıtında ayrı teslim kaydına alınır.')
    value='\n'.join(lines)
    if len(value.encode('utf-16-le'))//2>4096:raise ValueError('TIMELINE_MESSAGE_BUDGET')
    return value


async def reply_analysis(update,context,report,service):
    now=int(time.time())
    p=report.get('snapshot',{}).get('prediction',{})
    if 'quarters' in p:assert_projection(p)
    times=await asyncio.to_thread(timeline,report,service,now)
    parts=list(report.get('html_parts') or [report['html']])
    parts[-1]=render_timeline(parts[-1],times)
    journal=context.application.bot_data.get('delivery_journal')
    key=digest(dict(update_id=update.update_id,chat=update.effective_chat.id,kind='ANALYZE')) if journal else None
    for i,text in enumerate(parts):
        if len(text.encode('utf-16-le'))//2>4096:raise ValueError('TELEGRAM_MESSAGE_BUDGET')
        part_key=key+':part:'+str(i) if journal else None
        request_pin=digest(getattr(update.message,'text',''))
        prior=await asyncio.to_thread(journal.get,part_key+':result') if journal else None
        if prior:
            if prior.get('request_sha256')!=request_pin:raise ValueError('DELIVERY_UPDATE_ID_CONFLICT')
            if prior['status']!='TELEGRAM_ACCEPTED':raise ValueError('PRIOR_DELIVERY_UNCONFIRMED_NEW_USER_COMMAND_REQUIRED')
            from types import SimpleNamespace
            sent=SimpleNamespace(date=datetime.fromtimestamp(prior['telegram_sent_at_utc'],timezone.utc),message_id=prior['telegram_message_id'])
            continue
        event=dict(record_type='TELEGRAM_ANALYSIS_DELIVERY',timeline=times,update_id=getattr(update,'update_id',None),
            part_index=i,part_count=len(parts),request_sha256=request_pin,message_sha256=digest(text),attempted_at_utc=int(time.time()),telegram_sent_at_utc=None)
        if journal:await asyncio.to_thread(journal.append,part_key+':attempt',dict(event,status='ATTEMPTED'))
        try:sent=await update.message.reply_text(text,parse_mode='HTML',disable_web_page_preview=True)
        except Exception as exc:
            if journal:await asyncio.to_thread(journal.append,part_key+':result',dict(event,status='NOT_CONFIRMED',error_type=type(exc).__name__))
            raise
        if journal:
            date=getattr(sent,'date',None)
            stamp=int(date.timestamp()) if isinstance(date,datetime) and date.tzinfo is not None else None
            await asyncio.to_thread(journal.append,part_key+':result',dict(event,
                status='TELEGRAM_ACCEPTED' if stamp is not None else 'SERVER_DATE_UNAVAILABLE',
                telegram_sent_at_utc=stamp,telegram_reply_at_utc=stamp,telegram_ack_at_utc=int(time.time()),
                telegram_message_id=getattr(sent,'message_id',None)))
    return sent

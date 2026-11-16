"""Read-only isolated Telegram prediction listing with fixed-code diagnostics."""
import asyncio
import logging
import math
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram.ext import ApplicationHandlerStop

log=logging.getLogger(__name__)
PAGE_SIZE=25
VERSION='PHASE91_PREDICTIONS_V1'


def stamp(value):
    if value is None:return 'ayrı kaydedilmemiş / bilinmiyor'
    if type(value) is not int or value<=0:raise ValueError('PREDICTIONS_UTC_INTEGER_REQUIRED')
    return datetime.fromtimestamp(value,ZoneInfo('Europe/Istanbul')).strftime('%d.%m.%Y %H:%M:%S TSİ')


def split_plain(text,limit=3500):
    """Preserve whole lines when possible and all bytes/codepoints in UTF-16 budget."""
    if type(limit) is not int or limit<2:raise ValueError('TELEGRAM_TEXT_LIMIT_REQUIRED')
    chunk='';units=0
    for line in text.splitlines(keepends=True):
        n=len(line.encode('utf-16-le'))//2
        if units+n<=limit:chunk+=line;units+=n;continue
        if chunk:yield chunk;chunk='';units=0
        if n<=limit:chunk=line;units=n;continue
        # A single oversized native text line is split without losing data.
        chars=[]
        for char in line:
            width=len(char.encode('utf-16-le'))//2
            if units+width>limit:
                yield ''.join(chars);chars=[];units=0
            chars.append(char);units+=width
        chunk=''.join(chars)
    if chunk:yield chunk


def label(value,limit=180):
    value=str(value).replace('\r',' ').replace('\n',' ')
    return value if len(value)<=limit else value[:limit]+'… [gösterim kısaltıldı]'


def render_predictions(report,page=1):
    if report.get('status')!='VERIFIED_LIVE_REPORT':return ['Doğrulanmış canlı NBA tahmin arşivi kullanılamıyor; kayıtlar değiştirilmedi.']
    rows=sorted(report['forecasts'],key=lambda r:(r['fixture_start_utc'],r['fixture_id'],r['model_digest']),reverse=True)
    pages=max(1,math.ceil(len(rows)/PAGE_SIZE))
    if not 1<=page<=pages:return [f'Sayfa bulunamadı. Kullanım: /predictions NBA [1–{pages}]']
    lines=['ZEYNAL | KAYITLI NBA TAHMİNLERİ | Normal süre',
        f"Maç: {report['unique_fixtures']} | Tahmin: {len(rows)} | Sonuç bekleyen: {report['pending']}",
        f'Sayfa {page}/{pages} | Salt okunur arşiv; yeni tahmin üretilmedi.']
    if not rows:lines.append('Doğrulanmış, kalıcı NBA tahmini bulunamadı.')
    for r in rows[(page-1)*PAGE_SIZE:page*PAGE_SIZE]:
        ids=r['provider_fixture_ids']
        if not ids or any(not isinstance(i,str) or not i.isascii() or not i.isdigit() for i in ids):raise ValueError('PREDICTIONS_ESPN_IDS_REQUIRED')
        compare=ids[0] if len(ids)==1 else r['fixture_id']
        lines.extend(['',label(r['home'])+' – '+label(r['away']),
            'ESPN kimliği: '+', '.join(ids),
            'Maç: '+stamp(r['fixture_start_utc']),
            'İlk üretim: '+stamp(r.get('prediction_generated_at_utc')),
            'İlk snapshot: '+stamp(r['created_utc']),
            'İlk kalıcı arşiv: '+stamp(r['first_archived_at_utc']),
            f"Tahmin: {r['prediction'][0]:.2f} – {r['prediction'][1]:.2f} | Toplam: {sum(r['prediction']):.2f}",
            'Model: '+label(r['model_version'])+' | '+r['model_digest'],
            'Durum: '+('SONUÇ BEKLENİYOR' if r['actual'] is None else 'SONUÇ DOĞRULANDI'),
            'Gerçek normal süre skoru: '+('henüz doğrulanmadı' if r['actual'] is None else f"{r['actual'][0]} – {r['actual'][1]}"),
            '/compare NBA '+compare])
        if r.get('final_with_ot') is not None and r['final_with_ot']!=r['actual']:
            lines.append(f"Uzatma dahil final: {r['final_with_ot'][0]} – {r['final_with_ot'][1]} (normal süre metriğine katılmadı)")
    if page<pages:lines.append(f'\nDevamı: /predictions NBA {page+1}')
    return list(split_plain('\n'.join(lines)))


class PredictionsCommand:
    version=VERSION
    def __init__(self,reports,journal,chat_id,*,read_timeout=5,send_timeout=15):
        self.reports=reports;self.journal=journal;self.chat_id=chat_id
        self.read_timeout=read_timeout;self.send_timeout=send_timeout

    async def event(self,update,kind,**fields):
        import time
        from core.team_identity import digest
        event=dict(kind=kind,update_id=getattr(update,'update_id',None),observed_at_utc=int(time.time()),**fields)
        try:
            await asyncio.wait_for(asyncio.to_thread(self.journal.append,digest(dict(update=event['update_id'],kind=kind,part=fields.get('part'))),event),timeout=2)
        except Exception as exc:
            log.error('Predictions diagnostics unavailable: %s',type(exc).__name__)

    async def send(self,update,parts):
        message=update.effective_message
        for i,part in enumerate(parts):
            await self.event(update,'PREDICTIONS_SEND_ATTEMPT',part=i,parts=len(parts))
            try:
                await asyncio.wait_for(message.reply_text(part,disable_web_page_preview=True),timeout=self.send_timeout)
                await self.event(update,'PREDICTIONS_SENT',part=i,parts=len(parts))
            except Exception as exc:
                await self.event(update,'PREDICTIONS_SEND_FAILED',part=i,error_type=type(exc).__name__)
                log.warning('Predictions send failed: %s',type(exc).__name__)
                # Do not resend the full list: a timeout may have been accepted by
                # Telegram. Rate limits/forbidden chats cannot be fixed by retrying.
                from telegram.error import RetryAfter,Forbidden
                if not isinstance(exc,(RetryAfter,Forbidden)):
                    try:
                        await asyncio.wait_for(message.reply_text('Tahmin listesi gönderimi tamamlanamadı. Kayıtlar korunuyor. Kod: PREDICTIONS_SEND_FAILED',disable_web_page_preview=True),timeout=self.send_timeout)
                        await self.event(update,'PREDICTIONS_ERROR_NOTICE_SENT',part=i)
                    except Exception as notice:
                        await self.event(update,'PREDICTIONS_ERROR_NOTICE_FAILED',part=i,error_type=type(notice).__name__)
                return

    async def handle(self,update,context):
        if update.effective_chat is None or update.effective_chat.id!=self.chat_id:raise ApplicationHandlerStop
        if update.effective_message is None:raise ApplicationHandlerStop
        await self.event(update,'PREDICTIONS_STARTED',handler_version=VERSION)
        args=context.args or [];page=1
        if len(args)>2 or (args and args[0].upper()!='NBA') or (len(args)==2 and (len(args[1])>4 or not args[1].isascii() or not args[1].isdigit() or not 1<=int(args[1])<=1000)):
            await self.send(update,['Kullanım: /predictions NBA [sayfa]']);raise ApplicationHandlerStop
        if len(args)==2:page=int(args[1])
        if self.reports is None:
            await self.send(update,['Canlı NBA tahmin arşivi bu modda kullanılamıyor. Araştırma modeli yüklenmedi; yeni tahmin üretilmedi.']);raise ApplicationHandlerStop
        try:
            report=await asyncio.wait_for(asyncio.to_thread(self.reports.read,'NBA',None),timeout=self.read_timeout)
            parts=render_predictions(report,page)
            await self.event(update,'PREDICTIONS_READ_OK',records=len(report.get('forecasts',[])))
        except asyncio.TimeoutError:
            await self.event(update,'PREDICTIONS_READ_FAILED',error_type='TimeoutError')
            parts=['Tahmin arşivini okuma zaman aşımına uğradı. Kayıtlar değiştirilmedi. Kod: PREDICTIONS_READ_TIMEOUT']
        except Exception as exc:
            await self.event(update,'PREDICTIONS_READ_FAILED',error_type=type(exc).__name__)
            parts=['Tahmin arşivi doğrulanamadı veya okunamadı. Kayıtlar değiştirilmedi. Kod: PREDICTIONS_ARCHIVE_UNAVAILABLE']
        await self.send(update,parts)
        raise ApplicationHandlerStop

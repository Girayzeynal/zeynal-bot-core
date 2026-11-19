"""Bounded isolated-bot quality report; never opens a production archive."""
import asyncio
import time

from telegram.ext import ApplicationHandlerStop

from hybrid_engine.predictions_command import PredictionsCommand, split_plain
from hybrid_engine.quality_monitor import monitor, render_monitor


class HealthCommand(PredictionsCommand):
    version = 'PHASE92_HEALTH_COMMAND_V1'

    async def handle(self, update, context):
        if update.effective_chat is None or update.effective_chat.id != self.chat_id or update.effective_message is None:
            raise ApplicationHandlerStop
        await self.event(update, 'HEALTH_STARTED', handler_version=self.version)
        args = context.args or []
        if len(args) != 1 or args[0].upper() != 'NBA':
            await self.send(update, ['Kullanım: /health NBA'])
            raise ApplicationHandlerStop
        if self.reports is None:
            await self.send(update, ['Canlı araştırma arşivi bu modda yapılandırılmadı. Sağlık ölçümü yapılamadı.'])
            raise ApplicationHandlerStop
        def read():
            report = self.reports.read('NBA')
            if report.get('status') != 'VERIFIED_LIVE_REPORT':
                raise ValueError('HEALTH_NATIVE_REPORT_REQUIRED')
            return monitor(report['forecasts'], asof_utc=int(time.time()))
        try:
            result = await asyncio.wait_for(asyncio.to_thread(read), self.read_timeout)
            parts = list(split_plain(render_monitor(result)))
            await self.event(update, 'HEALTH_READ_OK', cohorts=len(result['groups']))
        except asyncio.TimeoutError:
            await self.event(update, 'HEALTH_READ_FAILED', error_type='TimeoutError')
            parts = ['Sağlık raporu okuma zaman aşımı. Arşiv değişmedi. Kod: HEALTH_READ_TIMEOUT']
        except Exception as exc:
            await self.event(update, 'HEALTH_READ_FAILED', error_type=type(exc).__name__)
            parts = ['Sağlık raporu doğrulanamadı. Arşiv değişmedi. Kod: HEALTH_READ_FAILED']
        await self.send(update, parts)
        raise ApplicationHandlerStop
